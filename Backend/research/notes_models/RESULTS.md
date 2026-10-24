# Which model writes the notes — measured 2026-10-24

`compare.py` sends the notes writer's own prompt (`notes_writer.SYSTEM`,
`notes_writer.brief`) to each candidate, then scores every answer with the
module's own gate (`notes_writer.check`). Raw rows are in `results.json`.

**Cases (12):**

- **8 real questions** from two live sessions (C: Q1–4, E: Q2–5): two incorrect, one correct after a push, two vague and three partial.
- **4 written ones** on the same question: correct, surface-level, wrong ("the keys are kept sorted, so you binary search") and blank ("I don't know").

## Result

| Model (provider) | Passed the checks | Latency p50 / max | Notes |
|---|---|---|---|
| `openai/gpt-oss-120b` (Groq) | 12 / 12 | 2.0 s / 3.6 s | Correct and grounded. Next steps often generic ("Study how hash functions map keys…"); restates the misconception as "You said …" |
| `minimaxai/minimax-m3.1-flash` (NIM) | 12 / 12 | 12 s / 23 s | Correct and grounded. Next steps concrete ("Redraw the lookup path: key → hash function → bucket index"); states the misconception as a belief; noticed the push-back in C.Q2 |
| `nvidia/nemotron-3-ultra-550b-a55b` (NIM) | 0 / 5 strict schema; 2 / 2 with `json_object` + `/no_think` | 30–50 s | Degenerate whitespace under strict `json_schema` |
| `nvidia/nemotron-3.5-lightning-30b-a3b` (NIM) | 0 / 10 | ~30 s | Empty content: all 3,000 tokens spent reasoning, even with `/no_think` |

**Not usable from this account on 2026-10-24:**

- **Listed by `/models` but answered `404 Function not found`:** nemotron-3-super-120b, kimi-k2.6, mistral-large-2, llama-3.1-nemotron-ultra/70b/51b, nemotron-4-340b, jamba, yi-large, palmyra, nemotron-nano-3-30b, phi-3.5-moe.
- **Hung until timeout:** glm-5.3, glm-5.3-flash, deepseek-v4.1-flash, gemma-4-31b-it, step-5-preview.

## Decision

- **Writing tier (`ai_core.models`, v0.40.0): minimax-m3.1-flash on NIM.**
  - Both finalists passed every check, so quality decided it.
  - The notes are written after the session, off every request path, so 12 s per question costs the student nothing they wait on.
  - It also takes the notes off Groq's 200K-tokens-per-day budget, which the live interview needs.
- **Fallback: gpt-oss-120b on Groq,** through M06's generation-tier job. Measured live:
  - an invalid NIM key (403) fell back within the same second;
  - NIM's 429 on the tenth call in two minutes also fell back.
  - After one such failure, the rest of the run skips NIM (`notes_writer._generate`).
- **Live (session C):** 4 write-ups in 45–50 s, 6–17 s each, no checker problems, one attempt each.

## Re-running

```
cd Backend
.venv/Scripts/python.exe research/notes_models/compare.py
```

Needs `GROQ_API_KEYS` (one key; pooling organisations is against Groq's AUP) and `NVIDIA_API_KEY`, both from the gitignored `keys.txt`. Groq calls are paced at 12 s for its 8K tokens-per-minute limit.
