# Ringback — standing rules for Claude Code

Callback-first voice agent for university offices, built for the CALL-E hackathon.
Full plan: `README.md`. Design tokens: `web/src/styles/tokens.css`.

## Scope — do not expand without being asked

Three intents only: `proof_of_registration`, `subject_cancellation`, `other` (triage/route).
A fourth idea goes in README "Future work", not in the app.

`app/calle_client.py` is the **only** file that imports or talks to CALL-E. Every other
file uses `CalleClient.dispatch()` / `.get_result()`. If the transport changes (API key
issued, MCP added), that file is the only one that should need edits.

Never re-fire a call with a stale run/plan identifier. A retry always dispatches a
brand-new call (`dispatcher.py` already does this — don't "optimize" it into reuse).

## UI consistency

Different screens must not look like they came from different tools. Every component
reads color, radius, and font values from `web/src/styles/tokens.css` — no hardcoded
hex, no inline font-family strings anywhere else in `web/src`.

Rules, enforced on every screen:

- Page background is always `--canvas`. No pink, cream, or tinted surfaces. Cards are
  `--card` with a 1px `--border` and no drop shadow.
- Headings use `--font-head` (Manrope). Body uses `--font-body` (Inter). Phone numbers,
  student numbers, currency amounts, durations, timestamps, and IDs use `--font-mono`
  (JetBrains Mono). Nothing else is mono.
- Sentence case everywhere. No uppercase transforms, no letter-spacing tricks.
- Solid `--red` appears only on the logo mark and primary buttons. Everywhere else red
  is `--red-tint` background with `--red` text.
- Status is always a tint + text pair plus a dot, never color alone: calling = amber,
  resolved = green, routed = blue, failed = red.
- Radii: panels `--r-panel`, inner cards `--r-card`, inputs `--r-input`, every
  button/tag/chip `--r-pill`.
- Card padding is 20px minimum.
- Shared components — `StatusPill`, `Card`, `Panel`, `PillButton`, `MonoValue`,
  `FieldLabel` (`web/src/components/`) — are how screens stay consistent. Extend them
  rather than styling a one-off element inline.

## Do not build

- A sidebar nav, login/auth, admin CRUD screens, a student portal, or settings pages.
  There are exactly three routes: intake, confirmation, dashboard.
- Stat cards, trend numbers, "active agents" lists, avatars, or stock photography.
- A system-status panel (VoIP gateway, CRM health, etc).
- Notification bells, help icons, or search/filter controls that aren't wired to real
  backend behavior.
- Anything showing data the backend doesn't actually produce. If a screen needs a
  number the API can't supply, the screen is wrong, not the API.

## Phone numbers

Namibia only for this build: fixed `+264` prefix, strip a leading `0` from local input,
validate length before accepting. A wrong number means phoning a stranger.

## Polling, not websockets

The dashboard polls `GET /api/cases` every 2 seconds. Don't add websockets or SSE for
this — it's out of proportion to what a single-tenant hackathon dashboard needs.
