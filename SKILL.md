---
name: senior-exam-writer
description: Build and use a local evidence-gated Chinese exam-question agent named 循证出题官. Use when Codex needs to ingest PDF/DOCX/Markdown/EPUB/text course materials, books, outlines, question banks, historical exam papers, knowledge Q&A, or current-affairs materials; build a SQLite evidence store; run local vector retrieval; separate course evidence from background materials; use local llama.cpp embeddings; require citations; review historical-question similarity; and refuse weak or uncited questions.
---

# 循证出题官
Use this skill for local, auditable Chinese exam-question generation from course materials and approved sources. The technical id is `senior-exam-writer`.

Core rule: evidence first, generation second, verification last. If evidence, citations, source policy, local model checks, historical similarity review, or human review are missing, fail closed instead of patching with model memory.

## Decision Map

- Local knowledge map: read [llms.txt](llms.txt) first when deciding which reference file to load.
- End-to-end task flow: read [references/task_workflow.md](references/task_workflow.md).
- Acceptance testing and scenario evaluation: read [references/acceptance_checklist.md](references/acceptance_checklist.md).
- PDF/DOCX/source audit details: read [references/audit_workflow.md](references/audit_workflow.md).
- Question-writing rejection rules: read [references/question_rules.md](references/question_rules.md).
- Style, cognitive level, and difficulty: read [references/style_difficulty.md](references/style_difficulty.md).
- Current-affairs/current-politics 素材: read [references/current_affairs.md](references/current_affairs.md).
- Local llama.cpp setup: read [references/llama_cpp.md](references/llama_cpp.md).
- LlamaIndex/sqlite-vec local RAG and optional CLI/MCP retrieval: read [references/llamaindex_mcp.md](references/llamaindex_mcp.md).
- Grounding and citation gates: read [references/evidence_gate.md](references/evidence_gate.md).
- Module responsibility audit: read [references/module_boundaries.md](references/module_boundaries.md).
- SQLite tables and migrations: read [references/sqlite_schema.md](references/sqlite_schema.md).

## Command Graph

Run Python commands from the skill directory with `uv run` unless the user provides another environment. If `uv` is not installed, install/fix `uv` first instead of falling back to an untracked global Python environment.

Prefer JSON files for `--outline`, `--source-policy`, `--question-rules`, `--requirements`, `--coverage`, and `--patch`. Inline JSON is accepted for quick tests, but files avoid PowerShell/CMD/Bash escaping differences and are safer for Chinese text, quotes, parentheses, and long policies. UTF-8 with or without BOM is supported.

Preferred managed batch path:

```bash
uv run python scripts/run_batch.py --requirements "..." --input ./materials --output-dir ./exam_run --db ./exam_evidence.sqlite
uv run python scripts/run_batch.py --prepare-only --requirements "..." --input ./materials --output-dir ./prepared_pipeline --db ./exam_evidence.sqlite
```

The first command resolves or downloads a ModelScope embedding GGUF, starts a temporary `llama-server` on `127.0.0.1` with an auto-selected local port, probes Chinese embeddings, initializes SQLite, ingests sources with embeddings, runs duplicate audit, and stops the temporary server. It should not require opening firewall/router ports because the server is loopback-only.

Advanced manual path, only when a reusable local embedding endpoint is already healthy:

```bash
uv run python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
uv run python scripts/init_modelscope_runtime.py
uv run python scripts/senior_exam_writer.py init-runtime --db ./exam_evidence.sqlite --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py prepare-pipeline --requirements "..." --input ./materials --output-dir ./prepared_pipeline --db ./exam_evidence.sqlite
uv run python scripts/senior_exam_writer.py split-requirements --requirements "..." --writer-count 3 --output-json ./prompt_package.json --output-jsonl ./prompt_stages.jsonl
uv run python scripts/senior_exam_writer.py create-task --db ./exam_evidence.sqlite --name "exam task" --outline ./outline.json --source-policy ./source_policy.json --question-rules ./question_rules.json --requirements ./requirements.json --coverage ./coverage.json
uv run python scripts/senior_exam_writer.py collect-urls --url https://example.gov/page --output-jsonl ./current_affairs.jsonl --out-dir ./collected_sources --db ./exam_evidence.sqlite --ingest
uv run python scripts/senior_exam_writer.py collect-exam-sources --input ./prior_exams --output-jsonl ./historical_exam.jsonl --out-dir ./historical_exam_sources --db ./exam_evidence.sqlite --ingest
uv run python scripts/senior_exam_writer.py ingest --db ./exam_evidence.sqlite --input ./materials --kind book --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py audit-duplicates --db ./exam_evidence.sqlite --backfill
uv run python scripts/senior_exam_writer.py plan-knowledge --db ./exam_evidence.sqlite --task-id TASK_ID
uv run python scripts/senior_exam_writer.py plan-evidence --db ./exam_evidence.sqlite --task-id TASK_ID --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py generate-candidates --db ./exam_evidence.sqlite --planning-unit-id PLANNING_UNIT_ID --topic "topic" --writer-count 3 --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py audit-question-similarity --db ./exam_evidence.sqlite --planning-unit-id PLANNING_UNIT_ID --task-id TASK_ID --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py review-candidate --db ./exam_evidence.sqlite --candidate-id CANDIDATE_ID --decision evidence_gap --reason-code evidence_missing --notes "needs stronger citations"
uv run python scripts/senior_exam_writer.py audit-question-similarity --db ./exam_evidence.sqlite --question-id QUESTION_ID --embed-url <LOCAL_EMBED_URL>
uv run python scripts/senior_exam_writer.py review-question --db ./exam_evidence.sqlite --question-id QUESTION_ID --decision approved --reviewer "chief reviewer"
uv run python scripts/senior_exam_writer.py task-status --db ./exam_evidence.sqlite --task-id TASK_ID
uv run python scripts/senior_exam_writer.py complete-task --db ./exam_evidence.sqlite --task-id TASK_ID
```

Strict local RAG path for source-file retrieval, after the local embedding endpoint is healthy:

```bash
uv sync --extra rag --extra test
uv run python scripts/llamaindex_sqlite_vec_rag.py index --db ./local_rag.sqlite --input ./materials --embed-url http://127.0.0.1:8081 --embed-model local-embedding --reset
uv run python scripts/llamaindex_sqlite_vec_rag.py query --db ./local_rag.sqlite --query "检索知识点证据" --knowledge-point "知识点" --embed-url http://127.0.0.1:8081 --embed-model local-embedding
```

This RAG path is not FTS-only: LlamaIndex must load and split files, local llama.cpp embeddings must create vectors, `sqlite-vec` must store vectors, and FTS5 is only the lexical side of hybrid recall and source locator matching.

The `generate` command is the legacy script-driven local-LLM path. Prefer Codex/agent writing from `generate-candidates` prompt records and retrieved evidence unless the user explicitly wants offline local-only generation.

Optional legacy local-LLM path:

```bash
uv run python scripts/senior_exam_writer.py generate --db ./exam_evidence.sqlite --task-id TASK_ID --topic "topic" --question-type single_choice --count 5 --embed-url <LOCAL_EMBED_URL> --llm-url http://127.0.0.1:YOUR_LOCAL_LLM_PORT
```

## Operating Rules

- Use `split-requirements` when the user starts with a broad natural-language request; treat its output as stage prompts, not final facts.
- Prefer `scripts/run_batch.py` for first-run and batch workflows. It uses `uv`, manages a temporary loopback-only embedding server, auto-picks a free local port, and should not require extra firewall or router port opening.
- Use `prepare-pipeline` when embedding is not deployed yet and the user wants batch processing. It may parse local files, build prompt packages, inspect source health, and emit next-step commands, but it must not create evidence claims, vectors, similarity scores, or approved questions.
- Use `llms.txt` as the local file map for this skill. Load only the linked reference needed for the current step; do not build or maintain a separate vector index for the skill's own documentation.
- Store outline, source policy, proposition rules, requirements, and coverage in `exam_tasks`; do not leave core requirements only in chat.
- Use a local loopback endpoint for embeddings. `init-runtime` must pass an actual Chinese embedding request before ingestion, planning, candidates, retrieval, or review.
- Prefer ModelScope as the default model source in China-facing environments. Use a Chinese-friendly llama.cpp embedding GGUF, such as Qwen3-Embedding GGUF from ModelScope, and do not use a general chat model as the embedding server.
- Do not require a local generation model such as Qwen3-4B when Codex/agent is the writer and reviewer. A local LLM endpoint is optional only for the legacy `generate` command or offline second-pass verification.
- Ingestion requires local embeddings by default. Do not use `--no-embed` for real workflows; if embedding setup or source ingestion fails, stop and fix the runtime or source instead of continuing with a half-indexed database.
- Download online sources into local reusable files or JSONL before ingestion. Do not paste large online materials into context when a file/cache can preserve them.
- Source kinds matter: `book`/`handout`/`notes` are core evidence; `syllabus`/`outline`/`exam_rules`/`requirements` are specifications; `question_bank`/`historical_exam` guide style and duplicate review only; `current_affairs` is dated background unless the task explicitly asks for current-affairs items; `qa` is supplemental.
- Knowledge planning and evidence planning may run in parallel after sources are indexed. Missing evidence routes to backfill; do not loop prompts to hide gaps.
- Core evidence retrieval ranks with local vectors against stored `embedding_json`; do not approve evidence from keyword-only retrieval.
- For local RAG over source files, use `scripts/llamaindex_sqlite_vec_rag.py`: LlamaIndex loads and splits files, local llama.cpp embeddings create vectors, sqlite-vec stores KNN vectors, and FTS5+vector hybrid retrieval returns source file, chunk id, split locator, matched text, and knowledge-point judgement.
- Treat `sqlite-vec`, LlamaIndex, and local embeddings as mandatory for that RAG path. If any dependency, vector dimension, embedding probe, or index build fails, stop and fix it; do not continue with FTS5-only, context-only, or remote-default retrieval.
- LlamaIndex CLI/MCP retrieval is optional and separate from the strict local RAG script. If used, pass an explicit provider/base URL from the current Codex config, keep embedding model consistency, cache returned results locally, and store auditable source locators before using results as evidence.
- Multi-writer candidates may start only after vectorized evidence planning is `strong`; they are judged by reviewers against evidence, outline, and historical-similarity results. Failed candidates route to writer revision, replanning, or evidence backfill.
- Generated items must include citations, evidence roles, knowledge points, coverage target, style profile, difficulty rationale, type-specific fields, and verification status.
- Never invent dates, names, institutions, policy wording, URLs, page numbers, citations, or historical-exam similarity results.

## Output Contract

Return question packages as JSON by default. For refused runs, include missing evidence types, strongest retrieved snippets, and the material the user should add.

Keep code modular. `cli.py` orchestrates only; core responsibilities live in the modules documented in [references/module_boundaries.md](references/module_boundaries.md).

