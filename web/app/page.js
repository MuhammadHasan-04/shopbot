"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import Chat from "@/components/Chat";
import Header from "@/components/Header";
import { API, pkr, userFetch } from "@/lib/api";

const CATS = ["all", "audio", "charging", "phone accessories", "wearables", "smart home", "laptop accessories"];

export default function Shop() {
  const [products, setProducts] = useState([]);
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState({ items: [], subtotal: 0, total: 0, shipping: 0, discount: 0 });
  const [cartOpen, setCartOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [prefill, setPrefill] = useState(null);
  const [toast, setToast] = useState("");
  const [err, setErr] = useState("");

  const loadProducts = useCallback(() => {
    fetch(`${API}/products`).then((r) => r.json()).then(setProducts).catch(() => setErr("Store is waking up… refresh in a few seconds."));
  }, []);
  const loadCart = useCallback((code = "") => {
    userFetch(`/me/cart${code ? `?discount_code=${encodeURIComponent(code)}` : ""}`).then(setCart).catch(() => {});
  }, []);
  useEffect(() => { loadProducts(); loadCart(); }, [loadProducts, loadCart]);

  const shown = useMemo(() => products.filter((p) =>
    (cat === "all" || p.category === cat) &&
    (!q || `${p.name} ${p.description} ${p.category}`.toLowerCase().includes(q.toLowerCase()))), [products, cat, q]);

  function flash(t) { setToast(t); setTimeout(() => setToast(""), 2200); }
  async function add(p) {
    const r = await userFetch("/me/cart", { method: "POST", body: JSON.stringify({ product_id: p.id, qty: 1 }) });
    if (r.error) flash(r.error); else { flash(`Added ${p.name}`); loadCart(); }
  }
  const count = cart.items.reduce((a, i) => a + i.qty, 0);

  return (
    <>
      <Header cartCount={count} onCart={() => setCartOpen(true)} />
      <main className="wrap">
        <section className="hero">
          <div>
            <p className="eyebrow">TechTokri · gadgets delivered across Pakistan</p>
            <h1>Tell ShopBot what you need.<br /><span>It finds it, fills the cart and books the order.</span></h1>
            <form className="hero-ask" onSubmit={(e) => { e.preventDefault(); const t = e.target.ask.value.trim(); if (t) { setPrefill({ text: t, k: Date.now() }); e.target.reset(); } }}>
              <input name="ask" placeholder="e.g. a gift for my brother under Rs 3,000" />
              <button>Ask ShopBot</button>
            </form>
            <ul className="perks"><li>Free delivery over Rs 5,000</li><li>Cash on delivery</li><li>7-day returns</li></ul>
          </div>
          <div className="hero-card">
            <div className="hc-row me">Earbuds for the gym under 5k?</div>
            <div className="hc-row bot">Bassline Wireless Earbuds (AUD-101), Rs 4,499: IPX4 sweat-proof, 30h battery. Add to cart?</div>
            <div className="hc-row me">yes, deliver to Gulshan, Karachi</div>
            <div className="hc-row bot">Total Rs 4,749 incl. delivery. Shall I place it?</div>
          </div>
        </section>

        <section className="toolbar">
          <div className="pills">{CATS.map((c) => <button key={c} className={c === cat ? "on" : ""} onClick={() => setCat(c)}>{c}</button>)}</div>
          <input className="search" placeholder="Filter products…" value={q} onChange={(e) => setQ(e.target.value)} />
        </section>
        {err && <p className="muted">{err}</p>}
        <section className="grid">
          {shown.map((p) => (
            <article key={p.id} className="card">
              <div className="thumb">{p.image}</div>
              <div className="meta"><span className="cat">{p.category}</span><span className="sku">{p.id}</span></div>
              <h3>{p.name}</h3>
              <p className="desc">{p.description}</p>
              <div className="buy">
                <b>{pkr(p.price)}</b>
                {p.in_stock ? <span className="stock ok">{p.stock <= 10 ? `Only ${p.stock} left` : "In stock"}</span> : <span className="stock no">Out of stock</span>}
              </div>
              <div className="card-actions">
                <button disabled={!p.in_stock} onClick={() => add(p)}>Add to cart</button>
                <button className="ghost" onClick={() => setPrefill({ text: `Tell me about ${p.name} (${p.id}). Is it right for me?`, k: Date.now() })}>Ask</button>
              </div>
            </article>
          ))}
        </section>
      </main>
      <footer className="foot wrap">TechTokri demo store · ShopBot is an AI assistant and can make mistakes; orders are only placed after you confirm.</footer>

      <CartDrawer open={cartOpen} onClose={() => setCartOpen(false)} cart={cart} reload={loadCart} flash={flash} />
      <Chat onAction={() => loadCart()} prefill={prefill} open={chatOpen} setOpen={setChatOpen} />
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}

function CartDrawer({ open, onClose, cart, reload, flash }) {
  const [code, setCode] = useState("");
  const [addr, setAddr] = useState("");
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(null);

  async function remove(id) { await userFetch(`/me/cart/${id}`, { method: "DELETE" }); reload(code); }
  async function place() {
    const r = await userFetch("/me/checkout", { method: "POST", body: JSON.stringify({ shipping_address: addr, discount_code: code }) });
    if (r.error) { flash(r.error); setStep(0); return; }
    setDone(r); setStep(0); reload();
  }
  return (
    <div className={`drawer ${open ? "open" : ""}`} onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()}>
        <header><h2>Your cart</h2><button onClick={onClose}>✕</button></header>
        {done ? (
          <div className="done"><h3>Order placed 🎉</h3><p><b>{done.order_id}</b> · {pkr(done.total)} · Cash on Delivery</p><a href="/orders">Track it in My orders →</a><button className="ghost" onClick={() => setDone(null)}>Keep shopping</button></div>
        ) : cart.items.length === 0 ? <p className="muted">Empty. Add something, or ask ShopBot to do it for you.</p> : (
          <>
            {cart.items.map((i) => (
              <div className="line" key={i.product_id}>
                <div><b>{i.name}</b><div className="muted">{i.qty} × {pkr(i.unit_price)}</div></div>
                <div>{pkr(i.line_total)} <button className="x" onClick={() => remove(i.product_id)}>remove</button></div>
              </div>
            ))}
            <div className="row"><input placeholder="Discount code (WELCOME10)" value={code} onChange={(e) => setCode(e.target.value)} /><button className="ghost" onClick={() => reload(code)}>Apply</button></div>
            {cart.note && <p className="warn">{cart.note}</p>}
            <dl className="totals">
              <dt>Subtotal</dt><dd>{pkr(cart.subtotal)}</dd>
              {cart.discount > 0 && <><dt>Discount</dt><dd>−{pkr(cart.discount)}</dd></>}
              <dt>Delivery</dt><dd>{cart.shipping ? pkr(cart.shipping) : "Free"}</dd>
              <dt className="t">Total</dt><dd className="t">{pkr(cart.total)}</dd>
            </dl>
            <textarea placeholder="Delivery address with city" value={addr} onChange={(e) => setAddr(e.target.value)} rows={2} />
            {step === 0 ? (
              <button className="primary" disabled={addr.trim().length < 5} onClick={() => setStep(1)}>Checkout · Cash on Delivery</button>
            ) : (
              <div className="confirm"><p>Place this order for <b>{pkr(cart.total)}</b>?</p><button className="primary" onClick={place}>Yes, place order</button><button className="ghost" onClick={() => setStep(0)}>Back</button></div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
