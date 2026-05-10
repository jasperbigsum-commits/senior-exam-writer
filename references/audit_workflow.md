# Audit Workflow

Use this reference to explain how `循证出题官` handles a PDF, DOCX, Markdown, EPUB, text, JSON, JSONL, or current-affairs/current-politics material package before it writes questions.

## Processing Flow

1. Receive materials and classify source type.
   - `book`: textbook, monograph, official handbook.
   - `handout`: course handout, teacher notes, lecture notes.
   - `outline`: syllabus or knowledge-point outline.
   - `syllabus`: formal exam/course syllabus with objectives and cognitive verbs.
   - `exam_rules`: proposition rules, item-writing constraints, scoring rules.
   - `requirements`: user/exam-specific requirements not already captured by the outline.
   - `question_bank`: prior/sample questions used for style, distribution, and trap analysis, not copying.
   - `qa`: knowledge question-answer pairs, FAQ, teacher explanations, or user-provided Q&A.
   - `current_affairs`: dated current-affairs素材, news, policy material, official release.
   - `notes`: user整理稿 or mixed notes.

2. Extract text.
   - DOCX: read paragraphs and tables with `python-docx`; heading styles are preserved as section hints.
   - PDF: read page text with `pypdf` or `PyPDF2`; page numbers become locators when extractable.
   - Markdown/text: read UTF-8 text directly.
   - EPUB: read spine HTML and convert to plain text.
   - JSON/JSONL: read structured current-affairs fields such as `title`, `date`, `source`, `url`, `entities`, `tags`, `event_summary`, and `full_text`.

3. Build a hierarchy.
   - Overview layer: early summary-like content, used for routing.
   - TOC layer: detected heading paths, used to decide where to look.
   - Parent layer: chapter or section-level context, used for generation.
   - Content layer: smaller child chunks, used for precise recall.

4. Attach metadata.
   - Each source records title, path, type, source name, URL, publication date, version, and created time.
   - Each chunk records layer, parent chunk id, heading path, locator, text, token estimate, optional embedding, and metadata.
   - Citations are formed from source title or source name, heading path, URL/file path, date, page, paragraph, or chunk locator.

5. Index for retrieval.
   - SQLite FTS5 provides keyword/BM25 retrieval.
   - Optional llama.cpp embeddings provide semantic retrieval.
   - Retrieval can work without embeddings, but audit quality is higher with a Chinese-capable local embedding model.

6. Block duplicate knowledge before retrieval.
   - Each chunk is normalized and fingerprinted.
   - Exact duplicates and high-similarity near duplicates are not inserted into `chunks` or `chunks_fts`.
   - When embeddings are enabled, semantic duplicates can also be blocked by cosine similarity.
   - Duplicate blocking is parent-first: if a parent section is duplicate, its children are skipped rather than counted as separate duplicate rows.
   - Blocked duplicates are stored in `ingest_duplicates` with the candidate id, original chunk id, similarity, reason, source, locator, and text sample.
   - Existing databases can be backfilled with fingerprints through `audit-duplicates --backfill`.
   - Repeated source copies must not be interpreted as stronger independent evidence.

7. Retrieve evidence before generation.
   - Overview and TOC route the topic.
   - Content chunks find precise matches.
   - Parent chunks expand context so the writer does not rely on isolated fragments.
   - Retrieved chunks become evidence IDs such as `E1`, `E2`, `E3`.
   - Course sources are labeled as `core_course_evidence`.
   - Outline, syllabus, exam rules, and requirements are labeled as `exam_specification`.
   - Question banks are labeled as `prior_question_style`.
   - Q&A sources are labeled as `supplemental_qa_evidence`.
   - Current-affairs/current-politics sources are labeled as `background_current_affairs`.

8. Apply script policy gates.
   - Generation must be bound to a valid task.
   - Required source kinds must have indexed chunks.
   - Chunks must have fingerprints and no exact duplicate fingerprint groups.
   - Generation requires answer-supporting evidence from book, handout, notes, or Q&A unless the task explicitly allows pure current-affairs items.
   - Question-bank and exam-specification evidence cannot be the only factual support.
   - Local LLM verification must be enabled.

9. Apply evidence gate.
   - Generation is blocked if there are too few usable content or parent evidence chunks.
   - Generation is blocked if evidence lacks citation locators.
   - Strict current-affairs mode requires dated URL or file-located sources.
   - Current-affairs background cannot replace missing course evidence unless the requested task is explicitly a pure current-affairs item.

10. Generate locally.
   - The question writer receives the topic, generation parameters, retrieved evidence JSON, stored task context, and prior task knowledge points.
   - It must output JSON.
   - It is instructed not to use outside facts or invent missing details.
   - It must include precise `knowledge_points`, `coverage_target`, `style_profile`, `difficulty_rationale`, and `dedup_check`.
   - It must avoid repeating knowledge points from prior unrejected task outputs and from other items in the same batch.

11. Verify.
   - Static verification checks schema, citation IDs, assertions, answer keys, and option consistency.
   - Static verification checks required knowledge points and duplicate knowledge points within the same batch.
   - Task-level verification checks repeated knowledge points against prior unrejected generated items.
   - Optional local LLM verification checks whether assertions are supported, contradicted, or absent in the cited evidence.
   - Failed items are rewritten once when enabled; otherwise the run is refused with reasons and strongest evidence snippets.

12. Store audit trail.
   - Generation records are stored in SQLite `questions`.
   - Each record stores topic, question type, prompt parameters, evidence JSON, output JSON, verification JSON, status, and timestamp.
   - Exam-task metadata is stored in `exam_tasks`.
   - Human review decisions are stored in `question_reviews`.
   - Blocked duplicate chunks are stored in `ingest_duplicates`.

## Audit Questions

Use these questions when reviewing a run:

- Was the source type correctly classified?
- Did extraction preserve enough heading/page/paragraph location?
- Are overview and TOC used only for routing unless the item tests document structure?
- Were duplicate chunks blocked before retrieval?
- Do repeated source copies avoid inflating evidence confidence?
- Are final citations drawn from content or parent chunks?
- Are exam specifications separated from core course evidence?
- Are question banks used for style only, without copying?
- Are course claims supported by `core_course_evidence` rather than only background素材?
- Are current-affairs/current-politics sources dated, sourced, and reviewable?
- Does every factual claim map to evidence IDs?
- Does every item declare precise `knowledge_points` and `coverage_target`?
- Does the item avoid prior covered knowledge points for the same task?
- Does each wrong option have a documented wrong reason?
- Did the verifier reject unsupported or contradicted claims?
- Did script policy validation reject missing task, source, fingerprint, type-specific field, or completion requirements?
- Are current-affairs dates, sources, URLs, and review windows present when needed?
- Did the human reviewer approve, request revision, or reject the item?
