# Ringback

**[Demo video — add link here before submission]**

**A callback-first front door for university admin offices, built on CALL-E.** Students leave a query; CALL-E calls back and resolves it.

Ringback turns "please hold" into "we'll call you right back." A student fills in a fifteen-second web form with their question and hangs up on nothing, because there was never a call to hang up on. Ringback classifies the query, pulls their record (or the right knowledge-base article, if they're not a registered student), and dispatches a CALL-E agent to call them back and resolve it — or routes it to the one named person who can, with the full context already attached.

Built for [CALL-E: Your Code Is Calling](https://call-e.devpost.com). Reference deployment: Namibia University of Science and Technology (NUST), Windhoek.

## The problem, specifically

| Inconvenience | How Ringback answers it |
|---|---|
| **Long hold times** | There is no hold. The student submits a form in 15 seconds. CALL-E calls back, usually within two minutes. |
| **Repetitive storytelling** | The query is captured once (`Case.original_query`, never overwritten) and travels into the call task, the structured result, and the escalation ticket. Nobody re-explains anything to anybody. |
| **Dropped calls** | The case lives in a database, not a queue. A failed, unanswered, or voicemailed call retries automatically, up to 3 attempts, before it's flagged for a manual callback. |

Secondary claim: **conflicting information** — every answer is derived from the student's record or a knowledge-base file, never from an agent's memory, so two people asking the same question get the same answer.

Explicitly not claimed: beating a dead-end IVR menu. Ringback removes the IVR rather than out-performing it. What every unresolved query gets instead is a named office, a named contact, and a one-line reason — never a loop.

## How it works

```
Web intake form (student number optional)
    ↓
Case created in SQLite — original_query stored verbatim
    ↓
Classifier (keyword-based) → proof_of_registration | subject_cancellation | other
    ↓
Mock SIS lookup (if a student number was given) or knowledge-base file (if not)
    ↓
Dispatcher builds a task string + a result schema, calls CalleClient.dispatch()
    ↓
CALL-E plans, calls, adapts, returns a structured result
    ↓
Resolved ───────────────────────→ case closed, transcript + result stored
   │
   └─ Unresolved / no answer ───→ Router picks a named office+contact, or the
                                   dispatcher retries (max 3 attempts) before
                                   marking the case failed for a manual callback
```

The dashboard polls `GET /api/cases` every 2 seconds — no websockets — so a judge watching the demo sees a case's status change on its own.

## Who's the agent here

Ringback itself is a deterministic pipeline: classify → look up → fill a template → dispatch → poll → route. Every branch above is code that runs the same way on every call — there's no model in Ringback deciding what to do next.

**CALL-E is the agent.** It plans the call, adapts in real time to whatever the student actually says, handles interruptions and voicemail, and returns the structured result Ringback acts on. Ringback orchestrates an agent; it is not one itself, and that's a deliberate choice, not a shortfall — a pipeline that behaves identically on take four is worth more than architectural cleverness when you're filming a three-minute demo. See "Future work" below for what a genuinely agentic version of Ringback would look like, and why it isn't built yet.

## Scope: three intents, on purpose

1. **Proof of registration** — resolvable. Confirm identity, check status, explain the document is ready or blocked by a fee balance.
2. **Subject cancellation** — resolvable with a deadline check. Confirm the subject, whether the drop window is open, and the fee implication.
3. **Anything else** — deliberately unresolvable by design. CALL-E gathers detail from the caller, working from the knowledge-base article Ringback selected, then the case routes to a named office.

The third one is the feature, not a fallback: "couldn't solve it, but here's exactly which office, which person, and the full context already attached" is the non-obvious part of this project.

## How CALL-E is used

`app/calle_client.py` is the **only** file in this codebase that talks to CALL-E. It wraps the Developer API directly:

- `POST /v1/calls` — dispatches a call with a `task` string and a `recipient_result_schema` built per-intent (see `app/schemas.py`)
- `GET /v1/calls/{call_id}` — polled by `app/dispatcher.py` to read `status`, `structured_result`, `transcript`, and `completion_confidence`

The dispatcher follows the documented polling rhythm against a live account (wait ~60s, then poll every 5–10s until terminal) and never re-fires a call with a stale identifier — a retry always dispatches a brand-new call and stores the new run id.

**Current status:** `CALLE_API_KEY` has not been configured yet (Day 1 of the build plan — see below), so `calle_client.py` currently falls back to a local mock transport with deterministic per-phone outcomes, purely so the rest of the pipeline (classifier → dispatcher → router → dashboard) can be built and demoed before the account is wired in. Setting `CALLE_API_KEY` in `.env` switches to real calls with no other code changes. The MCP transport (`plan_call` / `run_call` / `get_call_run`) described in the CALL-E docs is the fallback if no API key is issued, and would live in this same file — it is not implemented yet.

## Known limitations

- **Namibia is an International line.** Calls to `+264` numbers are placed from CALL-E's international numbers, which the CALL-E docs describe as primarily for testing. Students will see a foreign number ring rather than a local one. Fix path: request a local NA line from the CALL-E team for production use.
- **The knowledge base and classifier are intentionally simple.** Keyword matching over three intents costs nothing and is transparent to debug; it would be replaced by a real NLU step for a production deployment with more intents.
- **Single process, SQLite, in-process polling.** Fine for a hackathon dashboard with a handful of concurrent calls; would need a real task queue (Celery, etc.) and a proper database at any real scale.

## How this generalises

Nothing about NUST is hardcoded in `app/`. A university is a `tenants/<id>.json` file (identity, tone, office directory) plus a `kb/<id>/*.md` folder. `tenants/unam.json` exists specifically to prove this — a second university is a JSON file and a folder of markdown, not a code change.

## Repo structure

```
ringback/
├── CLAUDE.md              # standing rules for Claude Code sessions on this repo
├── app/
│   ├── main.py            # FastAPI routes, serves the built frontend
│   ├── calle_client.py    # the only file that talks to CALL-E (real + mock transports)
│   ├── dispatcher.py       # task templates, dispatch, poll loop, retries
│   ├── schemas.py          # result schemas per intent
│   ├── classifier.py       # query → intent
│   ├── router.py           # unresolved → named office
│   ├── directory.py        # StudentDirectory interface + JSONDirectory
│   ├── retrieval/          # pre-call retrieval: chunker, TF-IDF retriever, briefing builder
│   ├── tenants.py          # tenant config loader
│   ├── models.py           # SQLModel Case model + SQLite engine
│   └── data/students.json  # mock student information system, ~8 students
├── tenants/
│   ├── nust.json           # configured
│   └── unam.json           # exists to prove multi-tenancy
├── kb/nust/*.md             # six knowledge-base articles, with topic/office frontmatter
├── scripts/                 # build_index.py, tune_threshold.py
├── web/                     # React + Vite dashboard and intake flow
│   └── src/styles/tokens.css
└── requirements.txt
```

## Running locally

Backend:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (separate terminal, dev mode with hot reload and API proxy):

```bash
cd web
npm install
npm run dev
```

Visit the Vite dev URL for the intake form, and `/dashboard` for the staff view. Submitting the intake form with one of the phone numbers in `app/data/students.json` (e.g. `+264 81 123 4567`) will walk through a deterministic mock call outcome so the dashboard has something to show before a live CALL-E key exists.

For a single-process production-style run, build the frontend and let FastAPI serve it:

```bash
cd web && npm run build && cd ..
uvicorn app.main:app --port 8000
```

## Day 1 checklist (build plan)

- [ ] Place one real call to your own `+264` number by hand via the CALL-E CLI/MCP tools, before trusting the app end to end.
- [ ] Check the CALL-E dashboard for an API key; set `CALLE_API_KEY` in `.env` once issued.
- [ ] Confirm `plan_call` / `run_call` / `get_call_run` are available via `calle mcp tools` as a fallback path.

## Future work

- **Agentic escalation loop — the biggest idea here, deliberately deferred.** When a case can't be resolved on the first call, dispatch a *second* CALL-E call to the relevant office, ask the question on the student's behalf, then call the student back with the answer. Plan → execute → observe → act again, using CALL-E twice per case. This is the one change that would make Ringback itself agentic rather than a deterministic orchestrator, and it's a direct answer to "no transfers, no re-explaining" — the system does the transfer instead of a human. Not built before day 14 on purpose: it doubles the call budget per case and adds a second failure surface, and the core pipeline needs to be proven end to end first against a live account. Worth revisiting as the demo video's closing beat if there's schedule margin after day 8.
- **Model-backed classifier and router.** Swap the keyword classifier for a single Claude call returning `{intent, confidence, entities}` — cheap, and handles phrasing keywords miss ("won't let me download it", "can I still drop this subject"). Similarly, let a model pick the routing office and write the escalation reason from the structured result, instead of the static `ROUTING_TABLE` dict. Neither changes the architecture; both make the judgment sharper. Worth doing once the pipeline is verified against real CALL-E output, not before.
- **USSD intake** — a short code for students on feature phones with no data.
- **Live SIS connectors** — `PostgresDirectory` / `RESTDirectory` implementing the same `StudentDirectory` interface as the mock JSON directory, against a real student information system.
- **Tenant self-service** — signup, KB upload, and office-directory configuration without editing JSON by hand.
- **A local NA calling line**, so students see a Namibian number rather than an international one.

## Submission checklist

- [ ] PR to `https://github.com/CALLE-AI/awesome-phone-call-agents`, correct Contribution Area
- [ ] Demo video public on YouTube/Vimeo, under 3 minutes, no copyrighted music
- [ ] PR URL on the Devpost submission form
- [ ] Text description of features and functionality
- [ ] CALL-E account email
- [ ] Feedback survey submitted (separate prize track)
