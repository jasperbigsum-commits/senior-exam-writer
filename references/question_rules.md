# Question Rules

Use this reference to audit how `循证出题官` decides whether a question is valid.

## Non-Negotiable Rules

- Do not write a question before retrieving evidence.
- Do not invent dates, people, institutions, policies, page numbers, URLs, or citations.
- Do not use general model knowledge to fill gaps.
- Refuse when evidence is too thin, contradictory, stale, undated, or unlocatable.
- Make every key assertion cite one or more evidence IDs.
- Separate `core_course_evidence` from `background_current_affairs` in the item audit trail.
- Prefer a refusal report over a fluent unsupported question.

## Evidence Sufficiency

Evidence is sufficient only when it covers:

- subject: who or what the claim is about;
- action or relationship: what happened, changed, defined, required, or contrasted;
- scope: chapter, policy, institution, timeframe, region, or course module;
- locator: source title or source name plus heading/page/paragraph/chunk locator;
- date and URL/file locator for current-affairs material when applicable.

Overview and TOC chunks are not normally enough. They may support routing, syllabus-structure questions, or table-of-contents questions, but final conceptual or factual questions should cite parent/content chunks.

Current-affairs/current-politics素材 can be used as:

- background material in a stem;
- a case for applying a textbook concept;
- a dated policy or event fact in a pure current-affairs question;
- a contrast with textbook theory, if both sides are separately cited.

It must not be used to silently update or override textbook/course claims. If a current event changes a course claim, the item must explicitly ask about the change and cite both the course source and the current source.

## Question Package Schema

The writer should return JSON:

```json
{
  "status": "ok",
  "topic": "topic name",
  "question_type": "single_choice",
  "items": [
    {
      "id": "Q1",
      "stem": "question stem",
      "material": "optional source material excerpt",
      "options": [
        {"label": "A", "text": "option text", "citations": ["E1"]}
      ],
      "answer": "A",
      "analysis": "evidence-grounded explanation",
      "citations": ["E1", "E2"],
      "assertions": [
        {"claim": "short factual claim", "citations": ["E1"]}
      ],
      "evidence_roles": {
        "core": ["E1"],
        "background": ["E2"]
      },
      "difficulty": "medium",
      "valid_until": null
    }
  ]
}
```

When refusing:

```json
{
  "status": "refused",
  "reason": "evidence_gate_failed",
  "missing_evidence": ["what is missing"],
  "strongest_evidence": []
}
```

## Single-Choice Rules

- Include exactly one correct answer.
- Make distractors plausible but clearly wrong under the evidence.
- Each distractor should have a wrong reason in the analysis: contradicted, swapped subject, wrong time, wrong scope, overgeneralized, or evidence_not_supported.
- Avoid testing trivial wording unless the user asks for memorization questions.

## Multiple-Choice Rules

- State whether the answer may contain multiple options.
- Cite each correct option.
- Explain why every incorrect option is unsupported or contradicted.
- Avoid ambiguous "all of the above" patterns unless evidence explicitly supports them.

## Material-Analysis Rules

- Material excerpts must be copied or paraphrased from retrieved evidence and cited.
- Questions should ask the learner to infer, compare, classify, or explain from the material.
- Do not add background facts absent from the evidence.

## Short-Answer Rules

- Provide scoring points, not just a model answer.
- Each scoring point must cite evidence.
- Keep expected answer scope bounded by retrieved material.

## Verification Rules

Static verification fails when:

- required fields are missing;
- citations point to unknown evidence IDs;
- assertions lack citations;
- answers do not match option labels;
- item status is neither `ok` nor `refused`.

LLM verification fails when:

- a claim is unsupported by cited evidence;
- a claim contradicts cited evidence;
- the answer key is inconsistent with the analysis;
- an option explanation relies on outside facts;
- current-affairs claims lack date/source/URL or review window when needed.
- background evidence alone supports a non-current-affairs answer key.
