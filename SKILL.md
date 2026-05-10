---
name: senior-exam-writer
description: Build and use a local evidence-gated Chinese exam-question agent named 循证出题官. Use when Codex needs to ingest PDF/DOCX/Markdown/EPUB/text course materials, books, outlines, or current-affairs/current-politics素材; build a SQLite evidence store; perform TOC-driven hierarchical retrieval; separate core course evidence from background current-affairs evidence; use local llama.cpp embeddings and local generation; require citations; refuse weak evidence; and verify outputs for hallucination control.
---

# 循证出题官

Use this skill to turn books, handouts, outlines, and current-affairs/current-politics素材 into a local, evidence-gated question-writing workflow. The technical skill id remains `senior-exam-writer`; the user-facing name is `循证出题官`.

The central rule is: retrieve evidence first, generate second, verify last; refuse when the evidence is not enough.

Core policy is script-enforced. Do not rely on prompt compliance alone: task creation, ingestion, generation, review, and completion all run Python validation gates and fail closed when required metadata, evidence, citations, review decisions, coverage, or de-duplication constraints are missing.

## Decision Map

- Validate or run the full exam-task lifecycle: read [references/task_workflow.md](references/task_workflow.md).
- Explain how PDF/DOCX materials are processed: read [references/audit_workflow.md](references/audit_workflow.md).
- Audit item-writing rules and rejection conditions: read [references/question_rules.md](references/question_rules.md).
- Calibrate style, cognitive level, and difficulty against the syllabus/outline: read [references/style_difficulty.md](references/style_difficulty.md).
- Add or review current-affairs/current-politics素材: read [references/current_affairs.md](references/current_affairs.md).
- Download and normalize user-approved URLs into JSONL evidence: use `collect-urls`.
- Audit module boundaries and responsibilities: read [references/module_boundaries.md](references/module_boundaries.md).
- Change grounding, citation, or verification behavior: read [references/evidence_gate.md](references/evidence_gate.md).
- Configure local embedding/generation: read [references/llama_cpp.md](references/llama_cpp.md).
- Inspect or extend SQLite tables: read [references/sqlite_schema.md](references/sqlite_schema.md).

## Standard Workflow

1. Create a SQLite evidence database:

```bash
python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
```

2. Create an auditable exam task from the actual outline, question-bank policy, proposition rules, extra requirements, and coverage plan. These values may be JSON strings or JSON files.

```bash
python scripts/senior_exam_writer.py create-task \
  --db ./exam_evidence.sqlite \
  --name "2026 spring final exam" \
  --outline ./outline.json \
  --source-policy ./source_policy.json \
  --question-rules ./question_rules.json \
  --requirements ./requirements.json \
  --coverage ./coverage.json
```

3. Ingest course materials. Prefer `--embed` with a local llama.cpp embedding server; use `--no-embed` only for BM25-only indexing or offline testing. Ingestion blocks exact and near-duplicate chunks by default and records blocked duplicates in `ingest_duplicates`.

```bash
python scripts/senior_exam_writer.py ingest \
  --db ./exam_evidence.sqlite \
  --input ./materials \
  --kind book \
  --embed \
  --embed-url http://127.0.0.1:8081
```

Use source kinds intentionally:

- `syllabus` or `outline`: exam scope and cognitive-level calibration.
- `exam_rules` or `requirements`: hard proposition constraints.
- `question_bank`: prior style and common traps only; do not copy items.
- `qa`: user-provided knowledge Q&A, split and retrieved as supplemental evidence.
- `book`, `handout`, `notes`: core course evidence.
- `current_affairs`: dated auxiliary or current-politics素材.

4. Ingest dated current-affairs or current-politics素材 when it is used as background or auxiliary material:

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

5. When URL sources are provided or discovered, collect them into an auditable JSONL before ingestion:

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

6. Audit duplicate controls if source overlap is suspected:

```bash
python scripts/senior_exam_writer.py audit-duplicates \
  --db ./exam_evidence.sqlite \
  --backfill
```

7. Inspect retrieval before generating:

```bash
python scripts/senior_exam_writer.py retrieve \
  --db ./exam_evidence.sqlite \
  --query "新时代党的建设 总要求" \
  --top-k 8 \
  --embed-url http://127.0.0.1:8081
```

8. Generate questions locally with evidence gate, task constraints, prior-knowledge-point de-duplication, and verification:

```bash
python scripts/senior_exam_writer.py generate \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID \
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

9. Record the reviewer decision. A human reviewer may approve, request revision, or reject; the original generation record remains auditable.

```bash
python scripts/senior_exam_writer.py review-question \
  --db ./exam_evidence.sqlite \
  --question-id QUESTION_ID \
  --decision approved \
  --reviewer "chief reviewer" \
  --notes "meets outline and evidence rules"
```

10. Check completion status:

```bash
python scripts/senior_exam_writer.py task-status \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID
```

11. Mark the task complete only through the script gate. This fails if approved items do not satisfy coverage, review, verification, and knowledge-point de-duplication rules.

```bash
python scripts/senior_exam_writer.py complete-task \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID
```

## Evidence Rules

- Treat TOC/目录 and overview/导论 chunks as routers, not as final proof unless the question only asks about structure.
- Use content chunks and their parent section context as final evidence.
- Treat books, textbooks, handouts, and notes as `core_course_evidence`.
- Treat syllabus, outline, exam rules, and explicit requirements as `exam_specification`.
- Treat prior question banks as `prior_question_style`: they may guide format, style, difficulty distribution, and common traps, but must not be copied.
- Treat user-provided knowledge Q&A as `supplemental_qa_evidence`.
- Treat current-affairs/current-politics素材 as `background_current_affairs` unless the requested item is explicitly a current-affairs item.
- Do not let current-affairs background alone determine the correct answer for a textbook/course concept.
- Match item style and difficulty to the retrieved syllabus/outline or textbook chapter expectations; record the difficulty rationale.
- Prevent knowledge-base pollution: exact or near-duplicate chunks are blocked from the retrieval index by default. Review `ingest_duplicates` before treating repeated sources as independent evidence.
- Prevent question-set duplication: generated items must include precise `knowledge_points`; `generate --task-id` checks prior task outputs and refuses repeated points.
- Require `--task-id` and `--llm-verify` for generation. Ad-hoc generation without a task or verifier is blocked by the script.
- Require source-policy compliance before generation: required source kinds must have indexed chunks, chunk fingerprints must exist, and duplicate fingerprints must be cleaned.
- Require type-specific item fields: choice items need `option_audit`; short-answer items need `scoring_points`; material-analysis items need `material`.
- Require reviewer approval before task completion; refused or unverified outputs cannot be approved.
- Require citations for stem, answer, analysis, and material excerpts.
- For current-affairs/current-politics素材, prefer white-listed official or user-provided sources, and require source, date, URL or file locator, and review date.
- Refuse or ask for more material when evidence lacks a clear subject, time, policy wording, institution, or citation locator.
- After generation, verify every key assertion against cited evidence. Rewrite once if verification fails; otherwise return a refusal report.

## Output Expectations

Return question packages as JSON by default. Keep rejected runs useful: include the missing evidence types, the strongest retrieved snippets, and what material the user should add.

Never invent dates, names, institutions, policies, page numbers, URLs, or citations. Do not "smooth over" missing support with generic knowledge.

## Module Boundary

Keep the script implementation modular:

- `common.py`: shared dataclasses, constants, and stable IDs.
- `store.py`: SQLite connection and schema only.
- `parsing.py`: local file parsing and chunk shaping only.
- `dedup.py`: text normalization, chunk fingerprints, duplicate blocking, and duplicate audit reporting only.
- `evidence_roles.py`: source-kind/evidence-role mapping and item evidence role keys only.
- `source_metadata.py`: JSON/JSONL source metadata inspection only.
- `collection.py`: URL download and source normalization only.
- `ingest.py`: source/chunk insertion and embedding attachment only.
- `retrieval.py`: keyword/vector retrieval, parent expansion, and evidence JSON only.
- `generation.py`: prompt construction, output parsing, refusal, and verification only.
- `tasks.py`: exam task metadata, reviewer records, coverage status, and prior-question context only.
- `validation.py`: script-enforced policy gates for tasks, ingestion, evidence, output, review, and completion only.
- `cli.py`: command-line orchestration only.
- `senior_exam_writer.py`: thin compatibility wrapper only.
