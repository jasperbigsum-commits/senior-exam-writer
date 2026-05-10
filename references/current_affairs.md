# Current Affairs And Current Politics

Use this reference when adding real-time politics, policy updates, news, or热点素材 as auxiliary material for question writing.

## Role In The System

Current-affairs/current-politics素材 is evidence, not model memory. It must be ingested or retrieved as source material before it can appear in a question.

There are two valid roles:

- `background_current_affairs`: background case, stem material, policy example, or dated event used to contextualize a course concept.
- `core_current_affairs`: primary evidence only when the requested question is explicitly about current affairs, policy updates, or real-time politics.

For ordinary course or textbook questions, the answer key should be supported by `core_course_evidence`; current-affairs material may enrich the stem or analysis but should not be the only basis for the correct answer.

## Accepted Source Types

Prefer sources chosen by the user or a course owner:

- official government or institution websites;
- official policy releases, speeches, communiques, notices, or statistical releases;
- official media or course-approved news sources;
- teacher-provided current-affairs packets;
- user-maintained JSON/JSONL素材库 with source, date, URL, and excerpt.

Avoid unsourced summaries, screenshots without provenance, social posts without original source, or model-generated summaries that do not cite original text.

## Required Fields

For each current-affairs item, store as many of these as possible:

- `title`
- `date` or `published_at`
- `source` or `source_name`
- `url`
- `entities`
- `tags`
- `event_summary`
- `full_text`
- `review_after` or `valid_until` when the topic may change

JSONL example:

```json
{"title":"Policy release title","date":"2026-05-10","source":"Official source","url":"https://example.gov/item","entities":["Agency"],"tags":["policy","current_affairs"],"event_summary":"One-sentence cited summary.","full_text":"Original excerpt or full text."}
```

Ingest example:

```bash
python scripts/senior_exam_writer.py ingest \
  --db ./exam_evidence.sqlite \
  --input ./current_affairs.jsonl \
  --kind current_affairs \
  --source-name "Official or user-approved source" \
  --published-at 2026-05-10 \
  --embed
```

## Freshness Rules

- Use `--strict-current` for politics, policy, leaders, institutions, economic indicators, live disputes, or any topic likely to change.
- Set `valid_until` or `review_after` for generated items when later developments could change the answer.
- Refuse if a current claim lacks source/date/locator.
- Refuse if sources conflict and no priority rule is provided.
- Prefer official primary sources over secondary reporting for policy wording.

## Item-Writing Rules

Allowed:

- "Based on the material, identify which textbook concept is illustrated by the policy example."
- "Compare the course definition with this dated policy statement."
- "Use the cited event as background, then ask about a course principle supported by the textbook."

Not allowed:

- Use a current event as an uncited fact in the analysis.
- Let background news alone determine the answer to a course concept question.
- Merge multiple reports into a smooth narrative without preserving source/date boundaries.
- Treat outdated current-affairs素材 as still valid without review.

## Audit Checks

- Does every current-affairs citation include source and date?
- Is the current-affairs source role marked as background or core?
- Is the answer key supported by the correct role?
- Is there a review window for time-sensitive material?
- Are source conflicts surfaced instead of hidden?
