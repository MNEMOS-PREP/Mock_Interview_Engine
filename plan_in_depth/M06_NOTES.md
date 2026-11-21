# M06 — Post-session notes students can trust: implementation report

> **Date:** 2026-10-24.
> **Brief:** fix the post-session notes, redesign their UI, choose the notes model through NVIDIA NIM, audit the journey, test it. 8 sections.
> **Changed:** M06 backend and frontend, Platform_Core (`ai_core` v0.40.0), Platform_Shell.
> **Status:** implemented, tested, and run live on two recorded sessions.
> **Committed and pushed** on the user's word: Platform_Core `v0.40.0` first, then M06 pinned to it, then the shell.

## At a glance

| Brief | Status | Evidence |
|---|---|---|
| §1 Correct, partial, vague, incorrect, unanswered and unsupported answers are told apart | ✅ | `report._status`: eight statuses from the interview's own judgement; `test_report_status.py` (14) |
| §1 Root cause fixed end to end (evaluation → storage → API → UI) | ✅ | status in the report; write-ups stored in `m06_question_writeup` and keyed by brief; the API serves both; page, My answers and Today all show the same badge |
| §2 Notes UI: status, answer, right, missing or wrong, correct idea, ideal answer, next steps | ✅ | `SessionNotes.tsx`; screenshots of sessions C and E; `SessionNotes.test.tsx` (15) |
| §2 Weak topics and recurring mistakes | ✅ | overview: distribution bar, "Work on first", "Came up more than once" |
| §2 Accessible, responsive | ✅ | colour + shape + word per status (WCAG 1.4.1); screen-reader text on the rubric; `aria-pressed` filters; `aria-live` writing status; checked at 1440 and 500 px |
| §3 Model chosen by measurement on NIM | ✅ | 4 models × 12 cases through the module's own checks; `research/notes_models/RESULTS.md` |
| §3 Provider abstraction kept | ✅ | a `writing` tier in `ai_core.models`; M06 names the tier, never the model |
| §3 Schema validation; malformed, failing, slow and rate-limited output | ✅ | strict schema + `notes_writer.check`; fallback; per-run circuit breaker; live 403 and 429 |
| §4 Bug and regression audit | ✅ | 12 defects fixed (§3 below); each has a regression test that fails with the bug put back |
| §6 Tests, lint, types, build | ✅ | M06 750, frontend 31 (new runner), Platform_Core 166 + 6, shell green; ruff, `tsc`, `vite build` clean |

## 1. Root causes: why a correct, a vague and a wrong answer looked alike

1. **No verdict existed.** Nothing in the data said "this answer was incorrect". How a question ended was a grey phrase ("held up", "moved on").
2. **The only colour came from M13.** A band (Strong / Partly there / Not yet) from the share of key points reached, only on scored questions.
   - It measured coverage, not correctness: an answer could reach every key point and still rest on a wrong idea.
   - It could silently disagree with the interview.
3. **One green ✓ box on every question.** "What a strong answer covers" looked the same under a wrong answer as under a right one.
4. **The student's own answer was hidden** inside a collapsed transcript.
5. **No explanation of the verdict.** Nothing said why the answer was wrong, what the right reasoning was, or what to do next.

## 2. What changed

### The verdict (backend, `report.py`)

The verdict is decided by code; the model only explains it. Each question gets one status:

- correct, partial (shown as "Mostly correct"), vague, incorrect, unanswered, unsupported (a resume claim not backed up), not judged, not reached.
- It comes from how the interview left the question, every judged category across the thread, and any correction.

Rules that matter:

- A wrong idea that stood makes the answer **incorrect**, even if the student later says "I don't know".
- "I don't know" or an off-question answer is **unanswered**, with the reason.
- A correction after a push is still correct, with the qualifier "after a push".
- `status_counts` and `focus` (what to work on first) are built from the same statuses.

### The explanation (`notes_writer.py`, new)

After the session, each judged question gets a written explanation:

- headline, what held (with the student's exact words), what was missing or wrong (each with a fix), the misconception and the correct reasoning, a model answer, and next steps.
- The prompt fixes the status. The writer explains it and cannot change it.

Every write-up passes `check()` before it is shown:

- Quotes must be the student's own words.
- No praise in the headline of a wrong, vague or missing answer.
- An incorrect answer must carry the correct reasoning.
- No strengths for an answer never given.
- No invented misconception for a correct answer.
- Generic advice ("practise more") is dropped.
- Lengths are capped.
- A quote is shown once.

Storage and serving:

- Write-ups are stored per question, keyed by a hash of the prompt version and the brief, so a changed brief or rule set rewrites them.
- They are written in the background on the first report fetch.
- The report says `pending`, `ready` or `partial`; the page polls and fills in each write-up as it lands.

### The page (`SessionNotes.tsx`, `notes.ts`, `components/Status.tsx`)

Each question card:

- **Header:** the status badge (colour, shape and word), with the topic and who asked.
- **Body, in order:**
  - the headline;
  - your answer, quoted;
  - what you got right;
  - what was missing or incorrect — or, for a correct answer, "To make it even stronger";
  - the correct idea;
  - the rubric, each point ✓ / ✕ / – in a neutral frame;
  - one strong answer, labelled reviewed or not;
  - what to practise next.
- The evaluator's view stays in a collapsed section. When its band contradicts the status, a note says so.

Above the cards: a distribution of statuses (never a score), "Work on first", repeated mistakes, and filters for All / Needs work / Correct.

The shell's **My answers** and **Today** card now show the same badge and pick "practise next" in the same order as the notes. They used to show the M13 band, which could call Strong an answer the notes call Incorrect.

### The model (`ai_core` v0.40.0, M06 `llm.py`)

- **New `writing` tier:** `minimaxai/minimax-m3.1-flash` on NIM, with Groq gpt-oss-120b as M06's fallback job.
- **Why minimax:** both models passed 12/12 checks; minimax's next steps were concrete where 120b's read like a syllabus. Its 12 s per question is spent after the session, and it keeps the notes off Groq's daily quota. Detail in `RESULTS.md`.
- **Separate thread pool:** notes calls run on their own pool, so a 20-second write-up never holds a thread a live turn is waiting on.
- **Tolerant parsing:** JSON wrapped in a reasoning block or a code fence is read as the answer.

## 3. Bugs found and fixed (each with a regression test)

Ordered by how directly a student would see them.

| # | Bug | Where found | Fix | Test |
|---|---|---|---|---|
| 1 | Correct, vague and wrong answers looked alike | the brief | status (§2) | `test_report_status.py` |
| 2 | Rubric marked ✕ the points the student had made: the last answer's "missing" list replaced the thread's, so a narrow follow-up un-covered the first answer | live, session C (screenshot) | missed = missed by every answer; same for the study list | `…reached_once…` (fails with the bug) |
| 3 | My answers and Today showed M13's band, which could contradict the notes; unscored questions had no verdict | audit | shared `StatusBadge`, `weakest()` | `notes.test.ts` |
| 4 | Each missed key point listed twice (as a gap and in the rubric) | page tests | rubric only | `SessionNotes.test.tsx` |
| 5 | The page stopped polling after 3 minutes but kept saying "Writing…". React Query re-renders only for what a component reads, so identical answers never re-rendered it | page tests | stalled message + "Check again" | `…stops promising…` |
| 6 | NIM hanging (as it does on some networks) meant 90 s per question before the fallback: 12 minutes for 8 questions | audit | after one failure in a run, the rest goes to the fallback | `…tried_once_per_run` (fails with the bug) |
| 7 | `ai_core.resolve()` raised KeyError for a tier it lacks. With M06 pinned to 0.12.0, the new tier would have switched off **every** M06 model job | audit | `resolve` returns an unusable route; M06's `route_for` too | `test_models.py`, `test_llm_routing.py` |
| 8 | A `not_judged` answer would be sent to the writer, which would invent a verdict | audit | not sent | `…only_a_judged_answer…` |
| 9 | Background write-ups shared the hot-path thread pool (8 threads) | audit | own pool of 2 | `test_llm_routing.py` |
| 10 | One quote repeated under every gap; "I don't know" quoted as evidence | live, sessions C and E | quote once; none for an unanswered question | `test_notes_writer.py` |
| 11 | JSON in a code fence or after a reasoning block failed as "unparseable" | model comparison | `llm.json_object` | `test_llm_routing.py` |
| 12 | A note still said "each answer's band is the share of key points" | live screenshot | now describes the status | — |

## 4. Live verification (2026-10-24)

**Setup:** M06 on 8106 and M13 on 8113, one Groq key, NIM from the gitignored `keys.txt`. Sessions C and E are real recorded interviews.

| Run | Result |
|---|---|
| Session C, NIM | 4 write-ups in 45–50 s (6–17 s each), all minimax, no checker problems; the question never reached got none |
| Session E, NIM key deliberately invalid | every NIM call 403, logged; all 5 written by the Groq fallback in 16 s; the bad key absent from logs |
| Session E, real key, after C | NIM answered 429 on the 10th call in about 2 minutes; that question fell back to Groq at once, with the reason stored |
| Rewrite after the rule change (notes-2) | both sessions rewritten automatically on the next fetch |
| Screenshots | desktop 1440: both sessions; narrow 500: no overflow |

## 5. Research: what was adopted and what was not

- **Gradescope's applied-rubric pattern (adopted):** the rubric with each item marked, rather than a score. This became the ✓ / ✕ / – rubric.
- **Google Interview Warmup (adopted):** insights, not grades. This became the distribution, never a number.
- **WCAG 1.4.1 (adopted):** colour is never the only signal, so every status has a shape and a word too.
- **Vitest + Testing Library + jsdom (adopted):** the frontend's first component tests.
  - vitest **4.1.12**, not 3.2.x: 3.2.x pulls in tinypool and @vitest/mocker with critical and moderate advisories. With 4.1.12, the dependency audit matches what was there before.
- **Instructor (evaluated, not adopted):** M06 already has strict-schema output, a pydantic gate and its own fallback. A second retry layer would hide the failures the checks exist to surface.
- **NIM catalogue:** most listed models answer 404 or hang from this account (`RESULTS.md`). Listed is not served, and the roster now says so.

## 6. Security review

- **The NVIDIA key was pasted into a chat. Treat it as exposed and rotate it** at build.nvidia.com, then replace the `NVIDIA_API_KEY` line in `projects/keys.txt`. Nothing else needs to change.
- **Where the key lives:** only in `F:\AMRITA ALL SEMESTER\projects\keys.txt`, outside every repository.
  - It is read into the backend's environment by `load_keys()`, which logs names only.
  - A scan of the four repos, the logs and the scratch files found no key. `required_keys.txt` holds `REPLACE…` placeholders, and the gitignored `Final_Year_Project/keys.txt` holds only older keys.
- **The browser never sees it:** the frontend calls M06's API; no `VITE_` variable carries a key; model output is rendered as text, never as HTML.
- **Failures stored:** the provider's response body (e.g. "Authorization failed"), never the request headers.
- **Prompt injection through an answer:** bounded. The status is fixed by code before the model sees anything; praise for a wrong answer is refused; quotes must be the student's words.
- **Dependencies:** the new devDependencies add no advisories. Two were already there: vite 6.4.3 (launch-editor, dev server only) and source-map-js. `npm audit fix` resolves both without a major bump.

## 7. Test results

| Suite | Result |
|---|---|
| M06 backend | **750 passed** (new: status 16, writer 19, routing 10); ruff clean |
| M06 frontend | **31 passed** (`npm test`, new); `tsc` clean; `vite build` ok |
| Platform_Core | Python **166 passed** (incl. version parity, 4 new); TS typecheck + 6 tests |
| Platform_Shell | `npm test` passed; `tsc` clean; `vite build` ok |

## 8. Remaining issues and next steps

1. **Done at commit:**
   - Platform_Core tagged **v0.40.0**;
   - M06's pin moved from v0.12.0 to v0.40.0. The suite was re-run against ai-core installed from the tag itself, not the local source;
   - the three M06 TODO copies synced.
2. **Rotate the NVIDIA key** (§6).
3. **Done, on the user's call:** an answer whose opening held but whose follow-up left a wrong idea standing now reads **"Incorrect in a follow-up"**, with the detail "Your first answer held up, but a follow-up did not." It was "Incorrect" beside a full ✓ rubric (live session C, Q1).
   - The status is still incorrect, so the colour, the counts and "work on first" do not change.
   - Tests: `test_report_status.py` (2), `SessionNotes.test.tsx` (1).
   - Live: session C's Q1 carries the label, and only its write-up was rewritten.
4. **NIM's free tier throttled at about 10 calls in 2 minutes.** For a cohort ending interviews together, most notes would come from Groq. Pace a queue, or move to a paid NIM endpoint.
5. **Quality of the write-ups is checked, not yet rated by people.** A round like `M06_HUMAN_EVAL_ROUND1.md` on the notes is the next measure.
6. **Not checked:** dark mode on the notes page. The standalone M06 page has no theme switch for the headless check, so it should be looked at in the shell.
7. **`npm audit fix`** for the two pre-existing frontend advisories.
