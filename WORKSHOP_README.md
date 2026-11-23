# Care Chatbot: LangChain v1 + LangGraph workshop

A care assistant for patients with long-term conditions, built one framework primitive at a time.
**All data in `data/` is synthetic.** This is a teaching demo, not a medical device.

## Setup

Needs **Python 3.11+**.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # everything: notebooks, backend, UI, tests
cp .env.example .env               # then fill in your keys
```

| Key in `.env` | Needed for | Get one at |
|---|---|---|
| `ANTHROPIC_API_KEY` | The model (`claude-haiku-5-5`); embeddings run locally, no key needed | your group's workshop email |
| `LANGSMITH_API_KEY` | Traces and Studio | smith.langchain.com |
| `TAVILY_API_KEY` | Only the web search cell in 00 | tavily.com (free tier) |

Open the notebooks:

```bash
jupyter lab                        # then open notebooks/00_intro.ipynb
```

Run the app (two terminals, both with the venv activated):

```bash
langgraph dev                      # terminal 1: the agent server on :2024
streamlit run ui/streamlit_app.py  # terminal 2: the UI on :8501
```

## Start at `notebooks/00_intro.ipynb`

| # | Notebook | The limitation it fixes | New framework pieces |
|---|---|---|---|
| 00 | `00_intro` | From a bare LLM to an agent (university example) | `init_chat_model`, checkpointer, `@tool`, Tavily web search, RAG, `HumanInTheLoopMiddleware` |
| 01 | `01_agent` | An LLM can only talk | `create_agent`, `@tool`, `context_schema`, `ToolRuntime` |
| 02 | `02_middleware` | Same tools and prompt for everyone; nowhere for rules that must always run | the hooks (`@before_model`, `@after_model`, `@wrap_tool_call`, `@wrap_model_call`, `@dynamic_prompt`), `Command(update=...)`, `state_schema`, prebuilt middleware incl. `PIIMiddleware` |
| 03 | `03_safety` | Some decisions are too important for the model | prompt vs. guard exercise, `dose_guard` (`@before_model`), `interrupt()` in a tool |
| 04 | `04_rag` | Can't read our documents | vector store + retrieval tool, context filter, the full middleware stack |
| 05 | `05_multi_agent` | One agent with too many tools | agents as tools, `response_format`, `StateGraph` |
| 06 | `06_long_term_memory` | New chat = blank slate | `Store`, `runtime.store`, semantic search |

Each notebook imports what earlier notebooks built from `notebooks/common.py`, and writes only its new idea out in full.

## The backend (`app/`)

The same features as one deployable agent, served by the LangGraph server (no FastAPI needed):

```bash
langgraph dev             # API on http://localhost:2024 + LangSmith Studio
```

- `agent`: the full single agent (`app/agent.py`)
- `care_team`: the multi-agent graph (`app/multi_agent.py`)

Studio lets you set the context (try `{"role": "doctor"}`), approve interrupts and inspect state.

## The UI (`ui/`)

A Streamlit front end that talks to the server above. Keep `langgraph dev` running, then:

```bash
streamlit run ui/streamlit_app.py     # http://localhost:8501
```

- **Patient side (Sara, Omar):** chat, log readings, ask about leaflets, book appointments.
- **Doctor side (Dr. Lee):** a **nurse inbox** of paused patient chats. Your note resumes the patient's run.
  It also has a clinical assistant with doctor-only tools, and a patient list.
- **🎓 Learning mode:** shows every tool call, the middleware hooks, the model used, the runtime context,
  the visible tools, the thread state and long-term memory, next to the chat.

Demo: as Sara, send *"My BP is 190/120"* → switch to Dr. Lee → *Send note & continue* → back to Sara.

`ui/backend.py` is the whole frontend–backend contract: a handful of LangGraph SDK calls.
`ui/steps.py` turns the streamed updates into the learning-mode timeline.

```bash
pytest                          # fast tests of our CUSTOM rules (no API calls)
```

## What is custom (and why)

Everything else is a LangChain or LangGraph class. Look for `# CUSTOM:` in the code.

| Custom piece | Why the framework can't own it | Hook it plugs into |
|---|---|---|
| BP and glucose thresholds | Clinical policy, per patient | `interrupt()` inside `log_reading` |
| Dose-question detection | Our safety policy | `@before_model` |
| MRN and phone regexes | Our identifier formats | `PIIMiddleware(detector=...)` |
| Audit record fields | Our compliance needs | `@wrap_tool_call` |
| Who may use which tool | Our access policy | `@wrap_model_call` |
| Emergency triage words | Our triage policy | a `StateGraph` node |

Not covered by any library: BAAs, encryption at rest, hosting decisions and breach notification.
