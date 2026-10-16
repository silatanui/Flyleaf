# AI Writing Detector — Product Plan

A practical plan for a Turnitin-style integrity tool: document similarity plus an AI-writing likelihood score, built as a review aid for teachers and editors.

This document is a plan only. No detector code is included yet.

## 1. Is this possible?

**Yes, as a useful product. No, as a perfect detector.**

Two different problems sit under the name “Turnitin”:

| Capability | What it does | Feasibility | Certainty |
| --- | --- | --- | --- |
| Similarity / plagiarism | Finds overlapping passages against a corpus and the web | Well understood and buildable | High for near-copies; medium for heavy paraphrase |
| AI-writing detection | Estimates how likely a passage was produced by a language model | Buildable as a probability score | Low as proof. Scores drift as models change |

Companies already ship both: Turnitin, GPTZero, Originality.ai, Copyleaks, Winston AI. The category is real.

What is not realistic:

- A score that proves a person used ChatGPT. OpenAI shut down its own public AI classifier in 2023 because the error rate was too high. Turnitin itself tells institutions the AI percentage is not a finding of misconduct.
- Matching Turnitin’s closed archive of decades of student papers, journals, and LMS integrations in a first version. That archive is the hard part of classic Turnitin, not the highlighting UI.
- A detector that stays accurate after light human editing, translation, or a newer model. Attackers and students adapt faster than a fixed model.

What is realistic for this project:

- Upload or paste a document.
- Highlight sentences that look statistically unlike typical human writing, with a calibrated probability.
- Show overlapping passages against papers already submitted to this system, and optionally against the public web.
- Compare a new submission to the same author’s earlier writing.
- Present the result as “review this” with a confidence band, a minimum length, and a written disclaimer.

The honest product promise: **a second pair of eyes, not a verdict.**

## 2. What “like Turnitin” should mean here

Turnitin’s report has a shape worth copying, and a claim worth refusing.

Copy:

- Whole-document percentage plus passage-level highlights.
- Sources listed next to each match.
- A teacher view: assignment, student, submission time, downloadable report.
- A floor on length. Turnitin’s AI indicator is unreliable under a few hundred words; this product should refuse to score documents under about 300 words.
- Separation of quoted material, bibliographies, and headings so they do not inflate either score.

Refuse:

- Auto-fail, auto-plagiarism flags, or any UI that says “this student cheated.”
- A single number with no sentence evidence.
- Equal confidence on a 80-word paragraph and a 2,000-word essay.

Suggested report fields:

1. Similarity: percent of the document that matches known sources, with each source and the matched span.
2. AI writing indicator: percent of eligible sentences above the review threshold, plus a document-level probability and a confidence label (`low`, `moderate`, `high`).
3. Mixed-document map: a bar showing human-like, uncertain, and AI-like spans so a rewritten introduction does not paint the whole essay.
4. Author baseline, when prior work exists: “this submission is stylistically far from this person’s last three papers.”
5. Plain-language disclaimer on every report.

## 3. How detection actually works

No method reads the author’s mind. Each method measures a proxy.

### 3.1 Predictability (perplexity and burstiness)

Language models assign a probability to each next token. AI prose is often smoother: lower average perplexity, and less variation from sentence to sentence (“burstiness”). Human prose spikes — a short blunt sentence, then a long tangled one.

DetectGPT and Fast-DetectGPT push this further: they perturb the text and see whether the original sits in a probability valley that is typical of model samples. Binoculars (2024) compares two models’ views of the same text and is stronger than older RoBERTa “ChatGPT detectors,” which collapsed once people paraphrased.

Practical constraint: you almost never have the logprobs from the model that wrote the text (ChatGPT, Claude, Gemini do not give them to you). You score with an open proxy model (for example Llama or a smaller instruction model). The proxy is correlated with the original generator, not identical. That correlation is why scores are probabilistic.

### 3.2 Supervised classifier

Train or fine-tune a text classifier (DeBERTa or a similar encoder) on pairs labeled human vs AI, at sentence and document level. Output a probability per sentence.

This is fast at inference time and easy to highlight in a UI. It overfits the models it was trained on. A classifier trained on GPT-3.5 essays misses a lot of GPT-4o, Claude, or Gemini text, and it false-flags formulaic human writing (lab reports, legal style, non-native English).

Use it as one vote in an ensemble, and retrain when a new model family becomes common.

### 3.3 Ensemble

A document score should not be one model’s softmax. Combine:

- Proxy-model perplexity and burstiness (Fast-DetectGPT or Binoculars-style score).
- Supervised sentence classifier.
- Simple surface cues that are weak alone but useful in combination: uniformity of sentence length, rarity of typos, hedge-word rate. Never ship these alone; they are easy to fake and biased.

Calibrate the ensemble on a held-out set so “70%” means roughly 70 in 100 similar documents were AI-written in your test set — not an arbitrary slider.

### 3.4 Watermarks

Some providers experiment with statistical watermarks or metadata. A third-party tool cannot rely on this. Most student-facing chatbots do not expose a watermark you can verify. Treat watermark checks as optional and model-specific, never as the core detector.

### 3.5 Authorship baseline (the most defensible extra signal)

If the institution already has two or more genuine writing samples from the same person, compare the new submission to that baseline: function-word rates, sentence-length distribution, and embedding distance.

A generic AI score says “this looks like model text.” An authorship shift says “this does not look like this person’s other work.” Teachers already reason this way. It still is not proof — people change style, get editing help, or write in a new genre — but it reduces the damage of a context-free detector.

### 3.6 Similarity, separate from AI detection

Classic plagiarism detection does not ask who wrote the words. It asks where the words already appear.

- Exact and near-exact: shingles (overlapping word n-grams), winnowing fingerprints, MinHash, stored per submission.
- Paraphrase: sentence embeddings (a small open embedding model) with a high similarity threshold, shown as “possible paraphrase,” not as a copied quote.
- Corpus layers, in order of what you can actually obtain:
  1. This product’s own past submissions (the only corpus you fully control).
  2. Teacher-provided course materials and assignment prompts (exclude the prompt itself from the score).
  3. Public web, via a search API or a limited crawl of pages you are allowed to store. Do not pretend this is Turnitin’s private paper archive.
  4. Open scholarly metadata where the license allows it. Full-text journal databases are licensed; scraping them is not the plan.

Quotes and bibliography sections should be detected and excluded or down-weighted, the way Turnitin’s filters do.

## 4. Product boundaries (decide these before writing code)

1. **Audience.** Start with one: a teacher reviewing class submissions, or a writer checking their own draft. Institutional LMS integration (Moodle, Canvas) is a later phase. The first version is a web app with accounts, classes, and file upload.
2. **Languages.** Ship English first. AI detectors and perplexity models are much weaker in other languages, and a Swahili or multilingual claim needs its own labeled set. Do not show an English model’s score on text it was not evaluated on; detect language and refuse or label “not supported.”
3. **Decision policy.** The score never changes a grade by itself. The UI copy is “flagged for human review.”
4. **Length policy.** Under 300 words: no AI score, similarity only if there is a match. Show why.
5. **Privacy.** Student essays are sensitive. Default retention, who can see a report, and deletion must be explicit. Prefer processing on your own server over sending full essays to a third-party detector API. If a hosted model API is used, name it in the privacy note.
6. **Adversarial expectation.** Assume some users will paraphrase, translate to another language and back, or ask a model to “write with typos and uneven rhythm.” Measure this. Publish the failure modes inside the app, not only in a blog post.

## 5. Proposed architecture

Keep the web app and the model runtime separate so a slow model does not block uploads.

```
Browser
  → Web app (accounts, classes, uploads, reports)
  → Queue (one job per submission)
  → Worker
       1. Extract text from docx / pdf / txt / paste
       2. Segment sentences; strip quotes, headings, references
       3. Similarity index lookup
       4. AI ensemble (sentence scores + document score)
       5. Optional authorship comparison
  → Report stored in the database
  → Teacher opens the report
```

Suggested stack, given a Windows / XAMPP machine and a Python-friendly ML ecosystem:

- **API and web:** Python, FastAPI, server-rendered pages or a small frontend. Python is the practical choice because the models live there. XAMPP can reverse-proxy to it later; the detector should not be implemented as PHP calling a notebook by hand.
- **Database:** PostgreSQL when you want concurrent classes; SQLite is acceptable for a single-school prototype.
- **Queue:** a database-backed job table is enough at prototype scale. Move to Redis or a proper queue only when jobs pile up.
- **Models, local if the machine allows:**
  - Sentence segmentation: a normal NLP splitter, with extra rules for headings and citations.
  - Embeddings for paraphrase: a small open embedding model.
  - AI score: Fast-DetectGPT or Binoculars using an open instruct model you can run locally, plus one fine-tuned encoder if you have labels.
- **Object storage:** original files on disk under this project, not only extracted text. Keep the original so a teacher can see formatting the extractor dropped.

Minimum hardware for a local open model: a machine with a GPU makes interactive scoring pleasant. CPU scoring is acceptable if jobs are queued and the teacher does not wait on the upload request. Cloud GPU is a hosting choice, not a requirement for the design.

## 6. Data you must collect before trusting a score

A detector without a test set is a random number generator with a progress bar.

Build three evaluation sets and keep them frozen:

| Set | Contents | Purpose |
| --- | --- | --- |
| Human | Real essays you have rights to use: timed classwork, older pre-2022 writing, published prose with a known human author | Measure false positives |
| AI | Same prompts, generated by several current models, more than one temperature and style instruction | Measure false negatives |
| Evasion | AI text that was paraphrased, shortened, translated round-trip, or edited by a person for 5–10 minutes | Measure the gap you must disclose |

Also hold out:

- Non-native English writing. This is where detectors hurt people. If the false-positive rate here is unacceptable, do not ship the score for that group without a warning and a higher threshold.
- Formulaic genres: lab reports, recipes, code comments, CVs. Many should be out of scope.

Target to publish internally before launch, not as marketing:

- False positive rate on the human set at the chosen threshold.
- False negative rate on raw AI and on the evasion set.
- The threshold where you would rather miss AI text than accuse a human. For a school tool, prefer that tradeoff.

Retrain or recalibrate when you add a model family to the AI set and the false-negative rate jumps.

Public datasets (HC3, RAID, M4, and similar) are useful to bootstrap. They are not a substitute for text that looks like your users’ assignments, and many are contaminated or tied to old models.

## 7. Build phases

### Phase 0 — Feasibility spike (about 1 week)

Goal: learn the error rate on your own samples before building accounts or file upload.

- Pick one open method (Fast-DetectGPT or Binoculars) and one small open model you can run.
- Score 50 human and 50 AI passages you create from the same prompts.
- Record false positives and false negatives in a spreadsheet.
- Decision gate: if untouched AI text is not separable from human text at a threshold you would actually use, stop and narrow the product to similarity checking only. Similarity is still worth building. A bad AI score is not.

### Phase 1 — Single-user checker

- Paste text and upload `.txt`, `.docx`, and text-based `.pdf`.
- Sentence highlights, document probability, confidence label, word count, disclaimer.
- No score under 300 words.
- Language detection; unsupported languages get a clear refusal.
- Store nothing by default, or store only after the user opts in.

### Phase 2 — Similarity against your own corpus

- Accounts.
- Fingerprint every opted-in submission.
- Report exact and near-exact overlaps inside the corpus.
- Exclude assignment-prompt boilerplate supplied by the teacher.
- Side-by-side view: source passage and submitted passage.

### Phase 3 — Class workflow

- Teacher, class, assignment, due date.
- Student submit link.
- Report list with similarity and AI indicator as sortable columns, default sort not “highest AI.”
- Teacher note on each report (“reviewed, student explained editing help”) so the score is not the record of record.
- PDF export of the report including the disclaimer.

### Phase 4 — Stronger AI ensemble and authorship

- Add the second model vote and calibrate.
- Optional prior-work baseline per student.
- Evasion set rerun. Write the measured miss rate into the report footer (“paraphrased AI text is often missed”).
- Web matches via a search API for short distinctive phrases only, with caching and a rate limit. Show the URL and the snippet.

### Phase 5 — Only if a school asks

- Moodle or Canvas submission plugin.
- Admin retention controls and deletion.
- Audit log of who opened a report.
- Per-institution threshold settings, still unable to auto-apply a grade.

## 8. Report UX (the part users judge)

A teacher should understand the screen in under a minute.

- Left: the essay with three highlight colors — matched source, AI-like, uncertain. Hover shows the sentence probability and, for similarity, the source.
- Right: two gauges, similarity and AI indicator, each with a one-sentence explanation of what the number is.
- Below: source list; model and date of the scoring run (“scored 16 Oct 2026 with model set X”); disclaimer; link to “what this misses.”
- Empty and error states: scanned PDF with no text layer, file too large, unsupported language, too short, job still running.

Do not use red “guilty” styling. Use neutral review language.

## 9. Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| False accusation | A wrong AI flag can affect a grade or a job | Human review only; high threshold; show sentences; appeal note field |
| Bias against non-native writers | More uniform or formal learner English is often scored as AI | Separate evaluation; warning; higher threshold or no score |
| Model drift | Next year’s chatbot fools this year’s classifier | Dated model card; frozen test set; scheduled re-eval |
| Over-trust | A percentage looks like forensic evidence | Disclaimer on every screen and export |
| Privacy | Essays reveal identity, health, family | Local processing, retention limit, access control |
| Corpus licensing | Copying the web or journals into your index can violate copyright | Store fingerprints and short snippets where the law allows; link out to public URLs |
| Scope creep toward surveillance | “Detect AI” becomes “monitor all writing” | No keystroke logging, no covert browser extension, no scanning a machine without an explicit upload |

## 10. What to build first, in this folder

When implementation starts, Phase 0 is the whole first milestone:

1. A small Python project layout (`app/`, `tests/`, `data/samples/`).
2. A script that scores pasted text with one open detector and prints sentence scores.
3. A checked-in sample set description (not necessarily the essays, if you do not have rights) and a results table.
4. A go / no-go note based on that table.

Only after that gate: FastAPI upload page, queue, and the report screen from Phase 1.

## 11. Success criteria for a version you can show someone

- A teacher can upload a `.docx` and, within a minute on your hardware, see highlights and two separate scores.
- Documents under 300 words and non-English documents do not receive an AI percentage.
- On your frozen test set, the chosen threshold’s false-positive rate on genuine human essays is measured and written on the about page.
- Paraphrase evasion is measured and disclosed, even if the number is unflattering.
- Nothing in the interface says the author cheated.

## 12. Bottom line

Build the similarity checker expecting it to work. Build the AI indicator expecting it to be a fallible triage signal that must be recalibrated. Ship both only with the evaluation numbers visible. That is the honest version of “an AI detector like Turnitin,” and it is a project a small team can start in this folder.
