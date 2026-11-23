"use client";

export const API = (process.env.NEXT_PUBLIC_AGENT_URL || "http://localhost:7860").replace(/\/$/, "");

function store() {
  try { return window.localStorage; } catch { return null; }
}

let inflight = null;
export function getSession(forceNew = false) {
  const ls = store();
  if (!forceNew && ls) {
    const s = ls.getItem("tt_session");
    if (s) return Promise.resolve(JSON.parse(s));
  }
  if (inflight && !forceNew) return inflight; // one session even if several components ask at once
  inflight = fetch(`${API}/session`, { method: "POST" })
    .then((r) => r.json())
    .then((s) => {
      ls && ls.setItem("tt_session", JSON.stringify(s));
      ls && ls.removeItem("tt_thread");
      return s;
    })
    .finally(() => setTimeout(() => { inflight = null; }, 0));
  return inflight;
}

export function getThread(forceNew = false) {
  const ls = store();
  let t = !forceNew && ls ? ls.getItem("tt_thread") : null;
  if (!t) {
    t = "t_" + Math.random().toString(36).slice(2, 10);
    ls && ls.setItem("tt_thread", t);
  }
  return t;
}

export async function userFetch(path, opts = {}) {
  const s = await getSession();
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-User-Token": s.token, ...(opts.headers || {}) },
  });
  if (r.status === 401) {
    await getSession(true);
    throw new Error("Session expired, please retry");
  }
  return r.json();
}

export async function adminFetch(path, token, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-Admin-Token": token, ...(opts.headers || {}) },
  });
  if (r.status === 401) throw new Error("unauthorized");
  return r.json();
}

export async function sendChat(user_id, thread_id, message) {
  const r = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id, thread_id, message }),
  });
  return r.json();
}

export const pkr = (n) => "Rs " + Number(n || 0).toLocaleString("en-PK");
