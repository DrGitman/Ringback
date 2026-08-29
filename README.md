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
3. **Anything else** — deliberately unresolvable by design, and always routes to a named office.

Retrieval runs on all three, but frames differently. For (1) and (2), the student's record is the answer — retrieval only adds background for anything the record doesn't cover (e.g. a proof-of-registration caller who also asks *where* the Cashier's Office is), and the record always wins if the two disagree. For (3), there's no record to fall back on, so the retrieved material *is* the answer; if nothing clears the relevance threshold, CALL-E is told plainly to say it doesn't know rather than guess. Either way, retrieval happens once, before dispatch — CALL-E has no hook to query anything mid-call.

The third intent is the feature, not a fallback: "couldn't solve it, but here's exactly which office, which person, and the full context already attached" is the non-obvious part of this project.

## How CALL-E is used

`app/calle_client.py` is the **only** file in this codebase that talks to CALL-E. It wraps the Developer API directly:

- `POST /v1/calls` — dispatches a call with a `task` string and a `recipient_result_schema` built per-intent (see `app/schemas.py`)
- `GET /v1/calls/{call_id}` — polled by `app/dispatcher.py` to read `status`, `structured_result`, `transcript`, and `completion_confidence`

The dispatcher follows the documented polling rhythm against a live account (wait ~60s, then poll every 5–10s until terminal) and never re-fires a call with a stale identifier — a retry always dispatches a brand-new call and stores the new run id.

**Current status:** `CALLE_API_KEY` has not been configured yet (Day 1 of the build plan — see below), so `calle_client.py` currently falls back to a local mock transport with deterministic per-phone outcomes, purely so the rest of the pipeline (classifier → dispatcher → router → dashboard) can be built and demoed before the account is wired in. `parse_call_response()` is written against a real `get_call_run` payload rather than the docs' shorthand example (uppercase/spaced statuses, `result.extracted`, `result.outcome.*`, string transcript) — see `tests/test_parse_call_response.py` and `tests/replay_fixture.py`. Setting `CALLE_API_KEY` in `.env` switches to real calls with no other code changes. The MCP transport (`plan_call` / `run_call` / `get_call_run`) is the fallback if no API key is issued, and would live in this same file — it is not implemented yet.

## Known limitations

- **Namibia is an International line.** Calls to `+264` numbers are placed from CALL-E's international numbers, which the CALL-E docs describe as primarily for testing. Students will see a foreign number ring rather than a local one. Fix path: request a local NA line from the CALL-E team for production use.
- **The classifier is intentionally simple.** Keyword matching over three intents costs nothing and is transparent to debug; it would be replaced by a real NLU step for a production deployment with more intents.
- **The relevance threshold is doing its job, and TF-IDF is the reason it sometimes has to.** "What are your office hours" retrieves `office-hours.md` at 0.215 (well above the 0.09 threshold). "Are you open on saturdays and can I come after 5pm" — the same underlying question, phrased differently — scores 0.071 and gets **no reference material at all**, so the agent is told to say it doesn't know and have the right office follow up, rather than answer off a weak match. On a phone call, where nobody sees a citation and nobody can scroll back, refusing to guess is the correct behavior, not a bug — a confidently wrong answer read aloud is worse than an honest "I'll have someone follow up." The cost of that safety property is real, though: TF-IDF is lexical, so it's paraphrase-blind, and that's what's driving the miss above. Embeddings would close this specific gap (`EmbeddingRetriever` is a documented, not-yet-built swap behind the same `Retriever` protocol — see `docs/retrieval-spec.md` §2 for why TF-IDF was chosen first). Re-tune with `scripts/tune_threshold.py` after any KB change.
- **Single process, SQLite, in-process polling.** Fine for a hackathon dashboard with a handful of concurrent calls; would need a real task queue (Celery, etc.) and a proper database at any real scale.

## How this generalises

Nothing about NUST is hardcoded in `app/`. A university is a `tenants/<id>.json` file (identity, tone, office directory) plus a `kb/<id>/*.md` folder — `get_retriever()` compares file mtimes against the saved index and rebuilds automatically the next time it's called if any `.md` file changed, so editing the KB is enough on its own. `python scripts/build_index.py <tenant>` still exists to rebuild eagerly (e.g. right before `tune_threshold.py`, or in CI) rather than waiting for the next call. `tenants/unam.json` exists specifically to prove this — a second university is a JSON file and a folder of markdown, not a code change.

### Connecting your own data

Three different shapes, at three different levels of "actually built":

- **Documents** (prospectus, handbooks, fee schedules) — a folder to drop files into. This is how `kb/nust/` already works; the retrieval index rebuilds itself automatically once a `.md` file's mtime is newer than the saved index (`scripts/build_index.py` remains for an eager, on-demand rebuild). A `scripts/ingest.py` that chunks PDFs and writes the frontmatter automatically would turn this into a genuine one-command onboarding path, but isn't built.
- **Student records** — the `StudentDirectory` protocol in `app/directory.py`, currently backed by `JSONDirectory` (the mock SIS). `PostgresDirectory` / `RESTDirectory` against a real system are documented future implementations behind the same interface, not built.
- **Live systems** (Moodle, ITS) — would need to be a sync job, not a live query, since a phone call can't block on a slow ITS instance. Not built, not started.

A signup-and-upload UI for all of this is two to three weeks of auth, tenant isolation and credential storage — invisible in a three-minute video, and it competes for the same days as the escalation loop below. `tenants/` plus this documented interface makes the same claim honestly, today.

## Repo structure

```
ringback/
├── CLAUDE.md              # standing rules for Claude Code sessions on this repo
├── render.yaml            # Render backend service config
├── netlify.toml           # Netlify frontend build config
├── app/
│   ├── main.py            # FastAPI routes, CORS, /health, /status
│   ├── calle_client.py    # the only file that talks to CALL-E (real + mock transports)
│   ├── dispatcher.py       # task templates, dispatch, poll loop, retries, resume_case()
│   ├── prepare.py          # the reasoning step: ModelPreparer (Gemini) + DeterministicPreparer
│   ├── schemas.py          # result schemas per intent, including the channel enum
│   ├── classifier.py       # query → intent (DeterministicPreparer's fallback path)
│   ├── router.py           # unresolved → named office
│   ├── directory.py        # StudentDirectory interface + JSONDirectory + SqlDirectory
│   ├── models_student.py   # Student/Application/Registration/SubjectEnrolment/FeeLine/AgeAnalysis/Bursary tables
│   ├── retrieval/          # pre-call retrieval: chunker (.md + PDF), TF-IDF retriever, briefing builder
│   ├── tenants.py          # tenant config loader
│   ├── models.py           # SQLModel Case model + shared DB engine (DATABASE_URL or local SQLite)
│   └── data/students.json  # superseded by scripts/seed_students.py; kept for JSONDirectory reference
├── tenants/
│   ├── nust.json           # configured
│   └── unam.json           # exists to prove multi-tenancy
├── kb/nust/*.md             # curated knowledge-base articles, with topic/office frontmatter
├── scripts/                 # build_index.py, tune_threshold.py, seed_students.py
├── web/
│   ├── src/api.js          # the only file that knows the backend's URL
│   ├── src/styles/tokens.css
│   ├── public/_redirects   # Netlify SPA routing
│   └── .env.example        # VITE_API_URL
└── requirements.txt
```

## Running locally

Backend:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python scripts/seed_students.py --target sqlite   # once, or after resetting ringback.db
uvicorn app.main:app --reload --port 8000
```

Frontend (separate terminal, dev mode with hot reload and API proxy):

```bash
cd web
npm install
npm run dev
```

Visit the Vite dev URL for the intake form, and `/dashboard` for the staff view. The student directory (`app/directory.py`'s `SqlDirectory`) reads from real database tables (`app/models_student.py`) seeded by `scripts/seed_students.py` — student `220100002` has an outstanding balance and is a good one to test the proof-of-registration path with, before a live CALL-E key exists (the mock transport uses different placeholder numbers - see `_MockTransport._SCENARIOS` in `app/calle_client.py`).

## Deployment

Split across three free tiers: **Netlify** (frontend), **Render** (backend), **Neon** (Postgres). FastAPI no longer serves the built frontend itself — `ALLOWED_ORIGINS` and `VITE_API_URL` are what connect the two instead of one process doing both.

**What's already built, in this repo:** `render.yaml`, `netlify.toml`, `web/public/_redirects`, `/health` and `/status` endpoints, CORS reading `ALLOWED_ORIGINS`, and `DATABASE_URL` support (falls back to local SQLite when unset). None of this requires an account to exist yet - it's just config waiting to be pointed at real infrastructure.

**What needs your direct action** - creating accounts, connecting repos, and setting secrets in each provider's dashboard is something only you can do:

1. **Neon** — create a project, copy the pooled connection string. That's your `DATABASE_URL`.
2. **Render** — new Web Service from this repo. Render should detect `render.yaml` and use it. Set the real values for `DATABASE_URL`, `CALLE_API_KEY`, `GEMINI_API_KEY` in the dashboard (they're marked `sync: false` in `render.yaml` deliberately, so they're never committed). Leave `ALLOWED_ORIGINS` for now - you'll need the Netlify URL first.
3. Run the seed script once against the real database: `DATABASE_URL=<neon-url> python scripts/seed_students.py --target postgres` (from your machine, or a Render shell).
4. **Netlify** — new site from this repo. It should detect `netlify.toml`. Set `VITE_API_URL` to your Render service's URL in Netlify's environment variables, then trigger a build (this only takes effect at build time, not runtime - a later change needs a rebuild, not just an env var edit).
5. Back on Render, set `ALLOWED_ORIGINS` to your Netlify URL (plus `http://localhost:5173` if you still want local dev working against the deployed backend), and redeploy.
6. **UptimeRobot** (or similar) — a free monitor hitting `https://<your-render-url>/health` every 5 minutes. Render's free tier spins down a service after 15 minutes with no traffic; without this, the first real caller after a quiet spell waits through a cold start before anything happens.

**The cold-start caveat, explicitly:** even with UptimeRobot, a spin-down can still happen (a monitor outage, Render's own maintenance) and the first request after one will be slow - `/health` itself won't be slow (it does nothing), but the first real `/api/cases` call will pay the cost of the app waking up, `init_db()`, and the retrieval index either loading from cache or rebuilding. That's what `resume_case()` at startup (`app/dispatcher.py`) is for - a case left "calling" through a spin-down resumes polling instead of being silently abandoned.

## Day 1 checklist (build plan)

- [ ] Place one real call to your own `+264` number by hand via the CALL-E CLI/MCP tools, before trusting the app end to end.
- [ ] Check the CALL-E dashboard for an API key; set `CALLE_API_KEY` in `.env` once issued.
- [ ] Confirm `plan_call` / `run_call` / `get_call_run` are available via `calle mcp tools` as a fallback path.

## Future work

- **Agentic escalation loop — the biggest idea here, deliberately deferred.** When a case can't be resolved on the first call, dispatch a *second* CALL-E call to the relevant office, ask the question on the student's behalf, then call the student back with the answer. Plan → execute → observe → act again, using CALL-E twice per case. This is the one change that would make Ringback itself agentic rather than a deterministic orchestrator, and it's a direct answer to "no transfers, no re-explaining" — the system does the transfer instead of a human. Conditions to build it, not before: core pipeline proven against a *live* CALL-E account (not the mock), the extra call allocation approved, and the frontend already done. It needs a new case status (waiting on an outbound office call) and a second failure surface (what if the office doesn't answer either). Worth revisiting as the demo video's closing beat if all three hold by day 8.
- **Model-backed classifier and router.** Swap the keyword classifier for a single Claude call returning `{intent, confidence, entities}` — cheap, and handles phrasing keywords miss ("won't let me download it"). Similarly, let a model pick the routing office and write the escalation reason from the structured result, instead of the static `ROUTING_TABLE` dict. Neither changes the architecture; both make the judgment sharper. Worth doing once the pipeline is verified against real CALL-E output.
- **Embedding-based retrieval.** `app/retrieval/base.py`'s `Retriever` protocol is designed so an `EmbeddingRetriever` (sentence-transformers) is a one-line swap from `TfidfRetriever` — not built, since it's a ~2GB torch download that buys paraphrase tolerance TF-IDF doesn't have (see Known limitations), which only pays for itself once the corpus is large enough that lexical overlap stops being reliable.
- **USSD intake** — a short code for students on feature phones with no data. Needs a carrier agreement (MTC/Telecom Namibia); not something that can be scheduled.
- **A local NA calling line**, so students see a Namibian number rather than an international one. Costs one email to the CALL-E team — worth sending today, can't be built.

## Submission checklist

- [ ] PR to `https://github.com/CALLE-AI/awesome-phone-call-agents`, correct Contribution Area
- [ ] Demo video public on YouTube/Vimeo, under 3 minutes, no copyrighted music
- [ ] PR URL on the Devpost submission form
- [ ] Text description of features and functionality
- [ ] CALL-E account email
- [ ] Feedback survey submitted (separate prize track)
