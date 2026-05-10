# Exam Task Workflow

This reference is the end-to-end operating contract for `循证出题官`.

The contract is enforced by scripts. A workflow step that violates required metadata, evidence, verification, review, coverage, or duplicate-control rules must fail closed instead of relying on the model to comply.

## Inputs

An exam-writing task may include:

- exam outline or syllabus: target chapters, learning objectives, verbs, weights, difficulty expectations;
- question-bank sources: prior papers, sample items, style examples, common traps, scoring patterns;
- proposition rules: allowed question types, option rules, scoring rules, forbidden patterns, citation requirements;
- other requirements: count, distribution, audience, time limit, political/current-affairs constraints, reviewer preferences;
- knowledge Q&A: user-provided question-answer pairs, FAQ, interview notes, teacher explanations;
- course evidence: books, handouts, official manuals, lecture notes;
- current-affairs/current-politics background: dated, sourced, URL/file-located material used as case/background only unless the task is explicitly a current-affairs item.

## Required Flow

1. Create or update an exam task.
   - Store outline, source policy, proposition rules, requirements, and coverage plan in `exam_tasks`.
   - Use `create-task`; do not leave core requirements only in chat memory.
   - Script gate: `outline`, `source_policy`, `question_rules`, `requirements`, and `coverage` must be non-empty JSON objects. Citations, review, and knowledge-point de-duplication must be explicitly enabled.

2. Classify and ingest sources.
   - `syllabus` / `outline`: exam scope and cognitive-level calibration.
   - `exam_rules` / `requirements`: hard constraints for item style and output.
   - `question_bank`: style, distribution, common traps, not copyable source text.
   - `qa`: supplemental evidence after splitting into retrievable Q&A chunks.
   - `book` / `handout` / `notes`: core course evidence.
   - `current_affairs`: dated background material.

3. De-duplicate the knowledge base before retrieval.
   - Every ingested chunk gets a normalized fingerprint.
   - Exact or near-duplicate chunks are blocked from `chunks` and `chunks_fts`.
   - When `--embed` is enabled, high-similarity embedding matches are also blocked as semantic duplicates.
   - Duplicate blocking is parent-first: if an entire parent section is duplicate, child chunks are not inserted or counted separately.
   - Blocked duplicates are stored in `ingest_duplicates` with source, candidate id, duplicate target, similarity, reason, and sample text.
   - The duplicate source row is kept even when zero chunks are inserted, so provenance remains auditable.
   - This prevents repeated copies from inflating retrieval confidence or polluting evidence.
   - Script gate: `--allow-duplicate-chunks` is rejected by default policy, missing chunk fingerprints block generation, and duplicate fingerprints block generation until cleaned.

4. Retrieve before generating.
   - Retrieval combines TOC/overview routing, BM25, optional llama.cpp embeddings, and parent-context expansion.
   - Evidence is role-labeled as `exam_specification`, `core_course_evidence`, `prior_question_style`, `supplemental_qa_evidence`, or `background_current_affairs`.

5. Collect extra real-time/current-affairs material only when needed.
   - If the topic depends on current policy, events, institutions, dates, or public materials, collect URLs into JSONL with `collect-urls`.
   - Ingest collected JSONL before use; live facts are not usable until they are in the SQLite evidence store.
   - For political/current-affairs material, preserve source, date, URL/file locator, and review date or freshness note.

6. Generate under task constraints.
   - `generate --task-id` passes the stored outline, rules, requirements, coverage plan, and prior accepted/unrejected knowledge points to the writer.
   - Each item must include `knowledge_points`, `coverage_target`, `style_profile`, `difficulty_rationale`, citations, assertions, evidence roles, and `dedup_check`.
   - Choice items must include `option_audit`; short-answer items must include `scoring_points`; material-analysis items must include `material`.
   - Question-bank sources may guide style and common pitfalls, but generated items must not copy previous items.
   - Script gate: generation requires `--task-id`, task-valid source policy, indexed required sources, evidence from answer-supporting source kinds, and `--llm-verify`.

7. Verify and reject weak output.
   - Evidence gate blocks thin or unlocatable evidence.
   - Static verification blocks missing citations, missing knowledge points, repeated in-batch knowledge points, invalid answer labels, or missing difficulty/style audit fields.
   - Optional local LLM verification checks factual support against evidence only.
   - If verification fails, rewrite once; if still weak, store a refusal report.

8. Human reviewer loop.
   - The reviewer records `approved`, `revise`, or `rejected` with `review-question`.
   - Rejected questions are excluded from prior accepted coverage; revision requests remain auditable.
   - Reviewer patches may be stored as JSON without overwriting the original generation record.
   - Script gate: approval is blocked unless the stored question status is `ok`, output status is `ok`, and verification passed.

9. Finish only when task coverage is satisfied.
   - Use `task-status` to inspect source counts, run counts, review decisions, and covered knowledge points.
   - Continue generation until the coverage plan is complete, evidence is sufficient, no repeated knowledge points are present, and reviewer decisions meet the task policy.
   - Use `complete-task` to mark completion. Script gate: approved item count, per-target coverage, difficulty/type distribution, verification, reviewer approval, and knowledge-point uniqueness must pass.

## Boundary Rules

- The skill does not invent missing facts, dates, institutions, policy wording, source URLs, page numbers, or citations.
- The skill does not treat repeated copies as stronger evidence.
- The skill does not use current-affairs background alone to answer a course-concept item.
- The skill does not silently update a textbook claim with current material; changed facts must be explicit in the item and separately cited.
- The skill does not replace a human reviewer for high-stakes exams; it preserves the audit trail so the reviewer can approve, revise, or reject.

## Suggested Task JSON Shapes

`outline`:

```json
{
  "exam_name": "期末考试",
  "audience": "本科二年级",
  "modules": [
    {
      "name": "模块一",
      "objectives": [
        {"text": "理解核心概念", "verb": "理解", "difficulty": "medium", "weight": 0.2}
      ]
    }
  ]
}
```

`coverage`:

```json
{
  "total_items": 20,
  "distribution": [
    {"target": "模块一/核心概念", "question_type": "single_choice", "difficulty": "medium", "count": 4}
  ],
  "avoid_repeating_knowledge_points": true
}
```

`source_policy`:

```json
{
  "required_core_kinds": ["book", "handout", "syllabus"],
  "allowed_background_kinds": ["current_affairs"],
  "current_affairs_requires_url_and_date": true,
  "question_bank_usage": "style_only_no_copying"
}
```
