"use client";
import { useCallback, useEffect, useState } from "react";
import Header from "@/components/Header";
import { adminFetch, pkr } from "@/lib/api";

const TABS = ["Overview", "Orders", "Products", "Customers", "Agent activity"];
const STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"];

export default function Admin() {
  const [token, setToken] = useState("");
  const [ok, setOk] = useState(false);
  const [tab, setTab] = useState("Overview");
  const [err, setErr] = useState("");

  useEffect(() => { const t = sessionStorage.getItem("tt_admin"); if (t) { setToken(t); setOk(true); } }, []);
  async function login(e) {
    e.preventDefault();
    try { await adminFetch("/admin/stats", token); sessionStorage.setItem("tt_admin", token); setOk(true); setErr(""); }
    catch { setErr("Wrong admin token"); }
  }
  if (!ok) return (
    <><Header admin /><main className="wrap page narrow">
      <h1>Seller admin</h1>
      <form onSubmit={login} className="login"><input type="password" placeholder="Admin token" value={token} onChange={(e) => setToken(e.target.value)} /><button className="primary">Sign in</button></form>
      {err && <p className="warn">{err}</p>}
    </main></>
  );
  return (
    <><Header admin />
      <main className="wrap page">
        <div className="admin-head"><h1>Seller dashboard</h1>
          <button className="ghost" onClick={() => { sessionStorage.removeItem("tt_admin"); setOk(false); setToken(""); }}>Sign out</button></div>
        <div className="tabs">{TABS.map((t) => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</div>
        {tab === "Overview" && <Overview token={token} />}
        {tab === "Orders" && <OrdersTab token={token} />}
        {tab === "Products" && <ProductsTab token={token} />}
        {tab === "Customers" && <CustomersTab token={token} />}
        {tab === "Agent activity" && <LogsTab token={token} />}
      </main></>
  );
}

function useData(path, token) {
  const [data, setData] = useState(null);
  const load = useCallback(() => adminFetch(path, token).then(setData).catch(() => setData([])), [path, token]);
  useEffect(() => { load(); }, [load]);
  return [data, load];
}

function Overview({ token }) {
  const [s] = useData("/admin/stats", token);
  if (!s) return <p>Loading…</p>;
  const maxTool = Math.max(1, ...(s.tools || []).map((t) => t.n));
  const kpis = [
    ["Revenue", pkr(s.revenue)], ["Orders", s.orders], ["Buyers", s.buyers], ["Chat users", s.users],
    ["Conversations", s.threads], ["Messages", s.chats], ["Blocked (safety)", s.blocked], ["Avg latency", `${(s.avg_ms / 1000).toFixed(1)}s`],
    ["Tokens in / out", `${(s.tin / 1000).toFixed(1)}k / ${(s.tout / 1000).toFixed(1)}k`], ["Est. API cost", `$${s.est_cost_usd}`],
  ];
  return (
    <div className="overview">
      <div className="kpis">{kpis.map(([k, v]) => <div className="kpi" key={k}><span>{k}</span><b>{v}</b></div>)}</div>
      <div className="cols">
        <div className="box"><h3>Tool usage by the agent</h3>
          {(s.tools || []).length === 0 ? <p className="muted">No tool calls yet.</p> : s.tools.map((t) => (
            <div className="bar" key={t.name}><span>{t.name}</span><div><i style={{ width: `${(t.n / maxTool) * 100}%` }} /></div><b>{t.n}</b></div>))}
        </div>
        <div className="box"><h3>Orders by status</h3>
          {(s.orders_by_status || []).map((o) => <div className="kv" key={o.status}><span className={`badge ${o.status}`}>{o.status}</span><b>{o.n}</b></div>)}
          <h3 style={{ marginTop: 18 }}>Low stock</h3>
          {(s.low_stock || []).map((p) => <div className="kv" key={p.id}><span>{p.name}</span><b className={p.stock === 0 ? "red" : ""}>{p.stock}</b></div>)}
        </div>
        <div className="box"><h3>Daily usage</h3>
          <table><thead><tr><th>Day</th><th>Msgs</th><th>Tokens in</th><th>out</th></tr></thead>
            <tbody>{(s.daily || []).map((d) => <tr key={d.day}><td>{d.day}</td><td>{d.chats}</td><td>{d.tin}</td><td>{d.tout}</td></tr>)}</tbody></table>
        </div>
      </div>
    </div>
  );
}

function OrdersTab({ token }) {
  const [rows, load] = useData("/admin/orders", token);
  async function setStatus(uid, id, status) { await adminFetch(`/admin/orders/${encodeURIComponent(uid)}/${id}`, token, { method: "PATCH", body: JSON.stringify({ status }) }); load(); }
  if (!rows) return <p>Loading…</p>;
  return (
    <table className="table"><thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Address</th><th>Placed</th><th>Status</th></tr></thead>
      <tbody>{rows.map((o) => (
        <tr key={o.order_id}><td><b>{o.order_id}</b></td><td><code>{o.user_id}</code></td>
          <td>{o.items.map((i) => `${i.qty}× ${i.name}`).join(", ")}</td><td>{pkr(o.total)}{o.discount_code ? <div className="muted">{o.discount_code}</div> : null}</td>
          <td className="muted">{o.shipping_address}</td><td className="muted">{new Date(o.created_at).toLocaleString()}</td>
          <td><select value={o.status} onChange={(e) => setStatus(o.user_id, o.order_id, e.target.value)}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></td></tr>))}
      </tbody></table>
  );
}

const EMPTY = { id: "", name: "", category: "audio", price: 0, stock: 0, description: "", tags: "", image: "📦", active: true };
function ProductsTab({ token }) {
  const [rows, load] = useData("/admin/products", token);
  const [edit, setEdit] = useState(null);
  async function save() {
    const body = JSON.stringify({ ...edit, price: +edit.price, stock: +edit.stock });
    if (edit._new) await adminFetch("/admin/products", token, { method: "POST", body });
    else await adminFetch(`/admin/products/${edit.id}`, token, { method: "PUT", body });
    setEdit(null); load();
  }
  if (!rows) return <p>Loading…</p>;
  return (
    <>
      <button className="primary" onClick={() => setEdit({ ...EMPTY, _new: true })}>+ Add product</button>
      {edit && (
        <div className="editor">
          {["id", "name", "category", "price", "stock", "image", "tags"].map((f) => (
            <label key={f}>{f}<input value={edit[f]} disabled={f === "id" && !edit._new} onChange={(e) => setEdit({ ...edit, [f]: e.target.value })} /></label>))}
          <label className="wide">description<textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></label>
          <label><span>active</span><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /></label>
          <div><button className="primary" onClick={save}>Save</button> <button className="ghost" onClick={() => setEdit(null)}>Cancel</button></div>
        </div>
      )}
      <table className="table"><thead><tr><th></th><th>ID</th><th>Name</th><th>Category</th><th>Price</th><th>Stock</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((p) => (
          <tr key={p.id} className={p.active ? "" : "dim"}><td>{p.image}</td><td><code>{p.id}</code></td><td>{p.name}</td><td>{p.category}</td><td>{pkr(p.price)}</td>
            <td className={p.stock === 0 ? "red" : ""}>{p.stock}</td><td>{p.active ? "yes" : "no"}</td><td><button className="ghost" onClick={() => setEdit({ ...p })}>Edit</button></td></tr>))}
        </tbody></table>
    </>
  );
}

function CustomersTab({ token }) {
  const [rows] = useData("/admin/customers", token);
  const [sel, setSel] = useState(null);
  if (!rows) return <p>Loading…</p>;
  return (
    <div className="cols two">
      <table className="table"><thead><tr><th>Customer</th><th>Long-term memory</th><th>Orders</th><th>Spent</th><th>Chats</th></tr></thead>
        <tbody>{rows.map((u) => (
          <tr key={u.user_id} className={sel === u.user_id ? "sel" : ""} onClick={() => setSel(u.user_id)}>
            <td><code>{u.user_id}</code><div className="muted">{u.last_seen ? new Date(u.last_seen).toLocaleString() : ""}</div></td>
            <td>{u.memory ? Object.entries(u.memory).map(([k, v]) => <span className="fact" key={k}>{k}: {v}</span>) : <span className="muted">—</span>}</td>
            <td>{u.orders}</td><td>{pkr(u.spent)}</td><td>{u.messages} msgs / {u.threads} threads</td></tr>))}
        </tbody></table>
      <div>{sel ? <LogsTab token={token} userId={sel} /> : <p className="muted">Click a customer to see their conversations.</p>}</div>
    </div>
  );
}

function LogsTab({ token, userId }) {
  const [rows] = useData(`/admin/logs?limit=150${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`, token);
  if (!rows) return <p>Loading…</p>;
  return (
    <div className="logs">{rows.map((r) => (
      <div className={`log ${r.blocked ? "blocked" : ""}`} key={r.id}>
        <div className="log-head"><code>{r.user_id}</code> · <code>{r.thread_id}</code> · {new Date(r.created_at).toLocaleTimeString()} · {r.latency_ms} ms · {r.tokens_in}/{r.tokens_out} tok
          {r.blocked && <span className="badge cancelled">blocked: {r.blocked}</span>}</div>
        <p><b>Customer:</b> {r.message}</p>
        {r.tool_calls?.length > 0 && <div className="tools">{r.tool_calls.map((t, i) => <span key={i}>⚙ {t.name}({Object.entries(t.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})</span>)}</div>}
        <p><b>ShopBot:</b> {r.reply}</p>
      </div>))}
    </div>
  );
}
