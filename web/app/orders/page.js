"use client";
import { useEffect, useState } from "react";
import Chat from "@/components/Chat";
import Header from "@/components/Header";
import { getSession, pkr, userFetch } from "@/lib/api";

export default function Orders() {
  const [orders, setOrders] = useState(null);
  const [memory, setMemory] = useState({});
  const [uid, setUid] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [prefill, setPrefill] = useState(null);

  function load() {
    getSession().then((s) => setUid(s.user_id));
    userFetch("/me/orders").then(setOrders).catch(() => setOrders([]));
    userFetch("/me/memory").then(setMemory).catch(() => {});
  }
  useEffect(load, []);
  async function forget() { await userFetch("/me/memory", { method: "DELETE" }); load(); }

  return (
    <>
      <Header />
      <main className="wrap page">
        <h1>My orders</h1>
        <p className="muted">Signed in on this browser as <code>{uid}</code>. Only your own orders are shown.</p>
        {orders === null ? <p>Loading…</p> : orders.length === 0 ? <p className="muted">No orders yet.</p> : (
          <div className="orders">
            {orders.map((o) => (
              <div className="order" key={o.order_id}>
                <div className="o-head"><b>{o.order_id}</b><span className={`badge ${o.status}`}>{o.status}</span></div>
                <ul>{o.items.map((i) => <li key={i.product_id}>{i.qty} × {i.name}</li>)}</ul>
                <div className="o-foot"><span>{new Date(o.created_at).toLocaleString()}</span><b>{pkr(o.total)}</b></div>
                <div className="o-foot"><span className="muted">{o.shipping_address}</span>
                  {["pending", "confirmed"].includes(o.status) && <button className="ghost" onClick={() => setPrefill({ text: `I want to cancel order ${o.order_id}`, k: Date.now() })}>Cancel via ShopBot</button>}
                </div>
              </div>
            ))}
          </div>
        )}
        <h2>What ShopBot remembers about you</h2>
        <p className="muted">Long-term memory, kept across conversations. Only you (and the seller) can see it.</p>
        {Object.keys(memory).length === 0 ? <p className="muted">Nothing yet. Tell ShopBot your name, phone model or budget.</p> : (
          <dl className="memory">{Object.entries(memory).map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{v}</dd></div>)}</dl>
        )}
        {Object.keys(memory).length > 0 && <button className="ghost" onClick={forget}>Forget everything about me</button>}
      </main>
      <Chat onAction={load} prefill={prefill} open={chatOpen} setOpen={setChatOpen} />
    </>
  );
}
