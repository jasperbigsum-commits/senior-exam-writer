# Evidence Gate

## Core Contract

Generate only after retrieval. A question package must be backed by retrieved evidence that has stable source metadata and enough context to support the tested assertion.

## Minimum Evidence

- At least `min_evidence` relevant content or parent chunks must be retrieved.
- Each accepted evidence chunk should have a citation locator: source title or file path, TOC path or heading, and paragraph/page locator when available.
- For current-affairs素材, require date plus source name, URL, or file locator. Set `review_after` or `valid_until` in the output when the topic may change.
- Overview and TOC chunks may route the search, but final citations should usually point to content or parent chunks.

## Refusal Conditions

Refuse generation when:

- retrieved evidence is below threshold;
- evidence lacks clear subject, time, institution, event, or policy wording required by the question;
- citations cannot be produced;
- two evidence snippets conflict and no priority rule is available;
- current-affairs material is stale, undated, or from a non-whitelisted source when strict mode is requested.

## Citation Requirements

Every generated item should include:

- `citations`: evidence IDs such as `E1`, `E2`;
- `evidence_roles`: the cited evidence IDs grouped as `core`, `background`, `specification`, `prior_style`, and `qa`;
- `assertions`: short factual claims, each with citations;
- `analysis`: explanation grounded in citations;
- option-level support when writing choice questions. Wrong options should be contradicted by evidence, out of scope, or explicitly marked as "evidence_not_supported".

Book locator format:

`书名/文件名 - 章/节/小节路径 - 页码或段落定位`

Current-affairs locator format:

`来源 - 发布日期 - URL或文件名 - 段落定位`

## Verification Pass

Run static verification first:

- required fields exist;
- citations point to retrieved evidence IDs;
- assertions have citations;
- answer and analysis cite evidence.

Run LLM verification when a local generation model is available:

- verify whether each assertion is supported, contradicted, or not found;
- verify answer key consistency;
- verify wrong-option explanations;
- reject or rewrite items marked contradicted or unsupported.

Keep the verifier stricter than the writer. A rejected output is preferable to a fluent unsupported question.
