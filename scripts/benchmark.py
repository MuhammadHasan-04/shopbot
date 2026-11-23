"""Run tests.json against a deployed agent and write BENCHMARK.md (+ update README table).

usage:  python scripts/benchmark.py https://shopbot-agent.onrender.com [--repeat 2] [--no-readme]
Only uses the public /chat API, so it measures exactly what the graders see.
"""
import argparse
import json
import pathlib
import statistics
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRICE_IN, PRICE_OUT = 1.0, 5.0  # USD per million tokens, Haiku-class estimate: edit if your pricing differs


def post(base, body, timeout=90):
    req = urllib.request.Request(base.rstrip("/") + "/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    for attempt in (1, 2):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read()), time.time() - t0
        except urllib.error.HTTPError as e:     # 502/503 = Render deploying or waking up: wait and retry once
            if e.code in (502, 503) and attempt == 1:
                print("   (got", e.code, "- server restarting, retrying in 20 s)")
                time.sleep(20)
                continue
            raise


def check(exp: dict, res: dict) -> list[str]:
    reply = (res.get("reply") or "").lower()
    names = [t.get("name") for t in res.get("tool_calls", [])]
    fails = []
    for s in exp.get("contains", []):
        if s.lower() not in reply:
            fails.append(f"missing '{s}'")
    for s in exp.get("not_contains", []):
        if s.lower() in reply:
            fails.append(f"should not contain '{s}'")
    if exp.get("any_of") and not any(s.lower() in reply for s in exp["any_of"]):
        fails.append(f"none of {exp['any_of']}")
    for t in exp.get("tools_include", []):
        if t not in names:
            fails.append(f"tool {t} not called")
    if exp.get("tools_include_any") and not any(t in names for t in exp["tools_include_any"]):
        fails.append(f"none of tools {exp['tools_include_any']}")
    if "tools_count_max" in exp and len(names) > exp["tools_count_max"]:
        fails.append(f"too many tool calls {names}")
    for tool, args in exp.get("args_include", {}).items():
        calls = [t.get("args", {}) for t in res.get("tool_calls", []) if t.get("name") == tool]
        if not any(all(str(c.get(k, "")).upper() == str(v).upper() for k, v in args.items()) for c in calls):
            fails.append(f"{tool} args {args} not seen")
    if not isinstance(res.get("tokens"), dict) or "in" not in res["tokens"]:
        fails.append("bad response format")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--no-readme", action="store_true")
    a = ap.parse_args()
    data = json.loads((ROOT / "tests.json").read_text(encoding="utf-8"))
    tests = data["tests"] + data.get("attack_tests", [])

    # health
    with urllib.request.urlopen(a.base.rstrip("/") + "/health", timeout=60) as r:
        print("health:", r.read().decode())

    rows, lat_all, tin_all, tout_all, turns_all = [], [], [], [], 0
    for rep in range(a.repeat):
        run = uuid.uuid4().hex[:6]
        for t in tests:
            fails, lat, tin, tout, tools = [], [], 0, 0, []
            for turn in t["turns"]:
                body = {k: turn[k].replace("{run}", run) for k in ("user_id", "thread_id", "message")}
                try:
                    res, dt = post(a.base, body)
                except Exception as e:
                    res, dt = {"reply": "", "tool_calls": [], "tokens": {"in": 0, "out": 0}}, 0
                    fails.append(f"HTTP error {e}")
                lat.append(dt)
                tin += res["tokens"].get("in", 0)
                tout += res["tokens"].get("out", 0)
                tools += [x["name"] for x in res.get("tool_calls", [])]
                fails += [f"turn {t['turns'].index(turn) + 1}: {f}" for f in check(turn.get("expect", {}), res)]
                print(f"[{t['id']}] {body['message'][:50]!r} -> {res.get('reply', '')[:110]!r}")
            lat_all += lat
            tin_all.append(tin)
            tout_all.append(tout)
            turns_all += len(t["turns"])
            rows.append({"id": t["id"], "title": t["title"], "category": t["category"], "pass": not fails,
                         "fails": fails, "latency": statistics.mean(lat), "tin": tin, "tout": tout,
                         "tools": ", ".join(dict.fromkeys(tools)) or "-", "rep": rep + 1})
            print("   ->", "PASS" if not fails else f"FAIL {fails}")

    passed = sum(r["pass"] for r in rows)
    p50 = statistics.median(lat_all)
    p95 = sorted(lat_all)[max(0, int(len(lat_all) * 0.95) - 1)]
    cost = (sum(tin_all) * PRICE_IN + sum(tout_all) * PRICE_OUT) / 1e6
    lines = [
        f"Run on {time.strftime('%Y-%m-%d %H:%M')} against `{a.base}` (model claude-haiku-5-5; 10 own tests + 5 attack tests), {a.repeat} run(s).", "",
        "| Test | Category | Result | Avg latency (s) | Tokens in / out | Tools called |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} {r['title']} | {r['category']} | {'✅ pass' if r['pass'] else '❌ ' + '; '.join(r['fails'])[:80]} "
                     f"| {r['latency']:.2f} | {r['tin']} / {r['tout']} | {r['tools']} |")
    lines += ["", "| Metric | Value |", "|---|---|",
              f"| Pass rate | {passed}/{len(rows)} ({100 * passed / len(rows):.0f}%) |",
              f"| Latency p50 / p95 per turn | {p50:.2f}s / {p95:.2f}s |",
              f"| Avg tokens per turn (in / out) | {sum(tin_all) / turns_all:.0f} / {sum(tout_all) / turns_all:.0f} |",
              f"| Est. cost for this benchmark | ${cost:.4f} (≈ ${cost / turns_all * 1000:.2f} per 1,000 turns) |",
              f"| Attack tests passed | {sum(r['pass'] for r in rows if r['id'].startswith('A'))}/{sum(1 for r in rows if r['id'].startswith('A'))} (answered by the guard node with 0 tokens) |"]
    table = "\n".join(lines)
    (ROOT / "BENCHMARK.md").write_text(encoding="utf-8", data="# Benchmark\n\n" + table + "\n")
    print("\n" + table)
    if not a.no_readme:
        readme = ROOT / "README.md"
        txt = readme.read_text(encoding="utf-8")
        s, e = "<!-- BENCHMARK:START -->", "<!-- BENCHMARK:END -->"
        if s in txt and e in txt:
            txt = txt.split(s)[0] + s + "\n" + table + "\n" + e + txt.split(e)[1]
            readme.write_text(txt, encoding="utf-8")
            print("README.md benchmark table updated")


if __name__ == "__main__":
    main()
