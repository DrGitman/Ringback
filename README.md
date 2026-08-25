# Ringback

**Callback-first voice agent for university offices.** Students leave a query; CALL-E calls back and resolves it.

Ringback turns "please hold" into "we'll call you right back." A student dials the office, leaves their question in fifteen seconds, and hangs up. Ringback classifies the query, pulls their record, and dispatches a CALL-E agent to call them back and resolve it — or routes it to the one person who can, with the context already attached.

Built for [CALL-E: Your Code Is Calling](https://call-e.devpost.com). Reference deployment: Namibia University of Science and Technology admin office.

## How it works

1. **Intake** — Twilio answers the inbound call, transcribes the query, hangs up.
2. **Triage** — the query is classified and matched against the student record.
3. **Callback** — CALL-E dials the student back and handles the conversation.
4. **Resolve or route** — structured result either closes the query or opens a ticket with the right office.

## How CALL-E is used

`plan_call` → `run_call` → `get_call_run`, with a result schema that returns whether the query was resolved and, if not, which office should take it.