---
name: senior-exam-writer
description: Build and use a local senior exam-writing agent that generates Chinese exam questions only from retrievable evidence. Use when Codex needs to create evidence-gated questions from books, course handouts, DOCX/PDF/Markdown/text materials, outlines, or current-affairs素材, with SQLite indexing, directory/TOC-driven hierarchical retrieval, local llama.cpp embeddings, local llama.cpp generation, citations, refusal on weak evidence, and post-generation verification to avoid hallucinations.
---

# 循证出题官

Use this skill to turn books, handouts, outlines, and current-affairs素材 into a local, evidence-gated question-writing workflow. The technical skill id remains `senior-exam-writer`; the user-facing name is `循证出题官`.

The central rule is: retrieve evidence first, generate second, verify last; refuse when the evidence is not enough.

## Workflow

1. Create a SQLite evidence database:

```bash
python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
```

2. Ingest source files. Prefer `--embed` with a local llama.cpp embedding server; use `--no-embed` only for BM25-only indexing or offline testing.

```bash
python scripts/senior_exam_writer.py ingest \
  --db ./exam_evidence.sqlite \
  --input ./materials \
  --kind book \
  --embed \
  --embed-url http://127.0.0.1:8081
```

3. Inspect retrieval before generating:

```bash
python scripts/senior_exam_writer.py retrieve \
  --db ./exam_evidence.sqlite \
  --query "新时代党的建设 总要求" \
  --top-k 8 \
  --embed-url http://127.0.0.1:8081
```

4. Generate questions locally with evidence gate and verification:

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
  --llm-verify
```

## Evidence Rules

- Treat TOC/目录 and overview/导论 chunks as routers, not as final proof unless the question only asks about structure.
- Use content chunks and their parent section context as final evidence.
- Require citations for stem, answer, analysis, and material excerpts.
- For current-affairs素材, prefer white-listed official or user-provided sources, and require source, date, URL or file locator, and review date.
- Refuse or ask for more material when evidence lacks a clear subject, time, policy wording, institution, or citation locator.
- After generation, verify every key assertion against cited evidence. Rewrite once if verification fails; otherwise return a refusal report.

Read [references/evidence_gate.md](references/evidence_gate.md) before changing gating, citation, or verification behavior.
Read [references/audit_workflow.md](references/audit_workflow.md) when explaining how PDF/DOCX materials are processed.
Read [references/question_rules.md](references/question_rules.md) when auditing item-writing rules, output schema, and rejection rules.
Read [references/llama_cpp.md](references/llama_cpp.md) when configuring local embedding or generation models.
Read [references/sqlite_schema.md](references/sqlite_schema.md) when inspecting or extending the database.

## Output Expectations

Return question packages as JSON by default. Keep rejected runs useful: include the missing evidence types, the strongest retrieved snippets, and what material the user should add.

Never invent dates, names, institutions, policies, page numbers, URLs, or citations. Do not "smooth over" missing support with generic knowledge.
