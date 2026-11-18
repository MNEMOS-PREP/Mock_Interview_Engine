# The question bank — `q_bank_discovered.pdf`

Every question a student has answered in a mock interview, by subject, each with
the answer to say out loud and the follow-ups the interviewers asked next. It
grows after every question, and the student downloads it from Today.

Added 2026-11-18 at the user's request: *"a pdf … continuously edited live as a
question is addressed by a candidate … a dedicated styled page for every concept
… all question with answer that u have come across (not student answer but the
actual answer well scripted in a way it can said by student) … doesn't matter
if the actual answer of the student was partial or incorrect."*

## How it works

| Step | Where | What |
|---|---|---|
| A question is met | `collect.py` | It is in the bank once it was **answered and its thread closed**: the interviewer moved on, or the session ended. An open question is left out, so its answer key is never on the desk while it is being asked. The closing "any questions for me?" is not ours. |
| Its follow-ups | `collect.py` | The moves that ask something new (rung, missing point, challenge, simpler question, specifics, evidence). Not the ones that manage the talk (repeat, clarify, redirect, hint), not the stock lines that fit any question (read from `phrasebook.py`), and not an acknowledgement in front of one ("Right. Besides…"). |
| Its answer | `book.py` | The item's reference answer, as written: a model never rewrites an answer a person reviewed. An older event log holds only the stem, so `refresh` fetches the item from M05 once and keeps it (`QBankLookup`). |
| What nobody wrote | `answers.py` | One model call per question: merge the follow-ups that ask the same thing ("why O(1)?" and "why constant time?"), make each read on its own, and answer each in the first person. Code checks that every follow-up stands for one that was asked, that nothing is a list or talks about itself, and that a reviewed answer is left alone. A question only the student can answer (a resume line, the opening) gets *how to answer*, with `[brackets]` for their own facts. |
| Its subject | `book.py` | The item's M05 track (the setup page's names and order), else the track of another question on the same concept, else M04's domain. Topic names are M04's. |
| The file | `render.py`, `__init__.py` | Drawn from the tables on every download, and redrawn only when what it shows changed (`Book.fingerprint`). After each answer and at the end of an interview, `refresh` runs as a background task: look-ups, redraw, write, redraw. |

Routes: `GET /v1/interviews/question-bank` (counts, for Today's card) and
`GET /v1/interviews/question-bank.pdf` (the file). Both serve the signed-in
student only. Files: `qbank_files/<student>/` beside the database
(`M06_QBANK_DIR` moves it). They are a cache of the tables and can be deleted.

Operator: `tools/qbank_seed.py` adds every question this database has asked to a
student's bank (`--from-all`; never another student's resume lines), fetches what
is missing and writes the answers (`--write`, paced for the free tier), or takes
the seeded ones back out (`--remove`). A seeded question never claims an
interview: its page shows no "Asked" line.

## Why it looks the way it does

Looked up before designing (2026-11-18), as for Rovix's tour:

| Finding | Source | Decision |
|---|---|---|
| Prep guides that work are organised by category, with a contents page, so a reader can find a topic before an interview. | interview-prep guides, e.g. [Mock Interview Pro's layout guide](https://www.mockinterviewpro.com/interview-questions/layout-designer); [Grand Ave Housing's Q&A guide](https://grandavehousing.calpoly.edu/blog/ace-your-interview-questions-and-answers-pdf-guide-1764806873) | One **divider page per subject** in its own colour, listing its topics, then the questions grouped by topic. A **contents page** with page numbers. Every row and topic is a link, the PDF sidebar has a bookmark per subject and topic, and a **thumb tab** on the page edge finds a subject in print. |
| Recalling an answer before checking it (retrieval practice) beats rereading, as long as the correct answer follows as feedback. Short-answer recall beats recognition. | [CMU Eberly Center](https://www.cmu.edu/teaching/resources/instructionalstrategies/activelearningstrategies/retrievalpractice/index.html); [The Learning Scientists](https://www.learningscientists.org/faq); [retrievalpractice.org](https://retrievalpractice.org/strategies/2019/10/7/retrieval-guides) | **The question first, the answer under it.** The cover says how to use it: cover the answer, say yours, then check. |
| Cornell notes: a question as a cue beside the notes, and a summary to check against. | [Cornell system (IWU)](https://www.iwu.edu/advising/students/the-cornell-system.pdf); [MindTools](https://www.mindtools.com/axbdk4f/the-cornell-note-taking-system) | The question is the cue, in the gutter with its number. The item's key points are a **"Make sure you cover"** checklist to hold the spoken answer against. |
| Body text reads best at 45–75 characters a line, about 66 ideal (Bringhurst). | [UXPin on line length](https://www.uxpin.com/studio/blog/optimal-line-length-for-readability/); [CreativePro, TypeTalk](https://creativepro.com/?p=122949) | Answers run about 70 characters a line in Inter at 10.4/15.6 pt, on a tinted panel. Headings use Lora, the platform's own serif. |
| Questions students write for themselves teach less than questions from the material. | [Myers, Hausman and Rhodes, 2023](https://hausman.sites.ucsc.edu/files/2023/08/2023-99019-001.pdf) | The questions are the ones the interviewers actually asked, with the bank's answer key, never the student's own answer. |

Every answer says where it came from: **reviewed** (the bank's, checked by a
person), **practice** (the bank's draft, not yet reviewed), **written for your
bank** (a follow-up, or an item with no answer), or **how to answer** (only the
student knows the facts).

## Typefaces

Inter (OFL), Lora (OFL) and DejaVu Sans (Bitstream Vera licence, for the few
symbols Inter lacks, such as ∈ and ∪) are bundled in `fonts/` with their
licences. ReportLab draws the file in pure Python: no browser, GTK or LaTeX on
the server.
