"""ShopBot Agent API (Step 3) - the endpoints the graders call.

    POST /chat    {"user_id": "...", "thread_id": "...", "message": "..."}
                  -> {"reply": "...", "tool_calls": [...], "tokens": {"in": 0, "out": 0}}
    GET  /health  -> ok

Memory:
- DATABASE_URL set (any Postgres: Render, Supabase, Neon) -> PostgresSaver (short-term, per thread) + PostgresStore (long-term, per user).
  Survives restarts.  This is what you deploy.
- DATABASE_URL empty                -> in-memory, for local testing only (lost on restart).

Run locally:  uvicorn app.api:app --reload --port 8000
"""
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

load_dotenv()
for _k in ("ANTHROPIC_API_KEY", "DATABASE_URL", "ADMIN_TOKEN", "SESSION_SECRET"):   # a pasted value often has a stray newline
    if os.getenv(_k):
        os.environ[_k] = os.environ[_k].strip()

from app import shop_tools as shop                             # noqa: E402
from app.shop_agent import build_shopbot, chat as run_chat   # noqa: E402  (after load_dotenv: needs the API key)

log = logging.getLogger("shopbot")
logging.basicConfig(level=logging.INFO)
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-admin")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-secret")
STATE: dict[str, Any] = {}


def _open_memory():
    if not DATABASE_URL:
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.store.memory import InMemoryStore
        log.warning("DATABASE_URL not set: memory is IN-MEMORY and will be lost on restart")
        return InMemorySaver(), InMemoryStore(), None
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore
    from psycopg_pool import ConnectionPool
    # No per-checkout health query (each one is a network round trip): instead keep connections alive with
    # TCP keepalives, retire them before the server's idle timeout, and retry a turn once if one was dropped.
    pool = ConnectionPool(DATABASE_URL, min_size=2, max_size=8, open=True, timeout=20, max_idle=120, max_lifetime=900,
                          kwargs={"autocommit": True, "prepare_threshold": None, "keepalives": 1,
                                  "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3})
    saver, store = PostgresSaver(pool), PostgresStore(pool)
    saver.setup()
    store.setup()
    log.info("Memory in Postgres (checkpointer + store)")
    return saver, store, pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    saver, store, pool = _open_memory()
    shop.seed_catalog(store)
    STATE["store"] = store
    STATE["graph"] = build_shopbot(checkpointer=saver, store=store)
    yield
    if pool:
        pool.close()


app = FastAPI(title="ShopBot Agent API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"reply": "Sorry, something went wrong.", "tool_calls": [],
                                                  "tokens": {"in": 0, "out": 0}})


class ChatIn(BaseModel):
    user_id: Any = None
    thread_id: Any = None
    message: Any = None


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    """One message at a time per conversation, so two quick messages can't corrupt the thread."""
    with _locks_guard:
        if len(_locks) > 5000:
            _locks.clear()
        return _locks.setdefault(key, threading.Lock())


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@app.get("/")
def root():
    return {"name": "ShopBot Agent API (TechTokri)", "endpoints": ["POST /chat", "GET /health"]}


@app.post("/chat")
def chat(body: ChatIn):
    t0 = time.time()
    user_id = str(body.user_id or "").strip()[:100]
    thread_id = str(body.thread_id or "").strip()[:100] or "default"
    message = str(body.message or "").strip()[:2000]
    empty = {"tool_calls": [], "tokens": {"in": 0, "out": 0}}
    if not user_id:
        return JSONResponse(status_code=400, content={"reply": "user_id is required.", **empty})
    if not message:
        return {"reply": "Hi! What can I help you find today?", **empty}
    try:
        with _lock(f"{user_id}::{thread_id}"):
            try:
                result = run_chat(STATE["graph"], user_id, thread_id, message)
            except psycopg.OperationalError:          # a dropped DB connection: the pool replaces it, retry once
                log.warning("database connection dropped, retrying turn once")
                result = run_chat(STATE["graph"], user_id, thread_id, message)
    except Exception as e:
        log.exception("chat failed")
        busy = any(w in str(e).lower() for w in ("overloaded", "rate", "credit", "billing", "timeout"))
        result = {"reply": "I'm a bit busy right now, please try again in a moment." if busy
                  else "Sorry, something went wrong on my side. Please try again.", **empty}
    latency = int((time.time() - t0) * 1000)
    log.info("chat user=%s thread=%s tools=%s tokens=%s %dms", user_id, thread_id,
             [c["name"] for c in result["tool_calls"]], result["tokens"], latency)
    blocked = result.pop("blocked", None)
    # dashboard log is written in the background: the customer doesn't wait for it
    threading.Thread(target=_log_turn, args=(user_id, thread_id, message, {**result, "blocked": blocked}, latency),
                     daemon=True).start()
    return result      # exactly {"reply", "tool_calls", "tokens"}


def _log_turn(user_id, thread_id, message, result, latency):
    """Every turn goes to ("chat_log", user_id) for the seller dashboard. Never breaks a chat."""
    try:
        STATE["store"].put(("chat_log", user_id), f"{time.time():.6f}-{secrets.token_hex(2)}", {
            "user_id": user_id, "thread_id": thread_id, "message": message[:1000], "reply": result["reply"][:2000],
            "tool_calls": result["tool_calls"], "tokens_in": result["tokens"]["in"], "tokens_out": result["tokens"]["out"],
            "latency_ms": latency, "blocked": result.get("blocked"), "created_at": shop.now_iso()})
    except Exception:
        log.exception("log failed")


# ═════════════════════ website: customer (signed session, so visitors can't read each other) ═════════════════════
def _sign(user_id: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:32]


def current_user(x_user_token: str = Header(default="")) -> str:
    uid, _, sig = x_user_token.rpartition(".")
    if not uid or not hmac.compare_digest(_sign(uid), sig):
        raise HTTPException(401, "missing or bad session")
    return uid


@app.post("/session")
def new_session():
    uid = "web_" + secrets.token_hex(6)
    return {"user_id": uid, "token": f"{uid}.{_sign(uid)}"}


def _pub(p: dict) -> dict:
    return {k: p[k] for k in ("id", "name", "category", "price", "stock", "description", "image")} | {"in_stock": p["stock"] > 0}


@app.get("/products")
def products(category: str = "", q: str = ""):
    store = STATE["store"]
    items = shop.find_products(store, q, category, limit=100) if q else sorted(
        shop.catalog(store).values(), key=lambda p: (p["category"], p["price"]))
    return [_pub(p) for p in items if not category or p["category"] == category]


class CartIn(BaseModel):
    product_id: str
    qty: int = 1


class CheckoutIn(BaseModel):
    shipping_address: str
    discount_code: str = ""


@app.get("/me/cart")
def me_cart(uid: str = Depends(current_user), discount_code: str = ""):
    return shop.cart_summary(STATE["store"], uid, discount_code)


@app.post("/me/cart")
def me_cart_add(body: CartIn, uid: str = Depends(current_user)):
    return shop.add_item(STATE["store"], uid, body.product_id, body.qty)


@app.delete("/me/cart/{product_id}")
def me_cart_remove(product_id: str, uid: str = Depends(current_user)):
    return shop.remove_item(STATE["store"], uid, product_id)


@app.post("/me/checkout")
def me_checkout(body: CheckoutIn, uid: str = Depends(current_user)):
    # The website shows the total and a "Yes, place order" button: that click is the human confirmation.
    return shop.create_order(STATE["store"], uid, body.shipping_address, body.discount_code)


@app.get("/me/orders")
def me_orders(uid: str = Depends(current_user)):
    return shop.list_orders(STATE["store"], uid)


def _memory_dict(store, uid):
    out, n = {}, 0
    for i in store.search(shop.memory_namespace(uid), limit=50):
        fact = i.value["fact"]
        if i.key.startswith("auto-") and ": " in fact:
            k, v = fact.split(": ", 1)
            out[k] = v
        else:
            n += 1
            out[f"note {n}"] = fact
    return out


@app.get("/me/memory")
def me_memory(uid: str = Depends(current_user)):
    return _memory_dict(STATE["store"], uid)


@app.delete("/me/memory")
def me_forget(uid: str = Depends(current_user)):
    store = STATE["store"]
    for i in store.search(shop.memory_namespace(uid), limit=100):
        store.delete(i.namespace, i.key)
    return {"ok": True}


# ═════════════════════ website: seller admin (X-Admin-Token) ═════════════════════
def admin(x_admin_token: str = Header(default="")):
    if not hmac.compare_digest(x_admin_token or "", ADMIN_TOKEN):
        raise HTTPException(401, "admin only")


def _logs(store, user_id: str = ""):
    ns = ("chat_log", user_id) if user_id else ("chat_log",)
    return sorted((i.value for i in store.search(ns, limit=5000)), key=lambda r: r["created_at"], reverse=True)


@app.get("/admin/stats", dependencies=[Depends(admin)])
def admin_stats():
    store = STATE["store"]
    orders, logs = shop.list_orders(store), _logs(store)
    live = [o for o in orders if o["status"] != "cancelled"]
    tools, by_status, daily = {}, {}, {}
    for r in logs:
        for t in r["tool_calls"]:
            tools[t["name"]] = tools.get(t["name"], 0) + 1
        d = daily.setdefault(r["created_at"][:10], {"day": r["created_at"][:10], "chats": 0, "tin": 0, "tout": 0})
        d["chats"] += 1; d["tin"] += r["tokens_in"]; d["tout"] += r["tokens_out"]
    for o in orders:
        by_status[o["status"]] = by_status.get(o["status"], 0) + 1
    tin, tout = sum(r["tokens_in"] for r in logs), sum(r["tokens_out"] for r in logs)
    return {"orders": len(orders), "revenue": sum(o["total"] for o in live), "buyers": len({o["user_id"] for o in orders}),
            "chats": len(logs), "users": len({r["user_id"] for r in logs}),
            "threads": len({(r["user_id"], r["thread_id"]) for r in logs}), "tin": tin, "tout": tout,
            "avg_ms": int(sum(r["latency_ms"] for r in logs) / len(logs)) if logs else 0,
            "blocked": sum(1 for r in logs if r.get("blocked")),
            "est_cost_usd": round((tin * 1.0 + tout * 5.0) / 1e6, 4),   # Haiku-class estimate, USD per 1M tokens
            "tools": [{"name": k, "n": v} for k, v in sorted(tools.items(), key=lambda t: -t[1])],
            "low_stock": [{"id": p["id"], "name": p["name"], "stock": p["stock"]}
                          for p in sorted(shop.catalog(store).values(), key=lambda p: p["stock"]) if p["stock"] <= 5],
            "orders_by_status": [{"status": k, "n": v} for k, v in by_status.items()],
            "daily": sorted(daily.values(), key=lambda d: d["day"], reverse=True)[:14]}


@app.get("/admin/orders", dependencies=[Depends(admin)])
def admin_orders():
    return shop.list_orders(STATE["store"])[:300]


class StatusIn(BaseModel):
    status: str


@app.patch("/admin/orders/{user_id}/{order_id}", dependencies=[Depends(admin)])
def admin_order_status(user_id: str, order_id: str, body: StatusIn):
    if body.status not in ("pending", "confirmed", "shipped", "delivered", "cancelled"):
        raise HTTPException(400, "bad status")
    shop.set_order_status(STATE["store"], user_id, order_id, body.status)
    return {"ok": True}


class ProductIn(BaseModel):
    id: str | None = None
    name: str
    category: str
    price: int
    stock: int
    description: str = ""
    tags: str = ""
    image: str = "📦"
    active: bool = True


@app.get("/admin/products", dependencies=[Depends(admin)])
def admin_products():
    return sorted(shop.catalog(STATE["store"], include_inactive=True).values(), key=lambda p: (p["category"], p["price"]))


@app.post("/admin/products", dependencies=[Depends(admin)])
@app.put("/admin/products/{pid}", dependencies=[Depends(admin)])
def admin_product_save(p: ProductIn, pid: str = ""):
    key = (pid or p.id or "NEW-" + secrets.token_hex(2)).upper()
    STATE["store"].put(shop.CATALOG_NS, key, {**p.model_dump(), "id": key, "category": p.category.lower()})
    return {"ok": True, "id": key}


class ImportIn(BaseModel):
    csv: str


@app.post("/admin/products/import", dependencies=[Depends(admin)])
def admin_products_import(body: ImportIn):
    """Seller uploads a catalogue as CSV: id,name,category,price,stock,description,tags (header row required).
    New ids are added, existing ids are updated. Returns how many rows were saved and any row errors."""
    import csv
    import io
    store, saved, errors = STATE["store"], 0, []
    for n, row in enumerate(csv.DictReader(io.StringIO(body.csv.strip())), start=2):
        try:
            row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            pid = (row.get("id") or "").upper() or "NEW-" + secrets.token_hex(2).upper()
            old = (store.get(shop.CATALOG_NS, pid).value if store.get(shop.CATALOG_NS, pid) else {})
            item = {"id": pid, "name": row["name"], "category": row.get("category", "other").lower() or "other",
                    "price": int(float(row["price"])), "stock": int(float(row.get("stock") or 0)),
                    "description": row.get("description", ""), "tags": row.get("tags", ""),
                    "image": row.get("image") or old.get("image", "📦"), "active": True}
            if not item["name"] or item["price"] < 0:
                raise ValueError("name and a price >= 0 are required")
            store.put(shop.CATALOG_NS, pid, item)
            saved += 1
        except Exception as e:
            errors.append(f"row {n}: {e}")
    return {"saved": saved, "errors": errors[:20]}


@app.get("/admin/customers", dependencies=[Depends(admin)])
def admin_customers():
    store = STATE["store"]
    users: dict[str, dict] = {}
    for r in _logs(store):
        u = users.setdefault(r["user_id"], {"user_id": r["user_id"], "messages": 0, "threads": set(), "last_seen": r["created_at"]})
        u["messages"] += 1; u["threads"].add(r["thread_id"])
    for o in shop.list_orders(store):
        users.setdefault(o["user_id"], {"user_id": o["user_id"], "messages": 0, "threads": set(), "last_seen": o["created_at"]})
    out = []
    for uid, u in users.items():
        mine = shop.list_orders(store, uid)
        out.append({**u, "threads": len(u["threads"]), "memory": _memory_dict(store, uid) or None, "orders": len(mine),
                    "spent": sum(o["total"] for o in mine if o["status"] != "cancelled")})
    return sorted(out, key=lambda u: u["last_seen"], reverse=True)[:200]


@app.get("/admin/logs", dependencies=[Depends(admin)])
def admin_logs(limit: int = 100, user_id: str = ""):
    return [{**r, "id": f"{r['created_at']}-{n}"} for n, r in enumerate(_logs(STATE["store"], user_id)[:min(limit, 500)])]
