---
name: senior-exam-writer
description: Build and use a local evidence-gated Chinese exam-question agent named 循证出题官. Use when Codex needs to ingest PDF/DOCX/Markdown/EPUB/text course materials, books, outlines, or current-affairs/current-politics素材; build a SQLite evidence store; perform TOC-driven hierarchical retrieval; separate core course evidence from background current-affairs evidence; use local llama.cpp embeddings and local generation; require citations; refuse weak evidence; and verify outputs for hallucination control.
---

# 循证出题官

Use this skill to turn books, handouts, outlines, and current-affairs/current-politics素材 into a local, evidence-gated question-writing workflow. The technical skill id remains `senior-exam-writer`; the user-facing name is `循证出题官`.

The central rule is: retrieve evidence first, generate second, verify last; refuse when the evidence is not enough.

## Decision Map

- Explain how PDF/DOCX materials are processed: read [references/audit_workflow.md](references/audit_workflow.md).
- Audit item-writing rules and rejection conditions: read [references/question_rules.md](references/question_rules.md).
- Add or review current-affairs/current-politics素材: read [references/current_affairs.md](references/current_affairs.md).
- Download and normalize user-approved URLs into JSONL evidence: use `collect-urls`.
- Change grounding, citation, or verification behavior: read [references/evidence_gate.md](references/evidence_gate.md).
- Configure local embedding/generation: read [references/llama_cpp.md](references/llama_cpp.md).
- Inspect or extend SQLite tables: read [references/sqlite_schema.md](references/sqlite_schema.md).

## Standard Workflow

1. Create a SQLite evidence database:

```bash
python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
```

2. Ingest course materials. Prefer `--embed` with a local llama.cpp embedding server; use `--no-embed` only for BM25-only indexing or offline testing.

```bash
python scripts/senior_exam_writer.py ingest \
  --db ./exam_evidence.sqlite \
  --input ./materials \
  --kind book \
  --embed \
  --embed-url http://127.0.0.1:8081
```

3. Ingest dated current-affairs or current-politics素材 when it is used as background or auxiliary material:

```bash
python scripts/senior_exam_writer.py ingest \
  --db ./exam_evidence.sqlite \
  --input ./current_affairs.jsonl \
  --kind current_affairs \
  --source-name "official/user-approved source" \
  --published-at 2026-05-10 \
  --embed \
  --embed-url http://127.0.0.1:8081
```

4. When URL sources are provided or discovered, collect them into an auditable JSONL before ingestion:

```bash
python scripts/senior_exam_writer.py collect-urls \
  --url https://example.gov/policy-page \
  --query "course topic + policy background" \
  --tag current_affairs \
  --output-jsonl ./current_affairs_collected.jsonl \
  --out-dir ./collected_sources \
  --db ./exam_evidence.sqlite \
  --ingest \
  --embed
```

5. Inspect retrieval before generating:

```bash
python scripts/senior_exam_writer.py retrieve \
  --db ./exam_evidence.sqlite \
  --query "新时代党的建设 总要求" \
  --top-k 8 \
  --embed-url http://127.0.0.1:8081
```

6. Generate questions locally with evidence gate and verification:

```bash
python scripts/senior_exam_writer.py generate \
  --db ./exam_evidence.sqlite \
  --topic "新时代党的建设 总要求" \
  --question-type single_choice \
  --count 5 \
  --difficulty medium \
  --llm-url http://127.0.0.1:8080 \
  --embed-url http://127.0.0.1:8081 \
  --min-evidence 3 \
  --strict-current \
  --llm-verify
```

## Evidence Rules

- Treat TOC/目录 and overview/导论 chunks as routers, not as final proof unless the question only asks about structure.
- Use content chunks and their parent section context as final evidence.
- Treat books, textbooks, handouts, and outlines as `core_course_evidence`.
- Treat current-affairs/current-politics素材 as `background_current_affairs` unless the requested item is explicitly a current-affairs item.
- Do not let current-affairs background alone determine the correct answer for a textbook/course concept.
- Require citations for stem, answer, analysis, and material excerpts.
- For current-affairs/current-politics素材, prefer white-listed official or user-provided sources, and require source, date, URL or file locator, and review date.
- Refuse or ask for more material when evidence lacks a clear subject, time, policy wording, institution, or citation locator.
- After generation, verify every key assertion against cited evidence. Rewrite once if verification fails; otherwise return a refusal report.

## Output Expectations

Return question packages as JSON by default. Keep rejected runs useful: include the missing evidence types, the strongest retrieved snippets, and what material the user should add.

Never invent dates, names, institutions, policies, page numbers, URLs, or citations. Do not "smooth over" missing support with generic knowledge.
