# M06 — Manual QA script (Phase 1, text)

**Who runs it:** anyone, before every release.
**How long:** about 15 minutes.
**Why it exists:** the automated suite proves the engine. This script proves what a student actually sees. Spec §12 asks for one, and its voice-and-camera steps wait for M11 and M12.

Each step says what to do, then what must be true. Copy in quotes is the exact string that ships. If a step fails, write down the step number and the session id (from the URL) and stop — the trace (step 15) is what someone will debug from.

---

## 0. Setup (2 min)

1. Start M06 with `start.bat` in `Mock_Interview_Engine` (API `:8106`, web `:5206`). Start the other modules too if they are present (M02, M04, M05, M13). Every one of them is optional; the session says which ones are missing.
2. Open `http://localhost:5206/mock/system`.
   - **Must be true:** the upstream table lists M01, M02, M04, M05 and M13. Each says up or down, and a down one shows the sentence a student is told.
   - **Must be true:** the agent list shows the five agents — `QuestionPlanner`, `TechnicalInterviewer`, `ProbeStrategist`, `SafetyGuard` and `ReportComposer` — each marked on or ABLATED.
3. Open `http://localhost:5206/mock`.

## 1. Setup screen and plan preview (2 min)

4. Choose **Mock** and **15 min**, then press **Start interview**.
   - **Must be true:** four modes are offered, and each has a one-line description of what it changes.
5. On the plan preview:
   - **Must be true:** each part shows "with ‹name›, ‹title›", its minutes, its question count, and M02's reason for it.
   - **Must be true:** the closing has no **Remove** button.
   - **Must be true:** any requirement the session cannot reach is listed rather than hidden.
6. Press **Remove** on one part.
   - **Must be true:** the part stays in the list, greyed out, with the reason.

## 2. The interview (6 min)

7. Press **Start**.
   - **Must be true:** the first interviewer introduces themselves by name, and the warm-up question follows.
8. Answer the warm-up with anything. Then answer the next question with **"I don't know"**.
   - **Must be true:** the interviewer moves on with the graceful exit — for example "Okay, let's leave that there." Nowhere on the screen does it say "wrong", "incorrect" or show a score.
9. On the next question, give a real answer of two or three sentences.
   - **Must be true:** a follow-up digs into what you said, rather than a new topic.
10. Press **Hint**.
    - **Must be true:** before you take it, the button says what the hint costs — "this answer would then count for 85%" or similar.
    - **Must be true:** the hint arrives, and the question stays open.
11. Press **Repeat the question**.
    - **Must be true:** the same words appear again, verbatim, near the answer box.
12. Press **⚑ Flag**, then **Unclear**.
    - **Must be true:** you get one of two messages. "Thanks — flagged…" means the flag reached M05. "Recorded here — the question bank was unreachable…" means it did not.
13. Type nothing for the interviewer's patience (42–66 s, depending on who is asking).
    - **Must be true:** a gentle prompt appears beside the question; it is not a new question.
    - Wait again. **Must be true:** a second prompt.
    - Wait again. **Must be true:** the offer to move on appears, with **Move on** and **Keep thinking**. After that, no more prompts.
    - Press **Move on**. **Must be true:** the next question is asked.
14. Press **Pause**.
    - **Must be true:** it asks first: "Once, up to 5 min — the clock stops."
    - Press **Pause now**. **Must be true:** the status reads Paused and the timer stops.
    - Press **Resume**. **Must be true:** you are back on the same question.

## 3. Leaving and coming back (2 min)

15. Refresh the browser in the middle of a question, and wait more than 5 seconds before it reloads (or close the tab and reopen the URL).
    - **Must be true:** "Welcome back — we were on question N of ‹round›." The same question is open, and the timer did not count the time you were away.
16. Turn the network off (DevTools → Network → Offline) for about 10 seconds, then back on.
    - **Must be true:** "Lost connection — reconnecting…" appears after a moment.
    - **Must be true:** when the network is back, the banner clears and the interview continues.

## 4. The closing and the notes (2 min)

17. Answer until you see "Anything you'd like to ask me?" (or "Do you have any for me?"). Ask a question.
    - **Must be true:** the interviewer acknowledges the question without pretending to answer for the real panel, then asks "Anything else?"
    - Answer **"No, that's all."** **Must be true:** the session ends with the closing line.
18. Open the notes.
    - **Must be true:** under each question there is a sentence on how deep it went, the hints you took, and "What a strong answer covers".
    - **Must be true:** your own question appears under **Your questions for the interviewer**.
    - **Must be true:** no number appears anywhere.
    - **Must be true:** the question you moved on from in step 13 reads "We moved on from this one after a pause."
    - If M13 is running and has scored, **What the evaluator noticed** shows reasoning and quotes from your answers — words only.
19. Open `http://localhost:8106/v1/interviews/‹session id›/trace` with the same identity headers.
    - **Must be true:** `replay_matches` is `true`.

## 5. Two more modes (1 min each)

20. **Practice:** answer one question with "I don't know".
    - **Must be true:** after the graceful exit you see **Try it again** and **Move on**. Take the retry; afterwards the notes say the first attempt is the one that was scored.
21. **Final Boss:** check the stage and the interviewer's lines.
    - **Must be true:** there is no hint button — "No hints in this mode."
    - **Must be true:** the interviewer is terse and never rude.

---

| Step | Pass | Notes |
|---|---|---|
| 0–3 setup | ☐ | |
| 4–6 preview | ☐ | |
| 7–14 interview | ☐ | |
| 15–16 coming back | ☐ | |
| 17–19 closing and notes | ☐ | |
| 20–21 modes | ☐ | |

Tester: ______  Date: ______  Build (M06 commit): ______
