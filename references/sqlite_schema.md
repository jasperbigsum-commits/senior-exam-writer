# SQLite Schema

The database is a local evidence store. It is intentionally simple enough to inspect with `sqlite3`.

## Tables

`sources`

- one row per ingested file or current-affairs item;
- stores title, path, kind, date, source, URL, version, and metadata JSON.

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

- stores generation runs, prompts, outputs, verification reports, and status.

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
