"use client";
import { useEffect, useRef, useState } from "react";
import { getSession, getThread, sendChat } from "@/lib/api";

function md(text) {
  const esc = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = esc.split("\n");
  let html = "", inList = false;
  for (const raw of lines) {
    const l = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");
    const m = l.match(/^\s*(?:[-•*]|\d+\.)\s+(.*)/);
    if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${m[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    html += l.trim() ? `<p>${l.replace(/^#+\s*/, "")}</p>` : "";
  }
  return html + (inList ? "</ul>" : "");
}

const TOOL_LABEL = {
  search_products: "Searched catalogue", get_product: "Checked product", store_policy: "Read store policy",
  add_to_cart: "Added to cart", remove_from_cart: "Updated cart", view_cart: "Checked cart",
  place_order: "Order step", my_orders: "Looked up orders", cancel_order: "Cancel step",
  remember_preference: "Saved to memory", recall_preferences: "Checked memory", sales_report: "Sales report",
};

const STARTERS = ["Wireless earbuds under Rs 5,000", "I use an iPhone 15, need a fast charger", "What's your return policy?", "Track my order"];

export default function Chat({ onAction, prefill, open, setOpen }) {
  const [session, setSession] = useState(null);
  const [thread, setThread] = useState("");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    getSession().then((s) => {
      setSession(s);
      const t = getThread();
      setThread(t);
      try { setMsgs(JSON.parse(localStorage.getItem("tt_msgs_" + t) || "[]")); } catch {}
    }).catch(() => setMsgs([{ role: "bot", text: "Can't reach the shop assistant right now." }]));
  }, []);

  useEffect(() => { if (prefill) { setOpen(true); send(prefill.text); } }, [prefill]); // eslint-disable-line
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);

  function save(t, m) { try { localStorage.setItem("tt_msgs_" + t, JSON.stringify(m.slice(-60))); } catch {} }

  async function send(text) {
    text = (text ?? input).trim();
    if (!text || busy) return;
    const s = session || (await getSession());
    const t = thread || getThread();
    const next = [...msgs, { role: "me", text }];
    setMsgs(next); setInput(""); setBusy(true);
    try {
      const r = await sendChat(s.user_id, t, text);
      const done = [...next, { role: "bot", text: r.reply, tools: (r.tool_calls || []).map((c) => c.name), tokens: r.tokens }];
      setMsgs(done); save(t, done);
      onAction?.();   // the agent may have changed the cart, an order or memory
    } catch {
      setMsgs([...next, { role: "bot", text: "Network problem, please try again." }]);
    }
    setBusy(false);
  }

  function newChat() { const t = getThread(true); setThread(t); setMsgs([]); }
  async function newCustomer() {
    const s = await getSession(true); setSession(s);
    const t = getThread(true); setThread(t); setMsgs([]); onAction?.();
  }

  return (
    <>
      <button className={`chat-fab ${open ? "hide" : ""}`} onClick={() => setOpen(true)}>
        <span className="dot" /> Ask ShopBot
      </button>
      <aside className={`chat ${open ? "open" : ""}`}>
        <header>
          <div>
            <b>ShopBot</b> <span className="muted">sales assistant</span>
            <div className="ids">customer <code>{session?.user_id || "…"}</code> · chat <code>{thread}</code></div>
          </div>
          <div className="chat-actions">
            <button onClick={newChat} title="Start a new conversation (memory of you is kept)">New chat</button>
            <button onClick={() => setOpen(false)} aria-label="close">✕</button>
          </div>
        </header>
        <div className="chat-body">
          {msgs.length === 0 && (
            <div className="hello">
              <p>Assalam o Alaikum! I can find the right gadget, check stock, fill your cart and place the order.</p>
              <div className="chips">{STARTERS.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              {m.tools?.length > 0 && (
                <div className="tools">{[...new Set(m.tools)].map((t) => <span key={t}>⚙ {TOOL_LABEL[t] || t}</span>)}</div>
              )}
              <div className="bubble" dangerouslySetInnerHTML={{ __html: m.role === "bot" ? md(m.text) : md(m.text) }} />
            </div>
          ))}
          {busy && <div className="msg bot"><div className="bubble typing"><i /><i /><i /></div></div>}
          <div ref={endRef} />
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about products, orders, delivery…" maxLength={1000} />
          <button disabled={busy || !input.trim()}>Send</button>
        </form>
        <div className="chat-foot"><button className="link" onClick={newCustomer}>Switch to a new customer profile</button></div>
      </aside>
    </>
  );
}
