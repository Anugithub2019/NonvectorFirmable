# Labels

`links_sample.jsonl` — 88 links sampled from `outputs/links.jsonl`, stratified by
match_type x source, labelled by two models that did not produce the links:

- **Gemini 3.1 Pro** (free-text verdict + reason), model `gemini-3.1-pro-preview` — independent: it played no
  part in making the links.
- **TypeSafe Jev 1.14** (decision model; P(same) with 0.7 / 0.3 cut-offs), model `typesafe/jev-1.14` — NOT
  independent for `name_semantic` links, which Jev itself scored (blind presentation removes the
  system's decision, not the model's own tendencies). `evaluation.md` therefore also reports
  Pro-only precision.

Both saw only the two records' attributes (`shown_to_labellers`). For name-path links the
identifiers were removed so the labellers judged the same evidence the semantic path had.
They were never shown the system's score, match type or evidence.

Consensus: 82/88 links where both labellers agreed on same/different. Disagreements
and 'cannot_tell' are reported as **unresolved** and never counted as correct.

These are model labels, not human labels. The write-up says so. Re-label any row by hand by
editing `human_verdict` into it; `evaluation.py` prefers a human verdict when present.
