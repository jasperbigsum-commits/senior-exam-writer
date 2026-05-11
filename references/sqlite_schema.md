# SQLite Schema

The database is a local evidence store. It is intentionally simple enough to inspect with `sqlite3`.

## Tables

`sources`

- one row per ingested file or current-affairs item;
- stores title, path, kind, date, source, URL, version, and metadata JSON.
- supported kinds include `book`, `handout`, `outline`, `syllabus`, `exam_rules`, `question_bank`, `historical_exam`, `qa`, `requirements`, `current_affairs`, and `notes`.
- a source may have zero chunks when all of its candidate chunks were blocked as duplicates; this preserves provenance without polluting retrieval.

`chunks`

- one row per overview, TOC, parent section, or child content chunk;
- `layer` is one of `overview`, `toc`, `parent`, or `content`;
- `parent_id` links child content chunks to larger parent section context;
- `path` stores the chapter/section route;
- `text` stores the retrievable content;
- `embedding_json` stores local llama.cpp embedding vectors when available.

`questions`

- stores generation runs, prompts, evidence, outputs, verification reports, status, and optional `task_id`.

`exam_tasks`

- stores the exam outline, source policy, proposition rules, other requirements, coverage plan, status, and timestamps.

`question_reviews`

- stores human reviewer decisions: `approved`, `revise`, or `rejected`, plus reviewer notes and optional patch JSON.
- the CLI blocks approval unless the stored question run is `ok`, output status is `ok`, and verification passed.

`chunk_fingerprints`

- stores normalized text fingerprints for ingested chunks.
- supports exact and near-duplicate blocking before chunks enter retrieval.

`ingest_duplicates`

- stores blocked duplicate candidates with duplicate target, layer, path, similarity, reason, and sample text.
- keeps duplicate-source evidence auditable without polluting FTS/vector retrieval.
- duplicate reasons include `exact_normalized_text`, `near_duplicate_ngrams`, and, when embeddings are enabled, `semantic_embedding`.

`planning_units`

- stores coverage-derived planning units for batched knowledge and evidence planning.
- includes question type, difficulty, knowledge/evidence status, writer round, and review status.

`evidence_points`

- stores knowledge-point to evidence-id bindings for each planning unit.
- supports evidence gap routing before candidate generation.

`candidate_questions`

- stores multi-writer candidate prompts and outputs.
- includes `writer_id`, `round`, `prompt_json`, `output_json`, and `verification_json` for auditability.
- omits legacy duplicate payload fields; `prompt_json`, `output_json`, and `verification_json` are the single source of truth.

`candidate_reviews`

- stores reviewer routing decisions for candidates.
- decisions include `approved_candidate`, `revise_candidate`, `replan_required`, `evidence_gap`, and `rejected_candidate`.
- stores routing data in `review_json`; candidate reviews do not carry a separate patch payload.

`question_similarity_audits`

- stores local embedding duplicate-review audits for candidates or final questions.
- `candidate_question_id` may be null when the audit targets `question_id`.
- `blocked_duplicate` and `revise_required` block approval.
- uses `created_at`, `threshold_policy_json`, and `audit_summary_json` as the canonical audit fields.

`question_similarity_hits`

- stores top historical/prior-question hits for each similarity audit.
- comparison sources are `historical_exam` and `question_bank`, not factual answer support.
- uses `similarity_score`, `match_reason`, and `snippet` for hit details.

## Retrieval Pattern

1. Embed the query with the same local embedding model used during ingestion.
2. Rank chunks by vector similarity against `chunks.embedding_json`.
3. Expand child chunks to parent chunks for generation context.
4. Refuse retrieval if the query embedding endpoint or stored chunk vectors are missing.

## Maintenance

Use `vacuum` after large deletions:

```bash
uv run python scripts/senior_exam_writer.py vacuum --db ./exam_evidence.sqlite
```

Use `audit-duplicates --backfill` when opening an older database that predates chunk fingerprints:

```bash
uv run python scripts/senior_exam_writer.py audit-duplicates --db ./exam_evidence.sqlite --backfill
```

Generation is blocked when chunks lack fingerprints or exact duplicate fingerprint groups remain.

