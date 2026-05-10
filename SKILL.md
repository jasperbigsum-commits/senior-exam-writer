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

1. Create or migrate a SQLite evidence database:

```bash
python scripts/senior_exam_writer.py init-db --db ./exam_evidence.sqlite
```

2. Initialize the local runtime. Both embedding and generation endpoints must be loopback URLs; use the generated sidecar folders for downloads, cache files, and reports.

```bash
python scripts/senior_exam_writer.py init-runtime \
  --db ./exam_evidence.sqlite \
  --embed-url http://127.0.0.1:8081 \
  --llm-url http://127.0.0.1:8080
```

3. Split the user's entry requirement into executable stage prompts when the request starts as natural language rather than ready JSON. Use the prompt package to fill task JSON, source collection, knowledge planning, evidence planning, multi-writer, reviewer, similarity review, and final approval steps.

```bash
python scripts/senior_exam_writer.py split-requirements \
  --requirements "entry requirement text" \
  --writer-count 3 \
  --output-json ./prompt_package.json \
  --output-jsonl ./prompt_stages.jsonl
```

4. Create an auditable exam task from the actual outline, question-bank policy, proposition rules, extra requirements, and coverage plan. These values may be JSON strings or JSON files.

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

5. Ingest course materials with local embeddings. Use `--no-embed` only for BM25-only indexing or offline tests.

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
- `historical_exam`: prior real exam items for local duplicate review and style signals only; do not copy them.
- `qa`: user-provided knowledge Q&A, split and retrieved as supplemental evidence.
- `book`, `handout`, `notes`: core course evidence.
- `current_affairs`: dated auxiliary or current-politics material.

6. Collect URL sources into reusable local files before ingestion. Downloaded online material is cached locally and should be reused instead of pasted into the chat context.

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

7. When historical exam coverage is thin, collect prior papers or online historical items into reusable local files, then ingest the normalized JSONL as `historical_exam`.

```bash
python scripts/senior_exam_writer.py collect-exam-sources \
  --url https://example.edu/prior-exam \
  --input ./local_prior_exams \
  --output-jsonl ./historical_exam_collected.jsonl \
  --out-dir ./historical_exam_sources \
  --db ./exam_evidence.sqlite \
  --ingest \
  --embed
```

8. Audit duplicate controls if source overlap is suspected:

```bash
python scripts/senior_exam_writer.py audit-duplicates \
  --db ./exam_evidence.sqlite \
  --backfill
```

9. Plan knowledge and evidence in batches. Knowledge-point matching and evidence-point generation may run in parallel when source coverage is already available; missing evidence points are routed to evidence backfill rather than repeated prompting.

```bash
python scripts/senior_exam_writer.py plan-knowledge \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID

python scripts/senior_exam_writer.py plan-evidence \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID \
  --embed-url http://127.0.0.1:8081
```

10. Generate one final run locally with evidence gate, task constraints, prior-knowledge-point de-duplication, and verification when using the classic path:

```bash
python scripts/senior_exam_writer.py generate \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID \
  --topic "course topic" \
  --question-type single_choice \
  --count 5 \
  --difficulty medium \
  --llm-url http://127.0.0.1:8080 \
  --embed-url http://127.0.0.1:8081 \
  --min-evidence 3 \
  --strict-current \
  --llm-verify
```

11. For the closed-loop path, fan out each planning unit to multiple writers, then fill candidate outputs through the local generation process or an orchestrator that writes `candidate_questions.output_json` and `verification_json`.

```bash
python scripts/senior_exam_writer.py generate-candidates \
  --db ./exam_evidence.sqlite \
  --planning-unit-id PLANNING_UNIT_ID \
  --topic "course topic" \
  --writer-count 3
```

12. Run mandatory local historical duplicate review before approval. The command uses local embeddings only and fails when question text has not been generated. Use `--planning-unit-id` for candidate batches or `--question-id` for final question records.

```bash
python scripts/senior_exam_writer.py audit-question-similarity \
  --db ./exam_evidence.sqlite \
  --planning-unit-id PLANNING_UNIT_ID \
  --task-id TASK_ID \
  --embed-url http://127.0.0.1:8081
```

13. Review candidates against the outline, evidence points, and similarity audit. Route failures back to the correct stage: writer revision, replanning, or evidence backfill.

```bash
python scripts/senior_exam_writer.py review-candidate \
  --db ./exam_evidence.sqlite \
  --candidate-id CANDIDATE_ID \
  --decision evidence_gap \
  --reason-code evidence_missing \
  --notes "add stronger citations before the next writer round"
```

14. Record the final reviewer decision. A human reviewer may approve, request revision, or reject; the original generation record remains auditable. Approval is blocked unless verification passed and a local similarity audit for the final question passes.

```bash
python scripts/senior_exam_writer.py audit-question-similarity \
  --db ./exam_evidence.sqlite \
  --question-id QUESTION_ID \
  --embed-url http://127.0.0.1:8081

python scripts/senior_exam_writer.py review-question \
  --db ./exam_evidence.sqlite \
  --question-id QUESTION_ID \
  --decision approved \
  --reviewer "chief reviewer" \
  --notes "meets outline and evidence rules"
```

15. Check completion status:

```bash
python scripts/senior_exam_writer.py task-status \
  --db ./exam_evidence.sqlite \
  --task-id TASK_ID
```

16. Mark the task complete only through the script gate. This fails if approved items do not satisfy coverage, review, verification, historical duplicate review, and knowledge-point de-duplication rules.

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
