# Audit Workflow

Use this reference to explain how `循证出题官` handles a PDF, DOCX, Markdown, EPUB, text, JSON, or JSONL material package before it writes questions.

## Processing Flow

1. Receive materials and classify source type.
   - `book`: textbook, monograph, official handbook.
   - `handout`: course handout, teacher notes, lecture notes.
   - `outline`: syllabus or knowledge-point outline.
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

6. Retrieve evidence before generation.
   - Overview and TOC route the topic.
   - Content chunks find precise matches.
   - Parent chunks expand context so the writer does not rely on isolated fragments.
   - Retrieved chunks become evidence IDs such as `E1`, `E2`, `E3`.

7. Apply evidence gate.
   - Generation is blocked if there are too few usable content or parent evidence chunks.
   - Generation is blocked if evidence lacks citation locators.
   - Strict current-affairs mode requires dated URL or file-located sources.

8. Generate locally.
   - The question writer receives only the topic, generation parameters, and retrieved evidence JSON.
   - It must output JSON.
   - It is instructed not to use outside facts or invent missing details.

9. Verify.
   - Static verification checks schema, citation IDs, assertions, answer keys, and option consistency.
   - Optional local LLM verification checks whether assertions are supported, contradicted, or absent in the cited evidence.
   - Failed items are rewritten once when enabled; otherwise the run is refused with reasons and strongest evidence snippets.

10. Store audit trail.
   - Generation records are stored in SQLite `questions`.
   - Each record stores topic, question type, prompt parameters, evidence JSON, output JSON, verification JSON, status, and timestamp.

## Audit Questions

Use these questions when reviewing a run:

- Was the source type correctly classified?
- Did extraction preserve enough heading/page/paragraph location?
- Are overview and TOC used only for routing unless the item tests document structure?
- Are final citations drawn from content or parent chunks?
- Does every factual claim map to evidence IDs?
- Does each wrong option have a documented wrong reason?
- Did the verifier reject unsupported or contradicted claims?
- Are current-affairs dates, sources, URLs, and review windows present when needed?
