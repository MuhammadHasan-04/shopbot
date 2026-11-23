# Deploy guide: GitHub → Render (API + PostgreSQL) → Vercel (about 30 minutes)

You need free accounts on **GitHub**, **Render** and **Vercel**. Sign in to Render and Vercel with GitHub.
The database is a **PostgreSQL** database that Render creates for you from `render.yaml`. No separate database website is needed.

## 0. Check the key is safe, then push to GitHub
In the project folder (`Workshop-main\Workshop-main`):
```bat
git init
git add .
git status
```
**Check the list:** `.env` must NOT appear (it's in `.gitignore`); `.env.example` should. If `.env` shows up, stop and run `git rm --cached .env`.
```bat
git commit -m "ShopBot: LangGraph sales agent, API, website"
```
Create an **empty public** repo on github.com (e.g. `shopbot`), then:
```bat
git remote add origin https://github.com/YOUR-USER/shopbot.git
git branch -M main
git push -u origin main
```

## 1. Render: PostgreSQL + agent API in one go
1. https://dashboard.render.com → **New + → Blueprint** → pick your repo.
2. Render reads `render.yaml` and shows **two** things to create:
   - `shopbot-db`: a free **PostgreSQL** database
   - `shopbot-agent`: the web service, with `DATABASE_URL` already wired to that database
3. It asks for 2 values:
   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your group key |
   | `ADMIN_TOKEN` | a password you choose for the seller dashboard |
4. **Apply**. The database is ready in about 1 minute and the API build takes about 3–5 minutes. Tables are created automatically on first start.
5. Test it, using your service URL from the top of the `shopbot-agent` page:
   - Browser: `https://shopbot-agent.onrender.com/health` → `ok`
   - Browser: `https://shopbot-agent.onrender.com/docs` → try `POST /chat` with
     `{"user_id":"test1","thread_id":"t1","message":"Show me earbuds under 5000"}`
   - In the Render **Logs** you should see `Memory in Postgres (checkpointer + store)`.

> Render's free PostgreSQL expires **30 days** after creation. That's fine for the evaluation (Tue 24 to Wed 25 Nov). To keep it longer, upgrade the database or move it later.

**Manual alternative** (if the Blueprint fails):
1. **New + → PostgreSQL**: name `shopbot-db`, region Singapore, plan Free → Create. Open it and copy the **Internal Database URL**.
2. **New + → Web Service** → your repo → Runtime Python 3 → Build `pip install -r requirements-api.txt` → Start `uvicorn app.api:app --host 0.0.0.0 --port $PORT` → Free plan, **same region**.
3. Environment variables: `DATABASE_URL` = the Internal Database URL, plus `ANTHROPIC_API_KEY`, `ADMIN_TOKEN`, `SESSION_SECRET` (any long text) and `PYTHON_VERSION=3.12.8`. Health check path `/health`.

**Using a different Postgres** (Supabase, your own server, etc.)? Put its connection string in `DATABASE_URL`; nothing else changes. Notes:
- On **Supabase**, use the **Session pooler** string (`...pooler.supabase.com:5432/postgres`), not the direct one, because Render can't reach Supabase's direct IPv6 address.
- Hosted databases outside Render usually need `?sslmode=require` at the end of the URL.
- The brief names "Supabase or Neon"; if your instructor insists on those, use one of them the same way.

## 2. Vercel (website)
1. https://vercel.com/new → import the same repo.
2. **Root Directory → `web`** (click Edit). Framework: Next.js.
3. Environment variable: `NEXT_PUBLIC_AGENT_URL` = your Render API URL (no trailing `/`).
4. **Deploy** → `https://your-project.vercel.app`. The seller dashboard is at `/admin` (password = `ADMIN_TOKEN`).

## 3. ⚠️ Keep Render awake until Wed 25 Nov night
A free Render web service sleeps after 15 minutes idle, and the first request after that takes about 50 s, which can fail the graders' tests.
- https://cron-job.org → new job → URL `https://<your-render-url>/health` → **every 10 minutes**.
- Tuesday morning: open `/health` yourself and check you get `ok` instantly.

## 4. Benchmark, GIF and README (on your laptop)
```bat
python scripts\benchmark.py https://shopbot-agent.onrender.com
```
This re-runs the 15 tests against the live API and rewrites the README table (about 8 cents of your $2).
`docs/demo.gif` is already recorded. To re-record from the live site: `pip install playwright pillow`, `playwright install chromium`, then `python scripts\make_demo_gif.py https://your-project.vercel.app YOUR_ADMIN_TOKEN`.

Put the 4 links in the table at the top of `README.md`, then:
```bat
git add . && git commit -m "links + benchmark" && git push
```
Render and Vercel redeploy automatically.

## Local testing with your own Postgres (optional)
Install PostgreSQL, create a database, and put its URL in `.env`:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/shopbot
```
Then `uvicorn app.api:app --reload --port 8000`. If `DATABASE_URL` is empty, memory falls back to RAM (lost on restart: local testing only).

## Don't
- Don't commit `.env` or paste the key anywhere public. A leaked key gets disabled.
- Don't change code or keys during evaluation (Tue 24 Nov).
- Don't use `claude-sonnet-5-5` unless told; it costs much more.
