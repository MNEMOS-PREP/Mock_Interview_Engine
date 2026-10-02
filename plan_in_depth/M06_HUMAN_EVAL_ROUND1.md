# M06 — Human evaluation, round 1

**For:** the team running the study, and the faculty member who signs it off.
**Spec:** §12, *"Human evaluation [the real test]"*: ten students each do a session, then a five-minute structured interview. Run every phase. This is round 1: Phase 1, typed.

**What it decides:**
- **AC-6.8** — *"felt like a real interview"*: the mean must be at least 4.0 out of 5.
- **AC-6.12** — sessions where a student felt humiliated: there must be **zero**.

No automated test can measure either of these. The suite proves the engine does what the spec says; this round finds out whether that is what a student needs.

---

## 1. Before anyone sits down

The day before:
- **Run the manual QA script** ([M06_QA_SCRIPT.md](M06_QA_SCRIPT.md)) once, end to end, on the machine the students will use.
- **Start the five services** — M02, M04, M05, M06 and M13 — with one shared `M04_SERVICE_SECRET`, so M04's guard is on. This is the configuration verified live on 2026-10-02. If M04 is missing, nothing moves the skill graph; if M13 is missing, there is no feedback in the notes; and neither failure is visible to the student mid-session.
- **Check the model:** `/mock/system` must say *"A model is configured."* A session without one runs entirely on templates. That is a different study, and not the one you want to run.
- **Use real postings:** load two from the placement cell into M02, and note their `jd_id`s.
- **Check the bank:** M05 reports **12 items**, which is thin. A 30-minute session can run a round type dry, and the round then ends early (by design — §6.1's 409). Note any session where this happens; it is a finding about M05, not M06.
- **Clear the reliability page:** `/mock/system` should show no crashed steps and no failure endings left over from testing.

## 2. Who

- **Ten students**, final-year, who have not worked on this platform.
- **A spread of preparation levels.** Ask each to self-rate before the session (1 — not started, 5 — interviewing now), so the analysis can tell "felt real" apart from "felt easy".
- **Split by mode:**
  - six on **Mock**;
  - two on **Practice** (retries on, hints on);
  - two on **Final Boss** (no hints, a hard clock, the bar-raiser).

  Final Boss is where AC-6.12 is most at risk, which is why it is in round 1.

## 3. Consent

Each student consents twice:
1. **On paper**, using the form below.
2. **In M04**, with purpose **`research`** — `POST /v1/candidates/{id}/consent {"purpose": "research"}`. The `practice` purpose the product uses does not cover study data (M04 FR-4.18c).

> **Consent — AI mock interview study, round 1**
> You will do one typed mock interview of about 30 minutes, then answer seven short questions about it. The interview is practice: nothing about it is shared with any recruiter or placement record. We keep the interview's text and your answers to our questions, under a code rather than your name, for the duration of the project. You can stop at any time, and you can ask us to delete your data at any time, without giving a reason.
> Name ________ Signature ________ Date ________

Keep the mapping from names to codes **on paper only**. The candidate id in the system is a random UUID.

## 4. The session (45 minutes per student)

| Minutes | What happens |
|---|---|
| 0–2 | **Briefing**, read verbatim (below). Don't explain the scoring or the interviewer — that is what is being tested. |
| 2–32 | **The session.** 30 minutes, the student's assigned mode, one of the two postings via `/mock?jd=<id>`. The observer sits behind, says nothing, and notes the clock time of any visible reaction — a laugh, a frown, a long stop. |
| 32–37 | **The structured interview** (§5). |
| 37–42 | **The notes.** The student opens their notes; ask Q7. |
| 42–45 | Debrief and thanks. |

**Briefing (verbatim):** *"This is a practice interview with an AI interviewer. Answer as you would in a real one — type what you'd say out loud. There's no score during it. You can pause once, and you can end early. Afterwards we'll ask you a few questions about how it felt. We are testing the interviewer, not you."*

## 5. The structured interview (5 minutes, in this order)

1. **"On a scale of 1 to 5, how much did that feel like a real interview?"** One number. → AC-6.8
2. "Where did it feel *most* like a real interview?"
3. "Where did it feel *least* like one?"
4. **"Was there any moment you felt embarrassed, belittled or humiliated?"** Yes or no; if yes, where. → AC-6.12 — a single yes fails the gate.
5. "When the interviewer moved on from a question you couldn't answer, how did that land?" — tests the graceful exit, §6.5's hard requirement.
6. "Did the interviewer ever seem to misunderstand you?" — on the first live run, the strategist judged a correct-but-differently-framed answer as *"a different question"*; this is where that shows up.
7. *(after the notes)* "Would you do anything differently next time because of these notes?"

Write the answers down **verbatim**. A summary of what a student said is a finding the summariser already believed.

## 6. What gets recorded

| What | Where | Why |
|---|---|---|
| Code, mode, posting, self-rating | the study sheet | the analysis's columns |
| Q1–Q7, verbatim | the study sheet | AC-6.8, AC-6.12, the themes |
| Observer's timestamps | the study sheet | to find the moment in the trace |
| The session id | the URL, `/mock/<id>` | everything below hangs off it |
| The full trace | `GET /v1/interviews/<id>/trace` | every line, decision and model call; replayable (FR-6.19) |
| The notes | `GET /v1/interviews/<id>/report` | what the student was shown |

Export the trace and the report for every session on the day. They are built from the event log, so they will not change afterwards — but a database that gets reset does.

## 7. Analysis

- **AC-6.8:** the mean of Q1 over ten. Report the spread as well as the mean: a 4.0 from ten 4s and a 4.0 from five 5s and five 3s are different findings.
- **AC-6.12:** any yes in Q4 fails round 1. For each one, find the moment in the trace and name the line. If the interviewer said it, the copy is the fix (`phrasebook.py`, or the persona's YAML); if the strategist decided it, the prompt is.
- **Themes:** group Q2, Q3, Q5 and Q6 answers. Each theme names a mechanism, because every structural line is authored (§6.2) and every decision is on the log.
- **Q6 against the trace:** every misunderstanding a student reports should have a `probe.decided` event behind it. Count how many were the strategist's `off_question`; that number decides whether `strategist-3` needs another pass.
- **Cross-check what the student was shown:** the report must match the transcript for every session. A mismatch is a bug, whatever the student thought of it.

## 8. What round 1 can't tell you

- **Voice.** Phase 1 is typed. Speaking out loud changes how real an interview feels more than anything else, and it waits for M11. Round 2 repeats this script on voice.
- **Scores.** M13's numbers stay behind its display gate until calibration agrees with human raters, so students see words, not grades. If anyone asks, that is the answer.
- **Coding and design rounds.** Those are dropped at plan time until M07 and M08 exist, and a posting that asks for them says so on the preview.

Two places to look for these trade-offs:
- M06's [TODO](M06_Mock_Interview_Engine_TODO.md) §7–§8 lists what waits on another module.
- This document's §7 is how round 2 should be compared with round 1.
