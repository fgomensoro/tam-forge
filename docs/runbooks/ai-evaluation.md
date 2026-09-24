# AI and memory evaluation

`tamforge_backend.evals` is a deterministic harness. It runs no live model. Every input
is a synthetic fixture in Git, hashed; every evaluator is versioned; every threshold is a
constant in code, not a judgment made while reading the output.

## What runs

| Part | Fixture | Threshold |
|---|---|---|
| memory retrieval | `memory-cases.json` | required recall ≥ 95%, top-k relevance ≥ 90%, zero leaks |
| security | `security-cases.json` | every door closed, zero disclosures |
| failure injection | code scenarios | every invariant holds across recording, jobs, storage |
| speech gates | `speech-gate-cases.json` | timing gate agrees with the expected verdict on every case |
| rubric agreement | `rubric-agreement-cases.json` | ≥ 85% of dimensions within one point of the adjudicated human score, quadratic weighted kappa ≥ 0.60 |
| agent role invariants | `agent-invariant-cases.json` | 100% exactly two strengths and two corrections, distinct, timestamped evidence, no prohibited answer, zero high-severity unsupported claims |
| reviewer refusals | `reviewer-refusal-cases.json` | 100% of cases end as expected against the pinned reviewer model: an uncommitted attempt refused before any call; scores above the maximum, dimensions outside the rubric, quarter points, a single correction and completion claims refused by the validator; rubric-bound half-point reviews accepted |
| debrief refusals | `debrief-refusal-cases.json` | 100% of cases end as expected against the pinned debrief model: a missing transcript or skill catalog refused before any call; invented quotes, skills outside the catalog, a single strength and plan-change claims refused by the validator; quoted, catalog-bound debriefs accepted |
| class analysis refusals | `class-analysis-refusal-cases.json` | 100% of cases end as expected against the pinned reviewer model: a missing transcript refused before any call; quarter points, invented examples, a comparison that contradicts the history and completion claims refused by the validator; half-point, quoted analyses accepted |
| weekly report refusals | `weekly-report-refusal-cases.json` | 100% of cases end as expected against the pinned report model: a missing skill catalog refused before any call; a skill missing or outside the catalog, no suggestion and claims of having applied a change refused by the validator; complete reports with proposals accepted |
| monthly report refusals | `monthly-report-refusal-cases.json` | 100% of cases end as expected against the pinned report model: a missing skill catalog refused before any call; a missing skill, gaps out of the ledger's order or outside the catalog, and claims of having applied a change refused by the validator; trajectories with the gaps in order accepted |
| practice review refusals | `practice-review-refusal-cases.json` | 100% of cases end as expected against the pinned reviewer model: an answer too short to review or a missing question refused before any call; a missing or extra dimension, quarter points, evidence or a heard quote that is not in the transcribed answer (including text lifted from the learner's own reference answer), more than three fixes and completion claims refused by the validator; half-point reviews that quote only the answer accepted |
| coach refusals | `coach-refusal-cases.json` | 100% of cases end as expected against the pinned coach model: blocks sealed to the coach (`none`, `planner`, `reviewer`, `analyst`, and an interviewer block outside the interview cycle such as the sealed final mock) refused before any call; completion claims, smuggled scores and plan changes refused by the validator; coached turns accepted, including interviewer blocks in the interview cycle and before-commit hints |

The report records provenance: the SHA-256 of every fixture, the evaluator versions, the
pinned speech model (filename and hash from `config/speech-models.yaml`), the rubric config
version and hash, and the prompt version. A newer model, prompt or rubric is promoted when
this report passes on the same fixtures, never because its prose reads better.

## Running

```bash
uv run pytest apps/backend/tests/evals -q
```

The private gold set (Frank's consented recordings) never enters this suite or CI; its
manifest tooling lives in `tamforge_backend.speech.evaluation.goldset` and its evaluation is
a manual, audited procedure on the protected host.
