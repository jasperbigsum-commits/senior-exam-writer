---
name: senior-exam-writer
description: Build and use a local evidence-gated Chinese exam-question agent named 循证出题官. Use when Codex needs to ingest PDF/DOCX/Markdown/EPUB/text course materials, books, outlines, question banks, historical exam papers, knowledge Q&A, or current-affairs素材; build a SQLite evidence store; run TOC-driven retrieval; separate course evidence from background素材; use local llama.cpp embeddings/generation; require citations; review historical-question similarity; and refuse weak or uncited questions.
---

# 循证出题官

Use this skill for local, auditable Chinese exam-question generation from course materials and approved sources. The technical id is `senior-exam-writer`.

Core rule: evidence first, generation second, verification last. If evidence, citations, source policy, local model checks, historical similarity review, or human review are missing, fail closed instead of patching with model memory.

## Decision Map

- End-to-end task flow: read [references/task_workflow.md](references/task_workflow.md).
- PDF/DOCX/source audit details: read [references/audit_workflow.md](references/audit_workflow.md).
- Question-writing rejection rules: read [references/question_rules.md](references/question_rules.md).
- Style, cognitive level, and difficulty: read [references/style_difficulty.md](references/style_difficulty.md).
- Current-affairs/current-politics素材: read [references/current_affairs.md](references/current_affairs.md).
- Local llama.cpp setup: read [references/llama_cpp.md](references/llama_cpp.md).
- Grounding and citation gates: read [references/evidence_gate.md](references/evidence_gate.md).
- Module responsibility audit: read [references/module_boundaries.md](references/module_boundaries.md).
- SQLite tables and migrations: read [references/sqlite_schema.md](references/sqlite_schema.md).

## Command Graph

Run commands from the skill directory unless the user provides another path.

```bash
python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
python scripts/senior_exam_writer.py init-runtime --db ./exam_evidence.sqlite --embed-url http://127.0.0.1:8081 --llm-url http://127.0.0.1:8080
python scripts/senior_exam_writer.py split-requirements --requirements "..." --writer-count 3 --output-json ./prompt_package.json --output-jsonl ./prompt_stages.jsonl
python scripts/senior_exam_writer.py create-task --db ./exam_evidence.sqlite --name "exam task" --outline ./outline.json --source-policy ./source_policy.json --question-rules ./question_rules.json --requirements ./requirements.json --coverage ./coverage.json
python scripts/senior_exam_writer.py collect-urls --url https://example.gov/page --output-jsonl ./current_affairs.jsonl --out-dir ./collected_sources --db ./exam_evidence.sqlite --ingest --embed
python scripts/senior_exam_writer.py collect-exam-sources --input ./prior_exams --output-jsonl ./historical_exam.jsonl --out-dir ./historical_exam_sources --db ./exam_evidence.sqlite --ingest --embed
python scripts/senior_exam_writer.py ingest --db ./exam_evidence.sqlite --input ./materials --kind book --embed --embed-url http://127.0.0.1:8081
python scripts/senior_exam_writer.py audit-duplicates --db ./exam_evidence.sqlite --backfill
python scripts/senior_exam_writer.py plan-knowledge --db ./exam_evidence.sqlite --task-id TASK_ID
python scripts/senior_exam_writer.py plan-evidence --db ./exam_evidence.sqlite --task-id TASK_ID --embed-url http://127.0.0.1:8081
python scripts/senior_exam_writer.py generate-candidates --db ./exam_evidence.sqlite --planning-unit-id PLANNING_UNIT_ID --topic "topic" --writer-count 3
python scripts/senior_exam_writer.py audit-question-similarity --db ./exam_evidence.sqlite --planning-unit-id PLANNING_UNIT_ID --task-id TASK_ID --embed-url http://127.0.0.1:8081
python scripts/senior_exam_writer.py review-candidate --db ./exam_evidence.sqlite --candidate-id CANDIDATE_ID --decision evidence_gap --reason-code evidence_missing --notes "needs stronger citations"
python scripts/senior_exam_writer.py generate --db ./exam_evidence.sqlite --task-id TASK_ID --topic "topic" --question-type single_choice --count 5 --llm-url http://127.0.0.1:8080 --embed-url http://127.0.0.1:8081 --llm-verify
python scripts/senior_exam_writer.py audit-question-similarity --db ./exam_evidence.sqlite --question-id QUESTION_ID --embed-url http://127.0.0.1:8081
python scripts/senior_exam_writer.py review-question --db ./exam_evidence.sqlite --question-id QUESTION_ID --decision approved --reviewer "chief reviewer"
python scripts/senior_exam_writer.py task-status --db ./exam_evidence.sqlite --task-id TASK_ID
python scripts/senior_exam_writer.py complete-task --db ./exam_evidence.sqlite --task-id TASK_ID
```

## Operating Rules

- Use `split-requirements` when the user starts with a broad natural-language request; treat its output as stage prompts, not final facts.
- Store outline, source policy, proposition rules, requirements, and coverage in `exam_tasks`; do not leave core requirements only in chat.
- Use local loopback endpoints for embeddings and generation. Similarity review must use local embeddings.
- Download online sources into local reusable files or JSONL before ingestion. Do not paste large online materials into context when a file/cache can preserve them.
- Source kinds matter: `book`/`handout`/`notes` are core evidence; `syllabus`/`outline`/`exam_rules`/`requirements` are specifications; `question_bank`/`historical_exam` guide style and duplicate review only; `current_affairs` is dated background unless the task explicitly asks for current-affairs items; `qa` is supplemental.
- Knowledge planning and evidence planning may run in parallel after sources are indexed. Missing evidence routes to backfill; do not loop prompts to hide gaps.
- Multi-writer candidates are judged by reviewers against evidence, outline, and historical-similarity results. Failed candidates route to writer revision, replanning, or evidence backfill.
- Generated items must include citations, evidence roles, knowledge points, coverage target, style profile, difficulty rationale, type-specific fields, and verification status.
- Never invent dates, names, institutions, policy wording, URLs, page numbers, citations, or historical-exam similarity results.

## Output Contract

Return question packages as JSON by default. For refused runs, include missing evidence types, strongest retrieved snippets, and the material the user should add.

Keep code modular. `cli.py` orchestrates only; core responsibilities live in the modules documented in [references/module_boundaries.md](references/module_boundaries.md).
