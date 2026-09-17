# M06 — Frontend

The interview surface, on its reserved port **5206** ([PORTS.txt](../PORTS.txt)).

```bash
cd Frontend
npm install
npm run dev          # http://localhost:5206  (Vite binds ::1 — see below)
npm run typecheck
npm run build
```

Vite proxies `/v1`, `/health` and `/status` to the backend on `:8106`, so the
browser sees one origin and CORS never comes up. Point it somewhere else with
`VITE_API_BASE`.

> **`localhost`, not `127.0.0.1`.** Vite binds the name, which resolves to
> `::1` first; an IPv4 request to the same port is refused. The launcher lost a
> day to this once ("The launcher stops hanging on web tabs") — if a script
> cannot reach the dev server, try `http://[::1]:5206`.

---

## The screens

| Route | What it is |
|---|---|
| `/mock` | Setup and history. One choice — how long — because that is the only one the engine can honour today. |
| `/mock/:sessionId` | The interview. The question is the largest thing on the page and the answer box is under it. |
| `/mock/:sessionId/report` | The notes: what was asked, how far each question went, where it stopped. |
| `/mock/system` | Upstream health, which agents are running or ablated, and the step graph the engine compiled. |

`m06Routes` is exported for Platform_Shell, which mounts this exact tree —
`standalone.tsx` only adds the providers the shell would otherwise own.

## Three things worth knowing before changing it

**1. What is deliberately absent is the design.** Spec §2.2: no live score, no
correct/incorrect marker, no progress toward a grade. There is no space
reserved for any of them, and the API will not send them — the live stream
carries no verdict and no key points (`public.py`). A student who can see how
they are doing starts optimising for the meter, and the measurement dies.

**2. The live stream is `fetch`, not `EventSource`.** `EventSource` cannot send
headers, and every candidate-scoped route needs the identity ones (FR-6.26) —
a real session will need a token. `stream.ts` reads the same
`text/event-stream` with `fetch`, which also lets it send `Last-Event-ID` on a
reconnect so no event is missed.

**3. Interviewer tokens are a preview, not the record.** They arrive while the
line is still being written; the `question.asked` event that follows carries
the text of record and replaces them. That matters because the safety guard
can swap a model's line for its authored template mid-stream, and the student
must end up reading the line that was actually asked.

## Layout

```
frontend_M06_Mock_Interview_Engine/
  src/
    routes.tsx        the route tree Platform_Shell mounts
    standalone.tsx    the same tree, with providers, on :5206
    api.ts            one hook per endpoint
    stream.ts         the live stream
    identity.ts       the dev candidate control (PLATFORM_TODO §1)
    types.ts          the shapes the API returns
    components/       MockHome · InterviewStage · SessionNotes · SystemPage
    ui/               AppShell · theme.css (imports @ai/core's tokens)
```
