# M06 — Realism, intelligence and reliability overhaul: implementation report

> **Date:** 2026-10-22/23. **Brief:** "Mock Interview Engine: Realism,
> Intelligence & Reliability Overhaul" (19 sections). **Changed:** M06
> backend and frontend, M13, M05, M01. **Status:** implemented, tested, and
> run live against the real model. **Not committed**: every change is
> in the working trees, waiting for the word to commit.

## At a glance — the brief's acceptance criteria (§19)

| Criterion | Status | Evidence |
|---|---|---|
| A dedicated resume-based mock interview mode | ✅ | track `resume` (`planner.RESUME_TRACK`); `test_resume_track.py` (6); live session E |
| The interviewer responds naturally to answers | ✅ | `interviewer.react()` + tone guard + repeated-opener check; `test_reactions.py` (18); live runs |
| Materially incorrect answers are challenged | ✅ | `ladder.decide` → `challenge` quoting the student; `test_answer_types.py`; live session C |
| Strong answers get deeper follow-ups | ✅ | one level deeper, angled by the topic's level; `test_controller.py` |
| Weak answers → clarify, simplify or move on | ✅ | `clarify`, `probe_specifics`, `simplify`, `move_on` with reasons; `test_controller.py` (cases A–X) |
| Difficulty adapts per topic, not permanently | ✅ | `difficulty.py` TopicState, drifts back to 0, dies with the session; `test_controller.py`, M05 `test_selection.py` |
| Multi-part questions asked one part at a time | ✅ | `decompose.py` + `next_part`; 6 tests in `test_reactions.py` |
| Feedback reflects the actual answers | ✅ | quotes + why, study list, claim check; `test_report_notes.py`; M13 checklist fix |
| Per-question and overall assessments agree | ✅ | one evaluation per question; summary built from the per-question results; M13 `test_threads.py` (7) |
| Excessive fillers trigger useful live feedback | ✅ | `delivery.py`, one note, cooldown; `test_delivery.py` (10) |
| Resume claim-defence interviews terminate | ✅ | idempotent `/end`, drills superseded, keepalive end on leave; `test_lifecycle.py` (7), M01 409 test; live drill check |
| Star and unstar questions | ✅ | `POST …/questions/{turn}/star {on}`; `test_library.py` |
| System-flagged vs student-starred kept apart | ✅ | `SavedQuestion.starred_at` / `flagged_at` independent; `test_library.py` |
| A dedicated question library | ✅ | `/mock/library` (`QuestionLibrary.tsx`), `GET/DELETE /v1/interviews/library` |
| Earlier questions can make a new session | ✅ | `revisit: [entry ids]` → a revisit segment; `test_library.py`; live session D |
| Earlier attempts compared meaningfully | ✅ | `memory.compare()` → `last_time` in notes and library; live session D |
| Memory retrieval validated, not assumed | ✅ | A→B scenario and isolation between students in `test_library.py`; live sessions C→D |
| Common answer edge cases handled | ✅ | cases A–X in `test_controller.py` + `test_answer_types.py` |
| Lifecycle, persistence, async reliable | ✅ | `test_lifecycle.py`, outbox tests, `replay_matches` on every live trace |
| Regression tests for the reported bugs | ✅ | one or more per bug (§2); those found live were shown to fail with the bug put back |
| Existing functionality intact | ✅ | all four suites green: M06 704, M13 187, M05 127, M01 353; lint and `tsc` clean |

## 1. Root causes

| # | Symptom | Root cause |
|---|---|---|
| 1 | Wrong answers accepted, then followed deeper | `ladder.decide` counted any verdict that was not `failed` as a success and went to the next rung. |
| 2 | Follow-ups sounded like approval | Generic rungs presupposed the answer was right, and the interviewer prompt forbade "not quite". |
| 3 | A challenge could never be said | The guard banned every verdict word on every line, so a doubting line always failed it. |
| 4 | Mostly one generic follow-up | No bank item has authored `follow_ups`; personas cap generic rungs at 0/1/2. |
| 5 | Several questions in one breath | Multi-part stems were asked whole. |
| 6 | Repeated, contradictory notes | Each answer turn was scored against the whole question's key points, so a follow-up answer was marked as a failed full answer. |
| 7 | A correct paraphrase "missed" every point | M13 refilled an empty missing-points list from word overlap (`service.py`). |
| 8 | Praise after partial answers | "Credit" was keyed on `success`, which partial answers also had. |
| 9 | A closed drill blocked the next one | `/end` twice → 409; a left drill held the only live slot for 30+ minutes; M01 mislabelled M06's 409. |
| 10 | No sense of what was said before | The strategist saw only the last answer: no self-correction, contradiction or repeat could be seen. |
| 11 | "Focus: Hashing" asked behavioural questions (live, 2026-10-22) | The focus round listed every track and the engine asked under the first, alphabetically `behavioural`; and M05's focus was a ×1.8 preference that lost to its repeat penalties after one question. |
| 12 | "Here's mine again. Can you rephrase that?" (live) | A `clarify` turn did not record the question still open, so a redirect repeated the clarify. |
| 13 | The notes gave an answer to a different question a misconception, and a "claim to back up" (live screenshot) | The notes read the model's misconception, quotes and correct points from every decision, judged or not, and used the resume wording ("the number, the baseline…") for every question. |
| 14 | With the model down, every question read "Answered well" (live run with a bad key) | The fallback policy recorded `left="held"` for answers the rule strategist had not read, and let the interviewer assent to them. |
| 15 | "I'm not sure, I don't know this one" went unread; "I don't know the figure, but…" counted as giving up | The rule fallback's give-up pattern only matched the answer's first words, and had no length limit. |
| 16 | "Walk me through this project" was asked about two resume lines (live) | M01's opening probes are generic by design, because its page shows the line beside them; spoken, nothing said which line. |
| 17 | A correction made after a pushback read "corrected yourself" (live) | Every right answer after a struggle re-ran the correction test, so the next one relabelled it. |
| 18 | "Revisit the idea behind this: no mechanism" under a vague answer (live) | A misconception was kept for any judged answer, though only a wrong statement has one. |
| 19 | A contradiction settled after "how do those fit together?" read "corrected yourself" (live) | The confrontation was not counted as help. |
| 20 | The last answer of every part never reached its topic (found writing a test for 21) | The step that ends a part records the new part, which clears the open question, before its own decision about the last answer. |
| 21 | "0ac8493e-…: a real gap" in a student's summary; labels cut mid-word; "pytest.: the basics held" (live screenshot) | Topics were named by their concept id, which for a resume line is its claim's id; labels were cut at 80 characters. |
| 22 | "Practise <resume line> again" planned an empty interview (live screenshot) | The notes sent any concept id as a focus, a claim's and the opener's too; no track holds those. |
| 23 | "What held" listed "Uses chaining" and "mentions chaining" (live screenshot) | Points from different decisions were deduplicated by exact text. |

## 2. Bugs fixed

Every one has a regression test; those found live (11–23) were also shown to fail with the bug put back.

| Bug | Fix | Test |
|---|---|---|
| Wrong answers accepted (1, 2, 8) | Explicit decision controller; tone keyed on the decided move | `test_controller.py`, `test_answer_types.py::test_a_wrong_answer_is_pushed_back_on_in_the_students_own_words` |
| Challenge blocked by the guard (3) | Guard tones: `neutral`, `credit`, `challenge` | `test_reactions.py` (tone tests) |
| Per-answer scoring (6) | One M13 evaluation per question, when it closes | M13 `test_threads.py`; M06 `test_outbox.py` |
| M13 checklist refill (7) | Removed; the evaluators' list stands | M13 `test_threads.py` |
| Drill lifecycle (9) | `/end` idempotent; a live drill is superseded by any new session (a live mock still blocks); sweeper grace scales with length; the room ends a drill on leave; M01 says "in progress" and links it | `test_lifecycle.py` (7); M01 `test_api.py` |
| Warm-up answer credited to the next round (found by the idle test) | Thread-scoped fold | `test_idle.py` |
| Focus round off topic (11) | Planned under the tracks holding the focus; M05 `only_concepts` hard filter, never relaxed; M06's own playlist honours it | M05 `test_selection.py` (3), `test_planner.py` (3), `test_answer_types.py::test_a_focus_asks_only_its_concept_and_then_ends_the_round` |
| Redirect after clarify (12) | The clarify turn records the open question | `test_answer_types.py::test_a_redirect_after_a_clarify_repeats_the_question_not_the_clarify` |
| Client-contract gate read a POST `fetch` as GET | The gate reads a raw `fetch`'s method | `test_client_contract.py` |
| Findings from unjudged answers (13) | Recorded only for judged categories, at the source; the notes also filter older events; resume wording only on resume lines | `test_report_notes.py` (3) |
| "Answered well" with no model (14) | An unread answer leaves `unjudged` ("Not judged: the answer checker was unavailable"), and gets no assent | `test_controller.py::test_an_answer_nobody_read_is_never_said_to_have_held`, `test_answer_types.py` |
| Give-ups missed or over-matched (15) | Hedges allowed before the words, other phrasings added, short answers only, rephrase requests checked first | `test_answer_types.py::test_a_give_up_in_other_words_is_read_without_the_model` |
| A resume question that names no line (16) | Its line is read out first | `test_resume_track.py::test_a_question_that_does_not_say_which_line_reads_the_line_out` |
| Corrections relabelled (17, 19) | A correction is the right answer that turns a struggle round, counted once; help is the last move that did more than restate; a confrontation is help; "prompted" stays prompted, in older sessions too | `test_controller.py` (3), `test_report_notes.py` (2) |
| A misconception for a gap (18) | Kept only for incorrect, partial and contradicting answers | `test_report_notes.py::test_a_vague_answer_shows_a_gap_not_a_misconception` |
| A part's last answer lost (20) | The fold applies a decision that follows a part's end to the question that end closed; replay still matches | `test_resume_track.py::test_the_last_answer_of_a_part_reaches_its_topic` |
| Ids and cut labels in the summary (21) | Topics named as their questions are; labels cut at a word, their own full stop dropped | `test_resume_track.py`, `test_report_notes.py` |
| An empty "practise again" (22) | The button only for bank concepts (a resume line is starred instead); a focus no track holds is left out of the plan with a reason | `test_planner.py::test_a_focus_no_track_asks_about_is_left_out_and_says_why` |
| Repeated points (23) | Compared by their content words | `test_report_notes.py::test_a_point_two_decisions_worded_differently_is_listed_once` |

## 3. Features, by section of the brief

- **§1 Resume interview.** A `resume` track: it opens "walk me through your resume", then asks about the claims M01 wrote probes for, spread across sections. It is offered first when the student has a resume, and the notes carry a claim check.
- **§2, §4 Reactions.** The decided move is phrased by `interviewer.react()` from the student's own words. A challenge may doubt and may not praise; a line after an answer that held may assent but never gushes; nothing judges the person. The interviewer never repeats its last openers, and never says a five-word run of the answer key the student has not said. When the model's line fails any of these, an authored line for the move and register is used.
- **§3 Difficulty.** Each topic has a level from −2 to +2, moved by the last two answers on that topic and drifting back toward 0. It sets how deep the follow-ups may go, their angle (harder: edge cases, failure, scale, trade-offs; easier: diagnostic), and where M05 pitches the next question on that topic (0.5 logit per level). It never changes θ, and dies with the session.
- **§5 One thing at a time.** A stem that asks several things is split once (rules, then a validated model split), cached, and asked as a primary question with the rest as follow-ups. Each part's key points are scoped, so the student is never marked down for a part not yet asked.
- **§6 Notes.** Per question: what held, what went wrong (their quote and why), unsupported claims, contradictions, a correction (by themselves or after a push), a misconception named, a study list, how it went in plain words, and the comparison with their last attempt. The session summary is built from those, so the two cannot disagree.
- **§7 Delivery.** Fillers, repeats and restarts are counted, and pace is measured when the room gives timing. There is one short note per answer at most, with a cooldown, given live only in practice and mock; the report summarises it and says what was not measured. Since 2026-10-23 the room sends timing for spoken answers, and marks an answer the microphone cut off.
- **§9–§10, §14 Library and memory.** Questions can be starred during an interview or in the notes. The interview flags the ones worth another go (a misconception that stood, a claim not backed, a skip), independently of stars. Every attempt is kept. `/mock/library` filters by mark and topic, and builds a practice session of the chosen questions asked as they were. The notes compare the last two attempts.
- **§11, §13 Scoring.** M13 is sent the whole thread of the student's own words, never the interviewer's. `prompts_used` counts the pushes before a correction and costs credit like a hint at M13's published factors. `key_point_ids` scopes the key points to what was actually asked.
- **§15 Reliability.**
  - A session with the model down never says how an answer went: the notes read "Not judged", and the interviewer does not assent to answers nobody read.
  - The rule fallback recognises a give-up in ordinary words.
- **§12 Answer types A–X.** Each has a decision and a test. The categories are correct, correct-incomplete, partial, incorrect, vague, off-question, don't-know, unsupported, contradiction, ambiguous and non-answer, plus asks-for-time, a challenged premise, a repeated answer, a cut-off answer, conduct, and injection attempts.

## 4. Architectural changes

- **The verdict decides; the model phrases.**
  - Strategist prompt `strategist-5` returns a category, a severity and quoted evidence: `error_quote`, `unsupported_quote`, `contradiction_quote`, `correct_points` and `misconception`.
  - It is given the question's thread, the earlier answers, the resume claim, and the parts not asked yet.
  - The old band and justification are derived from the category, so M13 and M05 consumers are unchanged.
- **`ladder.decide` is an explicit policy.**
  - Conduct, then requests, time, cut-offs, ambiguity, off-question, repeats, contradictions, unsupported claims, don't-know, wrong, vague, incomplete, and correct, in that order.
  - Each outcome carries a `reason`, a `quality` (0–1) and how the question was `left`.
  - All three are recorded on `probe.decided` and visible in the trace.
  - Verdicts without a category keep the old policy.
- **State.** `TopicState` per concept and a per-question thread are folded from the event log like everything else, so a replay reproduces them (`replay_matches`).
- **New modules:** `difficulty.py`, `thread.py`, `decompose.py`, `memory.py`, `delivery.py`.
- **New tables:** `m06_question_split`, `m06_saved_question`, `m06_question_attempt`.
- **New routes:** `GET /v1/interviews/library`, `DELETE /v1/interviews/library/{id}`, `POST /v1/interviews/{sid}/questions/{turn}/star`. That makes 45 in all.
- **Contracts:**
  - M05 `SelectionRequest` gains `difficulty_offset`, `difficulty_shift` and `only_concepts`.
  - M13 `EvaluateRequest` gains `prompts_used` and `key_point_ids` (`m13-eval-1.1.0`).
  - M06 `PlannedSegment` gains `concepts_only`.
  - M06 `AnswerIn` gains `completion_reason`, and `AsrNote` gains `duration_s`.
- **Frontend:**
  - Library page, star toggle, coach-note chip and rich notes.
  - A keepalive end request when a drill is left.
  - Timing and cut-off reporting for spoken answers.

## 5. Tests and results

| Suite | Before | After | Result |
|---|---|---|---|
| M06 backend | 570 | **704** (82 release gates) | all pass; `ruff check` clean |
| M13 | 180 | **187** | all pass; lint clean |
| M05 | 121 | **127** | all pass; lint clean |
| M01 | 352 | **353** | all pass; lint clean |
| M06 frontend | — | `tsc --noEmit` | clean |

New test files in M06:

| File | Tests | What it covers |
|---|---|---|
| `test_controller.py` | 47 | The decision table, cases A–X |
| `test_answer_types.py` | 18 | Answer types through the whole engine |
| `test_reactions.py` | 18 | Tone, leaks, openers, decomposition |
| `test_delivery.py` | 10 | Filler and delivery notes |
| `test_library.py` | 8 | Stars, flags, revisit, comparison, isolation |
| `test_lifecycle.py` | 7 | Drill and session lifecycle |
| `test_resume_track.py` | 9 | The resume interview |
| `test_report_notes.py` | 12 | The notes |

M13 adds `test_threads.py` (7). Model output is tested by behaviour and schema, not exact wording.

### Live validation (real Groq models, fresh students, paced under 8K tokens/min, one key)

Three rounds, on the real services (M01, M04, M05, M06, M13) and the real Groq models: gpt-oss-20b for the strategist, gpt-oss-120b for the interviewer and M13, and llama-prompt-guard. Each round used a fresh student and one key, paced at 25 seconds an answer: no rate limit was hit and no call failed. Every trace replayed to the same state (`replay_matches` true).

- **Round 1** (focus: Hashing) found root causes 11 and 12.
- **Round 2** ran with the model unreachable, because of a bad key in the test's launch script. It exercised the degraded path and found 14 to 16.
- **Round 3**, with the model:

  | Session | What was checked | Result |
  |---|---|---|
  | **C — mock, focus Hashing** (16 answers) | Warm-up story | A follow-up on its content ("why does testing hypotheses one at a time isolate the cause?") |
  | | Wrong answer | Challenged in the student's words: "You mentioned the second key 'simply overwrites the first' — what would happen to a lookup for the original key?" |
  | | The correction | Went deeper: linked list against balanced tree for a bucket's chain |
  | | Vague answer | A request for the exact steps |
  | | The same answer again | Named |
  | | "I'm not sure, I don't know this one" | One simpler question, then a graceful move on |
  | | An answer to another question | Redirected once |
  | | The focus | Every question on hashing |
  | | Scoring | M13 scored the collision question complete, with evidence quoted |
  | **D — practice, two flagged questions again** | The revisit | Announced as practised again and asked as stored; the new answers were followed up |
  | | The library | "About the same as last time" |
  | **E — resume interview** (a pasted resume, 5 claims) | Opening | "Walk me through your resume" |
  | | Claim questions | Each specific to its line |
  | | A contradiction | "led a team of 4" against "built it on my own", confronted with both quotes |
  | | Claim checks | In the notes, e.g. "did not fit together — settle the story first" |
  | **Drills** | Two in a row | The second started; the first was `aborted / superseded` |
  | | A drill during a live mock | "You have an interview in progress… the questions are below in the meantime", with a link |

- **The notes and library pages** were rendered at 1440 px in headless Edge. They showed root causes 17 to 23, all fixed and checked again.

## 6. Design decisions and the evidence behind them (§16)

| Decision | Problem | Principle / evidence | Trade-off | Tested by |
|---|---|---|---|---|
| Decide the move in code from a structured verdict; the model only phrases it | The prompt decided the tone, and any non-`failed` verdict counted as success | Structured interviews owe their reliability to standardised, anchored procedure, not improvisation [1, 2]. LLM judges carry position and verbosity biases [3, 4], so the judgement is kept narrow and structured. | Less free-form follow-up; a mislabelled category now yields a definite (wrong) move | `test_controller.py`, `test_answer_types.py` |
| Challenge in proportion to severity, once, quoting the student; then simplify or move on | Misconceptions were validated | Conceptual change needs the conflict made explicit [5]. Feedback aimed at the task helps; aimed at the self, it can harm [6]. | One challenge only: a misconception that survives is recorded, not argued | `test_answer_types.py`, `test_reactions.py` |
| Contingent difficulty per topic, temporary | One global level; nothing ever got easier | Contingent tutoring: more help after failure, less after success [7, 8]. CAT targets each content area separately [9, 10]. | A two-answer window reacts fast but is noisy; nothing persists across sessions, by design | `test_controller.py`, M05 `test_selection.py` |
| One question at a time | Students answered half of a two-part stem | Double-barrelled questions lower answer quality [11]; least-to-most decomposition [12] | One cached model call per new stem (5 s timeout; the whole stem on failure) | `test_reactions.py` |
| Score the whole question once, blind to the interviewer, assistance priced in | Follow-up answers scored as failed full answers | Per-question anchored rating drives interview reliability [13, 14]; assistance received is evidence about proficiency [15] | Scores land when a question closes, not after each answer | M13 `test_threads.py`, `test_outbox.py` |
| Feedback that quotes the answer and says what to study | Generic notes; "missing" points the student had said | Effective feedback is specific, task-level and forward-looking [16, 17]; claims grounded in quoted evidence [18] | Fewer notes when the evidence is thin | `test_report_notes.py` |
| Filler notes above conversational norms, one at a time, honest about limits | Any filler count above zero was shown | About six disfluencies per 100 words is normal conversation [19]; fillers do communicative work [20]; ASR models omit many fillers [21, 22] | Fillers the recogniser dropped are not seen; thresholds are settings | `test_delivery.py` |
| Structured memory keyed by student and question, not vector search | Nothing remembered between sessions | Retrieval practice and spacing improve retention [23, 24]; agent memory retrieves by recency, importance and relevance [25], and here importance is explicit (star, flag) | Exact questions only; no "questions like this one" | `test_library.py` |
| A focus is a hard constraint | "Focus: Hashing" drifted after one question | Content constraints in constrained adaptive testing are hard, not weights [26] | A focus round ends early when the bank is thin (hashing has 6 items) | M05 `test_selection.py`, `test_planner.py`, `test_answer_types.py` |
| A drill is disposable; closing is idempotent | A closed drill blocked the next | Idempotent operations; leases that expire | A left drill ends; its progress is not resumable | `test_lifecycle.py`, M01 `test_api.py` |

Nothing heavier was used where a simpler rule did the job: no vector store, no learned difficulty model, no NLI service.

## 7. Remaining limitations

- **The bank is thin.**
  - No item has authored follow-ups, so follow-ups are generic rungs, now angled by topic level.
  - Only 12 items are reviewed, all DSA. Drafted items are asked but not scored, and do not move θ.
  - A focus round ends when its topic runs out.
- **Model quality bounds judgement.**
  - The strategist (gpt-oss-20b) can mislabel a category.
  - M13 runs at the "dev" grade: gpt-oss-120b three times, lexical key-point matching, no NLI model.
- **Delivery is partly blind.**
  - Whisper and the browser recogniser drop most "um"s and "uh"s.
  - Typed answers have no pace.
  - A cut-off is detected only from the browser recogniser's microphone or network errors; M11-side detection is not wired.
- **Rate limits.**
  - Groq allows 8K tokens per minute per model.
  - A student answering quickly can hit a 429, and the authored lines take over.
  - Whether to retry a 429 on the second key is still the open policy decision (see the TODO, 2026-10-17). These runs used one key.
- **Navigation.** The library has no link in Platform_Shell's nav, because the shell is on its unmerged `feat/gd-entry` branch. It is reachable from the mock home page.
- **Resume interviews** ask only about claims M01 wrote probes for.

## 8. Configuration and migration

- **Database.**
  - Three new tables, created at startup by `create_all`.
  - No columns were added to existing tables, so no migration is needed.
- **New settings**, all optional:

  | Setting | Default | Meaning |
  |---|---|---|
  | `M06_FILLER_RATE` | 6 | Fillers per 100 words |
  | `M06_FILLER_MIN` | 4 | Fewest fillers before a note |
  | `M06_MODEL_DECOMPOSE` | extraction tier | Model for splitting multi-part questions |
  | `M06_DECOMPOSE_TIMEOUT` | 5 s | Time allowed for a split |

- **Prompt versions:** `strategist-5`, `interviewer-4`, `split-1` (new), and M13's `m13-eval-1.1.0`.
- **Deploy M05 and M13 together with M06.**
  - Their new request fields have defaults, and an older service ignores unknown fields rather than failing.
  - With an old M05, a focus round would steer rather than hold to its topic.

## References

1. Campion, Palmer & Campion (1997). A review of structure in the selection interview. *Personnel Psychology* 50(3).
2. Levashina, Hartwell, Morgeson & Campion (2014). The structured employment interview. *Personnel Psychology* 67(1).
3. Zheng et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS*.
4. Wang et al. (2023). Large Language Models are not Fair Evaluators. arXiv:2305.17926.
5. Posner, Strike, Hewson & Gertzog (1982). Accommodation of a scientific conception. *Science Education* 66(2).
6. Kluger & DeNisi (1996). The effects of feedback interventions on performance. *Psychological Bulletin* 119(2).
7. Wood & Middleton (1975). A study of assisted problem-solving. *British Journal of Psychology* 66(2).
8. Wood, Bruner & Ross (1976). The role of tutoring in problem solving. *J. Child Psychology and Psychiatry* 17(2).
9. Kingsbury & Zara (1989). Procedures for selecting items for computerized adaptive tests. *Applied Measurement in Education* 2(4).
10. van der Linden & Glas, eds. (2010). *Elements of Adaptive Testing*. Springer.
11. Bradburn, Sudman & Wansink (2004). *Asking Questions*. Jossey-Bass.
12. Zhou et al. (2023). Least-to-Most Prompting Enables Complex Reasoning in LLMs. *ICLR*.
13. Conway, Jako & Goodman (1995). A meta-analysis of interrater and internal consistency reliability of selection interviews. *J. Applied Psychology* 80(5).
14. Huffcutt & Arthur (1994). Hunter and Hunter (1984) revisited: interview validity for entry-level jobs. *J. Applied Psychology* 79(2).
15. Feng, Heffernan & Koedinger (2009). Addressing the assessment challenge with an online system that tutors as it assesses. *User Modeling and User-Adapted Interaction* 19(3).
16. Hattie & Timperley (2007). The power of feedback. *Review of Educational Research* 77(1).
17. Shute (2008). Focus on formative feedback. *Review of Educational Research* 78(1).
18. Gao, Yen, Yu & Chen (2023). Enabling LLMs to Generate Text with Citations. *EMNLP*.
19. Bortfeld, Leon, Bloom, Schober & Brennan (2001). Disfluency rates in conversation. *Language and Speech* 44(2).
20. Clark & Fox Tree (2002). Using *uh* and *um* in spontaneous speaking. *Cognition* 84(1).
21. Radford et al. (2023). Robust Speech Recognition via Large-Scale Weak Supervision (Whisper). *ICML*.
22. Zusag, Wagner & Thallinger (2024). CrisperWhisper: accurate timestamps on verbatim speech transcriptions. *Interspeech*.
23. Roediger & Karpicke (2006). Test-enhanced learning. *Psychological Science* 17(3).
24. Cepeda et al. (2006). Distributed practice in verbal recall tasks. *Psychological Bulletin* 132(3).
25. Park et al. (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST*.
26. van der Linden & Reese (1998). A model for optimal constrained adaptive testing. *Applied Psychological Measurement* 22(3).
