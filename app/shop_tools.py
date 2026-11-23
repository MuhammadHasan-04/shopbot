"""ShopBot tools (Track 1).
- WHO is shopping comes from runtime.context (set by the app), never from a model argument,
  so one customer can never read or change another customer's cart, orders or memories.
- ALL shop data lives in the LangGraph store (PostgreSQL when deployed, nothing in RAM):
      ("catalog",)             product id -> product (seeded from data/products.json)
      ("carts", user_id)       "cart"     -> {"items": {product_id: qty}}
      ("orders", user_id)      order id   -> order
      ("shop_memories", user_id)          -> long-term facts about the customer
- Risky actions (placing / cancelling an order) pause with interrupt() and wait for a human "yes".
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from app.context import DATA

SEED = json.loads((DATA / "products.json").read_text(encoding="utf-8"))
POLICIES = SEED["policies"]
DISCOUNTS = SEED["discount_codes"]
SHIPPING_FEE = SEED["shipping_fee"]
FREE_SHIPPING_MIN = SEED["free_shipping_min"]
CATALOG_NS = ("catalog",)
LIMIT = 1000


@dataclass
class ShopContext:
    """Set by the app (login / API request), never by the chat."""
    user_id: str = "ali"
    role: str = "customer"      # "customer" or "seller"
    language: str = "English"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pkr(n: int) -> str:
    return f"Rs {n:,}"


# ───────────── store helpers (plain functions: used by tools, the API and tests) ─────────────

def seed_catalog(store):
    if not store.search(CATALOG_NS, limit=1):
        for p in SEED["products"]:
            store.put(CATALOG_NS, p["id"], {**p, "active": True})


def catalog(store, include_inactive=False) -> dict[str, dict]:
    seed_catalog(store)
    items = {i.key: i.value for i in store.search(CATALOG_NS, limit=LIMIT)}
    return items if include_inactive else {k: v for k, v in items.items() if v.get("active", True)}


def get_item(store, pid: str):
    item = store.get(CATALOG_NS, (pid or "").strip().upper())
    if item is None and not store.search(CATALOG_NS, limit=1):
        seed_catalog(store)
        item = store.get(CATALOG_NS, (pid or "").strip().upper())
    return item.value if item and item.value.get("active", True) else None


def set_stock(store, pid: str, delta: int):
    item = store.get(CATALOG_NS, pid)
    if item:
        store.put(CATALOG_NS, pid, {**item.value, "stock": max(0, item.value["stock"] + delta)})


STOPWORDS = {"a", "an", "the", "for", "with", "and", "or", "me", "show", "some", "any", "i", "want", "need",
             "under", "below", "less", "than", "rs", "pkr", "cheap", "best", "good", "of", "to", "in", "my"}


def find_products(store, query: str = "", category: str = "", max_price: int = 0, limit: int = 5) -> list[dict]:
    words = [w.rstrip("s") for w in re.findall(r"[a-z0-9\-]+", (query or "").lower()) if w not in STOPWORDS]
    hits = []
    for p in catalog(store).values():
        if category and category.lower() not in p["category"]:
            continue
        if max_price and p["price"] > max_price:
            continue
        text = f"{p['name']} {p['category']} {p['tags']} {p['description']}".lower()
        score = sum(w in text for w in words) if words else 1
        if score:
            hits.append((score, p))
    hits.sort(key=lambda t: (-t[0], t[1]["stock"] == 0, t[1]["price"]))
    return [p for _, p in hits[:limit]]


def get_cart(store, uid: str) -> dict[str, int]:
    item = store.get(("carts", uid), "cart")
    return dict(item.value["items"]) if item else {}


def save_cart(store, uid: str, items: dict[str, int]):
    store.put(("carts", uid), "cart", {"items": items})


def list_orders(store, uid: str | None = None) -> list[dict]:
    ns = ("orders", uid) if uid else ("orders",)
    orders = [i.value for i in store.search(ns, limit=LIMIT)]
    return sorted(orders, key=lambda o: o["created_at"], reverse=True)


def cart_summary(store, uid: str, discount_code: str = "") -> dict:
    cat = catalog(store, include_inactive=True)
    items = [{"product_id": pid, "name": cat[pid]["name"], "qty": q, "unit_price": cat[pid]["price"],
              "line_total": q * cat[pid]["price"]} for pid, q in get_cart(store, uid).items() if pid in cat]
    subtotal = sum(i["line_total"] for i in items)
    discount, note = 0, ""
    code = (discount_code or "").strip().upper()
    if code:
        d = DISCOUNTS.get(code)
        first_order = not any(o["status"] != "cancelled" for o in list_orders(store, uid))
        if not d:
            note = f"Code {code} is not valid."
        elif subtotal < d["min"]:
            note = f"Code {code} needs a subtotal of {pkr(d['min'])}."
        elif d["first_order_only"] and not first_order:
            note = f"Code {code} is only for a first order."
        else:
            discount = round(subtotal * d["value"] / 100) if d["type"] == "percent" else d["value"]
    shipping = 0 if not items or subtotal - discount >= FREE_SHIPPING_MIN else SHIPPING_FEE
    return {"items": items, "subtotal": subtotal, "discount": discount, "discount_code": code if discount else "",
            "shipping": shipping, "total": subtotal - discount + shipping, "note": note}


def format_cart(c: dict) -> str:
    if not c["items"]:
        return "The cart is empty."
    rows = [f"- {i['qty']} x {i['name']} ({i['product_id']}) = {pkr(i['line_total'])}" for i in c["items"]]
    rows.append(f"Subtotal {pkr(c['subtotal'])}")
    if c["discount"]:
        rows.append(f"Discount ({c['discount_code']}) -{pkr(c['discount'])}")
    rows.append(f"Delivery {pkr(c['shipping']) if c['shipping'] else 'FREE'}")
    rows.append(f"TOTAL {pkr(c['total'])}")
    if c["note"]:
        rows.append(c["note"])
    return "\n".join(rows)


def add_item(store, uid: str, pid: str, qty: int = 1) -> dict:
    p = get_item(store, pid)
    if not p:
        return {"error": f"No product with id {pid}."}
    cart = get_cart(store, uid)
    new_qty = cart.get(p["id"], 0) + max(1, min(int(qty or 1), 10))
    if new_qty > p["stock"]:
        return {"error": f"{p['name']} is out of stock." if not p["stock"] else f"Only {p['stock']} of {p['name']} left."}
    cart[p["id"]] = new_qty
    save_cart(store, uid, cart)
    return {"ok": True, "added": p["name"], "cart": cart_summary(store, uid)}


def remove_item(store, uid: str, pid: str) -> dict:
    cart = get_cart(store, uid)
    if cart.pop((pid or "").strip().upper(), None) is None:
        return {"error": f"{pid} is not in the cart."}
    save_cart(store, uid, cart)
    return {"ok": True, "cart": cart_summary(store, uid)}


def create_order(store, uid: str, shipping_address: str, discount_code: str = "") -> dict:
    """Places the order. Callers must have the customer's confirmation first."""
    c = cart_summary(store, uid, discount_code)
    if not c["items"]:
        return {"error": "The cart is empty."}
    if len((shipping_address or "").strip()) < 5:
        return {"error": "A delivery address with city is required."}
    for i in c["items"]:
        p = get_item(store, i["product_id"])
        if not p or p["stock"] < i["qty"]:
            return {"error": f"Sorry, {i['name']} just went out of stock."}
    for i in c["items"]:
        set_stock(store, i["product_id"], -i["qty"])
    order = {"order_id": "ORD-" + uuid4().hex[:6].upper(), "user_id": uid, **c, "shipping_address": shipping_address.strip(),
             "status": "pending", "created_at": now_iso()}
    order.pop("note", None)
    store.put(("orders", uid), order["order_id"], order)
    save_cart(store, uid, {})
    return {"ok": True, **order}


def set_order_status(store, uid: str, oid: str, status: str):
    item = store.get(("orders", uid), oid)
    if item:
        store.put(("orders", uid), oid, {**item.value, "status": status})


def is_yes(answer) -> bool:
    """A human approval counts only if it is an explicit yes."""
    text = str(answer.get("answer", "") if isinstance(answer, dict) else answer).strip().lower()
    return bool(re.match(r"^(yes|y|yeah|yep|sure|confirm|ok|okay|haan|han|ji|jee|go ahead|place it|please do)\b", text)) \
        and not re.search(r"\b(no|not|don'?t|nahi)\b", text)


# ───────────── catalogue tools ─────────────

@tool
def search_products(runtime: ToolRuntime[ShopContext], query: str = "", category: str = "", max_price: int = 0) -> str:
    """Search the TechTokri catalogue. query = keywords like 'wireless earbuds'.
    category: audio, charging, phone accessories, wearables, smart home, laptop accessories.
    max_price in PKR (0 = no limit)."""
    found = find_products(runtime.store, query, category, max_price)
    if not found:
        return "No matching products. Try fewer words or a higher budget."
    return "\n".join(f"{p['id']} | {p['name']} | {pkr(p['price'])} | "
                     f"{'in stock' if p['stock'] else 'OUT OF STOCK'} | {p['description']}" for p in found)


@tool
def get_product(product_id: str, runtime: ToolRuntime[ShopContext]) -> str:
    """Get full details, price and live stock for one product id, e.g. AUD-101."""
    p = get_item(runtime.store, product_id)
    if not p:
        return f"No product with id {product_id}."
    stock = f"{p['stock']} in stock" if p["stock"] else "OUT OF STOCK"
    return f"{p['id']} {p['name']} | {pkr(p['price'])} | {stock} | {p['category']} | {p['description']}"


@tool
def store_policy(topic: str = "") -> str:
    """Store policies. topic: shipping, returns, warranty, payment, discounts, contact or hours."""
    t = topic.lower()
    aliases = {"deliver": "shipping", "refund": "returns", "return": "returns", "pay": "payment", "cod": "payment",
               "code": "discounts", "coupon": "discounts", "discount": "discounts", "whatsapp": "contact"}
    keys = [k for k in POLICIES if t and (k in t or t in k)] + [v for a, v in aliases.items() if a in t]
    return "\n".join(f"{k}: {POLICIES[k]}" for k in (dict.fromkeys(keys) or POLICIES))


# ───────────── cart tools ─────────────

@tool
def add_to_cart(product_id: str, runtime: ToolRuntime[ShopContext], qty: int = 1) -> str:
    """Add a product to this customer's cart."""
    r = add_item(runtime.store, runtime.context.user_id, product_id, qty)
    return r["error"] if "error" in r else f"Added {r['added']}.\n" + format_cart(r["cart"])


@tool
def remove_from_cart(product_id: str, runtime: ToolRuntime[ShopContext]) -> str:
    """Remove a product from this customer's cart."""
    r = remove_item(runtime.store, runtime.context.user_id, product_id)
    return r["error"] if "error" in r else "Removed.\n" + format_cart(r["cart"])


@tool
def view_cart(runtime: ToolRuntime[ShopContext], discount_code: str = "") -> str:
    """Show this customer's cart with subtotal, discount, delivery and total."""
    return format_cart(cart_summary(runtime.store, runtime.context.user_id, discount_code))


# ───────────── order tools (RISKY: a human must say yes) ─────────────

@tool
def place_order(shipping_address: str, runtime: ToolRuntime[ShopContext], discount_code: str = "") -> str:
    """Place an order for everything in the cart. Needs a delivery address with city.
    The customer is asked to approve the summary before anything is placed."""
    store, uid = runtime.store, runtime.context.user_id
    c = cart_summary(store, uid, discount_code)
    if not c["items"]:
        return "The cart is empty. Add products first."
    if len(shipping_address.strip()) < 5:
        return "Ask the customer for a full delivery address with city."
    answer = interrupt({"action": "place_order", "summary": format_cart(c) + f"\nDeliver to: {shipping_address.strip()}"
                        + "\nPayment: Cash on Delivery", "question": "Place this order? Reply yes or no."})
    if not is_yes(answer):
        return "Customer did not approve. Order NOT placed. Cart kept."
    r = create_order(store, uid, shipping_address, discount_code)
    if "error" in r:
        return r["error"] + " Order NOT placed."
    return (f"Order {r['order_id']} placed. Total {pkr(r['total'])}, Cash on Delivery, "
            f"arrives in 2-5 working days at {r['shipping_address']}.")


@tool
def my_orders(runtime: ToolRuntime[ShopContext], order_id: str = "") -> str:
    """Show this customer's own orders and their status (or one order by id)."""
    mine = [o for o in list_orders(runtime.store, runtime.context.user_id)
            if not order_id or o["order_id"] == order_id.strip().upper()]
    if not mine:
        return "No orders found on this account."
    return "\n".join(f"{o['order_id']} | {o['status']} | {pkr(o['total'])} | {o['created_at'][:16]} | "
                     + ", ".join(f"{i['qty']}x {i['name']}" for i in o["items"]) for o in mine[:10])


@tool
def cancel_order(order_id: str, runtime: ToolRuntime[ShopContext]) -> str:
    """Cancel one of this customer's pending orders. The customer is asked to approve first."""
    store, uid, oid = runtime.store, runtime.context.user_id, order_id.strip().upper()
    item = store.get(("orders", uid), oid)
    if not item:
        return f"No order {order_id} on this account."
    o = item.value
    if o["status"] not in ("pending", "confirmed"):
        return f"Order {oid} is {o['status']} and can't be cancelled."
    answer = interrupt({"action": "cancel_order", "summary": f"Order {oid}, total {pkr(o['total'])}",
                        "question": f"Cancel order {oid}? Reply yes or no."})
    if not is_yes(answer):
        return f"Order {oid} kept."
    set_order_status(store, uid, oid, "cancelled")
    for i in o["items"]:
        set_stock(store, i["product_id"], i["qty"])
    return f"Order {oid} cancelled."


# ───────────── seller-only tool ─────────────

def report(store) -> dict:
    live = [o for o in list_orders(store) if o["status"] != "cancelled"]
    sold: dict[str, int] = {}
    for o in live:
        for i in o["items"]:
            sold[i["name"]] = sold.get(i["name"], 0) + i["qty"]
    return {"orders": len(live), "revenue": sum(o["total"] for o in live),
            "best": sorted(sold.items(), key=lambda t: -t[1])[:3],
            "low": [(p["name"], p["stock"]) for p in catalog(store).values() if p["stock"] <= 5]}


@tool
def sales_report(runtime: ToolRuntime[ShopContext]) -> str:
    """For the SELLER only: orders, revenue, best sellers and low-stock products."""
    if runtime.context.role != "seller":
        return "Only the seller can see sales reports."
    r = report(runtime.store)
    best = ", ".join(f"{n} ({q})" for n, q in r["best"]) or "none yet"
    low = ", ".join(f"{n} ({s})" for n, s in r["low"]) or "none"
    return f"Orders: {r['orders']} | Revenue: {pkr(r['revenue'])} | Best sellers: {best} | Low stock: {low}"


# ───────────── long-term memory (per user_id, across conversations) ─────────────

def memory_namespace(user_id: str):
    return ("shop_memories", user_id)


@tool
def remember_preference(fact: str, runtime: ToolRuntime[ShopContext]) -> str:
    """Save a lasting fact about this customer for next time, e.g. 'uses an iPhone 15', 'budget about Rs 5,000'."""
    ns = memory_namespace(runtime.context.user_id)
    existing = runtime.store.search(ns, limit=50)
    if any(fact.strip().lower() in i.value["fact"].lower() for i in existing):
        return f"Already remembered: {fact}"
    if len(existing) >= 25:
        oldest = sorted(runtime.store.search(ns, limit=50), key=lambda i: i.updated_at)[0]
        runtime.store.delete(ns, oldest.key)
    runtime.store.put(ns, str(uuid4()), {"fact": fact[:200]})
    return f"Remembered: {fact}"


@tool
def recall_preferences(runtime: ToolRuntime[ShopContext]) -> str:
    """Everything remembered about this customer from earlier conversations."""
    items = runtime.store.search(memory_namespace(runtime.context.user_id), limit=25)
    return "\n".join(f"- {i.value['fact']}" for i in items) or "Nothing remembered yet."


CUSTOMER_TOOLS = [search_products, get_product, store_policy, add_to_cart, remove_from_cart, view_cart,
                  place_order, my_orders, cancel_order, remember_preference, recall_preferences]
SELLER_ONLY = {"sales_report"}
SHOP_TOOLS = CUSTOMER_TOOLS + [sales_report]
