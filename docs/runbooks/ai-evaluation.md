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
