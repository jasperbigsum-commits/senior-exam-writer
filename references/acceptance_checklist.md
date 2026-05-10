# Acceptance Checklist

Use this checklist when evaluating whether `senior-exam-writer` behaves like a real evidence-gated exam-writing skill, not just a question generator.

The evaluator should inspect the workflow trace, local files, SQLite records, generated JSON packages, similarity audits, and reviewer decisions. A run passes only when missing evidence causes refusal or backfill instead of unsupported generation.

## Universal Flow

For every scenario, verify this order:

1. Split the user request with `split-requirements` when it starts as natural language.
2. Initialize the database and local runtime with `init-db` and `init-runtime`.
3. Store outline, source policy, question rules, requirements, and coverage with `create-task`.
4. Collect online sources into local files or JSONL before ingestion.
5. Ingest local materials and collected JSONL with correct source kinds.
6. Run `audit-duplicates`; repeated chunks must not inflate retrieval confidence.
7. Run `plan-knowledge` and `plan-evidence`; knowledge matching and evidence-point generation may run in parallel after sources are indexed.
8. Generate multiple candidates with `generate-candidates` when the task asks for reviewer selection.
9. Run `audit-question-similarity` with local embeddings before candidate or final approval.
10. Use `review-candidate` and `review-question` to record reviewer decisions.
11. Use `task-status` and `complete-task`; completion must fail until coverage, verification, similarity review, approval, and knowledge-point uniqueness all pass.

## Scenario 1: Civil-Service Exam From Latest Official Syllabus

Human acceptance prompt:

> 根据最新国家公务员考试公共科目大纲，生成行测练习题。题型包括时事政治题、数量关系题、找规律题，每类各 3 道，难度分 easy / medium / hard。请先确认最新大纲来源，把大纲和时政资料下载到本地，不能直接凭记忆出题。每道题都要给答案、解析、知识点、难度理由、引用证据，并做历届题重复率审查。

Key checks:

- The run identifies and freezes the latest official syllabus or user-approved syllabus source before task creation.
- Syllabus and policy/current-affairs pages are downloaded into reusable local files or JSONL before ingestion.
- Source kinds are correct: `outline` or `syllabus` for the exam scope, `exam_rules` for hard constraints, `current_affairs` for dated background, and `historical_exam` or `question_bank` only for style and duplicate review.
- Current-affairs items preserve source name, date, URL or file locator, and review date.
- Quantity-relation and pattern-recognition items cite syllabus/rules for scope but do not pretend current-affairs background is mathematical proof.
- Each type covers `easy`, `medium`, and `hard`, with a difficulty rationale tied to syllabus expectations.
- Candidate and final items run local historical similarity review; `blocked_duplicate` or `revise_required` cannot be approved.
- If official syllabus/current-affairs evidence is missing, the output is a refusal or evidence-backfill report, not fluent unsupported questions.

Evaluation focus:

- Latest-source handling.
- Online-source caching and reuse.
- Separation of exam specification, current-affairs background, and answer-supporting evidence.
- Local-only similarity review.

## Scenario 2: University Final From Local PDF Chapters

Human acceptance prompt:

> 我有一本本地 PDF，内容是高等数学中经济统计学相关章节。请基于这个 PDF 给大学期末考试出题，包含计算题 4 道、简答题 4 道，难度分 easy / medium / hard。必须从 PDF 章节中提取知识点和证据点，计算题要有完整解题步骤，简答题要有评分点。

Key checks:

- The PDF is ingested as `book` or `handout`; chunks keep chapter, heading, page, or locator metadata when available.
- TOC and overview chunks route retrieval but are not used as final proof for formulas or definitions.
- Calculation items include givens, answer, complete solution steps, formula references, citations, knowledge points, and difficulty rationale.
- Short-answer items include model answer, cited scoring points, coverage target, and bounded expected scope.
- Difficulty levels are meaningful: easy for direct concept/formula use, medium for combined calculation, hard for multi-step application or interpretation.
- Questions do not introduce textbook content absent from the ingested PDF or approved supplemental sources.
- If the PDF lacks an extractable text layer, the run requests OCR/preprocessing instead of fabricating evidence.

Evaluation focus:

- Local-file parsing and chapter retrieval.
- Evidence locator quality.
- Calculation and short-answer output completeness.
- Refusal behavior for scanned or weak PDF evidence.

## Scenario 3: AI Engineer Hiring Assessment

Human acceptance prompt:

> 我们公司要招聘 AI 工程师，请基于岗位要求生成基础笔试题和面试题。笔试包含机器学习、深度学习、Python、工程实践、LLM 基础，每类 easy / medium / hard 各 1 道；面试题包含基础追问、项目追问、系统设计追问。请先把岗位 JD、能力模型、公司要求作为资料入库，再出题。

Key checks:

- Job description, competency model, company requirements, and interviewer preferences are ingested as `requirements`, `exam_rules`, `qa`, or `notes`.
- Coverage targets include machine learning, deep learning, Python, engineering practice, and LLM basics.
- Written items include answer, analysis, knowledge points, difficulty rationale, and scoring or grading basis.
- Interview items include competency target, first question, follow-up path, and strong/acceptable/risk-answer signals.
- JD and competency material are treated as exam specification, not as authoritative technical proof unless they explicitly define an internal standard.
- Hard items test tradeoffs, debugging, system design, evaluation, and boundary awareness rather than trivia.
- If only a JD exists and no technical standard is supplied, the run produces a capability-assessment framework or asks for more material instead of claiming fully authoritative answers.

Evaluation focus:

- Non-school exam adaptation.
- Coverage planning from role requirements.
- Distinction between specification evidence and technical answer evidence.
- Practical scoring and interview rubric quality.

## Pass Criteria

Score each scenario on these dimensions:

- Flow compliance: the run follows ingestion, planning, generation, verification, similarity review, and reviewer approval in order.
- Evidence completeness: every item can be traced to source, locator, URL/date when applicable, and evidence ID.
- Content consistency: question type, difficulty, knowledge point, answer, analysis, and scoring criteria agree with each other.
- Risk control: weak evidence, missing local model, duplicate questions, stale current-affairs material, or unextractable files trigger refusal or backfill.
- Product usability: the final package is usable by a teacher, exam administrator, recruiter, or reviewer without reconstructing missing context.

A scenario passes only if all blocking gates pass and no approved item relies on uncited model memory.
