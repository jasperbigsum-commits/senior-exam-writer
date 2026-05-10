# Style And Difficulty

Use this reference to audit item style and difficulty calibration. The goal is not just "make questions"; it is to make questions that match the syllabus, chapter emphasis, and expected cognitive level.

## Style Contract

Every item should be:

- evidence-grounded: all factual claims cite evidence IDs;
- syllabus-aligned: the tested point maps to an outline, chapter, section, or stated learning objective when available;
- exam-grade: clear stem, explicit task, no accidental ambiguity;
- fair: enough information is present to answer from the supplied course/current-affairs evidence;
- reviewable: the output records citations, cognitive level, difficulty, and rationale.

Avoid:

- vague stems such as "Which of the following is correct?" without scope;
- double negatives or "not incorrect" phrasing unless explicitly requested;
- options with unequal grammar or giveaway length;
- "all of the above" or "none of the above" unless the source exam style requires it;
- distractors that are obviously absurd or not tied to common misunderstandings;
- difficulty labels that are not justified.

## Cognitive Levels

Use these levels when writing `style_profile.cognitive_level`:

- `remember`: recall a definition, term, time, institution, or factual statement.
- `understand`: explain, classify, compare, or identify meaning.
- `apply`: use a concept to judge a case, material, scenario, or current-affairs example.
- `analyze`: distinguish causes, structure, relationships, assumptions, or policy logic.
- `evaluate`: judge a view, decision, implication, or evidence strength against criteria.
- `create`: synthesize a plan, argument, or structured response. Use sparingly for exam items.

## Difficulty Calibration

Use the actual syllabus/outline first. If an outline is available, it overrides generic difficulty guesses.

`easy`

- Tests a single explicit fact, term, or definition.
- Uses one evidence chunk or one short section.
- Requires recognition or direct recall.
- Distractors are common but shallow confusions.

`medium`

- Connects two related concepts, evidence chunks, or chapter sections.
- Requires understanding, classification, comparison, or simple application.
- May use current-affairs material as a case, but the course concept remains clear.
- Distractors reflect plausible conceptual errors.

`hard`

- Requires multi-step reasoning, analysis of relationships, comparison of sources, or applying a concept to a complex case.
- Uses multiple evidence chunks or both course and current-affairs evidence.
- Requires distinguishing scope, time, institution, policy wording, or competing interpretations.
- Distractors should be genuinely plausible and evidence-sensitive.

Refuse or downgrade difficulty when evidence does not support the requested level.

## Syllabus And Outline Rules

When an outline or syllabus is ingested:

- Use outline headings to select topic scope.
- Treat "了解/识记/掌握/理解/应用/分析/评价" or similar verbs as difficulty signals.
- Prefer questions matching the strongest available learning-objective verb.
- Do not create high-difficulty analysis questions from a topic marked only as basic recall unless the user explicitly requests it and evidence supports it.
- Record the alignment in `style_profile.syllabus_alignment`.

Suggested mapping:

- `了解`, `识记`, `知道`: easy, remember.
- `理解`, `说明`, `比较`: medium, understand.
- `运用`, `结合材料`, `案例分析`: medium or hard, apply/analyze.
- `分析`, `评价`, `论述`: hard, analyze/evaluate.

## Output Fields

Each item should include:

```json
{
  "style_profile": {
    "cognitive_level": "apply",
    "syllabus_alignment": "Chapter 3 / section path / learning objective",
    "stem_style": "material-based application"
  },
  "difficulty": "medium",
  "difficulty_rationale": "The item asks learners to apply a chapter concept to a dated policy case; it uses one course evidence chunk and one background evidence chunk."
}
```

The `difficulty_rationale` should mention the evidence basis, cognitive level, and why the label is appropriate.

## Audit Checklist

- Does the item test the requested topic rather than a nearby but different topic?
- Does the difficulty match the outline verb or chapter emphasis?
- Is the cognitive level explicit and plausible?
- Are distractors plausible but not ambiguous?
- Is the answer derivable from cited evidence alone?
- Does the rationale justify the difficulty label?
