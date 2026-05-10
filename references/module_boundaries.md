# Module Boundaries

Use this reference when auditing whether `循证出题官` follows the single-responsibility principle.

## Current Module Layout

`scripts/senior_exam_writer.py`

- Thin compatibility wrapper.
- Owns no business logic.
- Calls `senior_exam_writer_lib.cli.main()`.

`scripts/senior_exam_writer_lib/common.py`

- Owns shared constants, dataclasses, timestamps, and stable IDs.
- Does not read files, call models, query SQLite, or generate questions.

`scripts/senior_exam_writer_lib/store.py`

- Owns SQLite connection, pragmas, schema creation, and schema migration hooks.
- Does not parse documents, retrieve evidence, or generate items.

`scripts/senior_exam_writer_lib/parsing.py`

- Owns local file parsing for TXT, Markdown, DOCX, PDF, EPUB, JSON, and JSONL.
- Owns heading detection, section extraction, and chunking.
- Does not write SQLite rows or call embedding/generation models.

`scripts/senior_exam_writer_lib/dedup.py`

- Owns text normalization, chunk fingerprints, exact/near-duplicate detection, duplicate audit reports, and knowledge-point normalization.
- Does not parse documents, retrieve evidence, or generate questions.

`scripts/senior_exam_writer_lib/collection.py`

- Owns URL download, HTML metadata extraction, raw source saving, and JSONL normalization.
- Does not silently search the web by itself.
- Does not make source-quality judgments beyond preserving metadata.

`scripts/senior_exam_writer_lib/ingest.py`

- Owns source/chunk row insertion, FTS index updates, and optional embedding attachment.
- Receives parsed material from `parsing.py`.
- Does not decide whether evidence is sufficient for a question.

`scripts/senior_exam_writer_lib/retrieval.py`

- Owns query tokenization, FTS/BM25 retrieval, vector scoring, route hints, parent expansion, evidence ranking, and evidence JSON rendering.
- Does not generate question text.
- Does not approve weak evidence; it only returns candidates and metadata.

`scripts/senior_exam_writer_lib/generation.py`

- Owns prompt construction, JSON extraction, static verification, optional LLM verification, refusal records, and rewrite-on-fail.
- Does not retrieve new evidence during generation.
- Does not download sources.

`scripts/senior_exam_writer_lib/tasks.py`

- Owns exam-task records, task JSON loading, reviewer decisions, task status reports, prior generated-item context, and prior knowledge-point duplicate checks.
- Does not parse documents, insert evidence chunks, or call models.

`scripts/senior_exam_writer_lib/cli.py`

- Owns argparse commands and high-level orchestration.
- Wires modules together.
- Does not implement core parsing, retrieval, generation, or verification logic inline.

## Responsibility Boundaries

The pipeline has explicit handoffs:

1. Collection produces JSONL and raw files.
2. Parsing produces sections and chunks.
3. De-duplication blocks repeated chunks and records duplicate audit rows.
4. Ingestion stores unique sources/chunks and embeddings.
5. Retrieval produces evidence objects.
6. Task context supplies outline, source policy, proposition rules, requirements, coverage, and prior knowledge points.
7. Evidence gate approves or refuses generation.
8. Generation writes draft JSON from supplied evidence and task context only.
9. Verification accepts, rewrites, or refuses.
10. Reviewer decisions are recorded without overwriting the original generation record.
11. CLI stores the final audit trail.

No module after retrieval may invent or fetch additional facts. No module before verification may declare an item valid.

## Audit Sufficiency

The Skill is audit-ready when:

- every source has a path or URL;
- current-affairs sources have date/source metadata or are refused in strict mode;
- each evidence chunk has source kind, role, locator, and citation;
- duplicate chunks are blocked or explicitly allowed by operator choice and recorded when blocked;
- each item contains assertions, citations, evidence roles, knowledge points, coverage target, style profile, difficulty rationale, de-duplication check, and verification status;
- refused generations include missing evidence and strongest retrieved snippets;
- SQLite `exam_tasks`, `questions`, `question_reviews`, `chunk_fingerprints`, and `ingest_duplicates` preserve task, generation, review, and duplicate-control audit trails.

## Known Boundaries And Non-Goals

- The tool does not bypass paywalls, login walls, CAPTCHA, or robots restrictions.
- The tool does not guarantee PDF OCR; scanned PDFs need an OCR preprocessing step outside this Skill.
- The tool does not determine political truth from model memory.
- The tool does not make live web facts usable until they are collected, normalized, and ingested.
- The tool does not treat duplicated chunks as independent corroborating evidence.
- The tool does not replace human review for high-stakes exams.
- The tool does not guarantee that every generated distractor is pedagogically ideal; it enforces evidence support and records rationale for review.

## Current Audit Verdict

The core boundary is clear enough for local audited use:

- Evidence acquisition is separate from evidence storage.
- Evidence retrieval is separate from generation.
- Current-affairs material is role-labeled and freshness-gated.
- Style and difficulty must be justified per item.
- Verification can reject missing citations, missing style metadata, and unsupported claims.

Residual risks:

- PDF extraction quality depends on the PDF text layer.
- LLM verification quality depends on the local model.
- Source quality policy still depends on user/course-approved source lists.
- `collect-urls` downloads approved URLs but does not independently rank search results.
