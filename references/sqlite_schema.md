# SQLite Schema

The database is a local evidence store. It is intentionally simple enough to inspect with `sqlite3`.

## Tables

`sources`

- one row per ingested file or current-affairs item;
- stores title, path, kind, date, source, URL, version, and metadata JSON.
- supported kinds include `book`, `handout`, `outline`, `syllabus`, `exam_rules`, `question_bank`, `qa`, `requirements`, `current_affairs`, and `notes`.
- a source may have zero chunks when all of its candidate chunks were blocked as duplicates; this preserves provenance without polluting retrieval.

`chunks`

- one row per overview, TOC, parent section, or child content chunk;
- `layer` is one of `overview`, `toc`, `parent`, or `content`;
- `parent_id` links child content chunks to larger parent section context;
- `path` stores the chapter/section route;
- `text` stores the retrievable content;
- `embedding_json` stores local llama.cpp embedding vectors when available.

`chunks_fts`

- SQLite FTS5 index for keyword/BM25 retrieval.

`questions`

- stores generation runs, prompts, evidence, outputs, verification reports, status, and optional `task_id`.

`exam_tasks`

- stores the exam outline, source policy, proposition rules, other requirements, coverage plan, status, and timestamps.

`question_reviews`

- stores human reviewer decisions: `approved`, `revise`, or `rejected`, plus reviewer notes and optional patch JSON.

`chunk_fingerprints`

- stores normalized text fingerprints for ingested chunks.
- supports exact and near-duplicate blocking before chunks enter retrieval.

`ingest_duplicates`

- stores blocked duplicate candidates with duplicate target, layer, path, similarity, reason, and sample text.
- keeps duplicate-source evidence auditable without polluting FTS/vector retrieval.
- duplicate reasons include `exact_normalized_text`, `near_duplicate_ngrams`, and, when embeddings are enabled, `semantic_embedding`.

## Retrieval Pattern

1. Search overview and TOC chunks to route to likely chapter paths.
2. Search content chunks with BM25 and vectors.
3. Expand child chunks to parent chunks for generation context.
4. Rank by combined keyword, vector, and route scores.

## Maintenance

Use `vacuum` after large deletions:

```bash
python scripts/senior_exam_writer.py vacuum --db ./exam_evidence.sqlite
```

Use `audit-duplicates --backfill` when opening an older database that predates chunk fingerprints:

```bash
python scripts/senior_exam_writer.py audit-duplicates --db ./exam_evidence.sqlite --backfill
```
