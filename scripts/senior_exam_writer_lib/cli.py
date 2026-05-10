from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

from .collection import collect_urls, read_url_list
from .common import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_EMBED_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_URL,
    DEFAULT_USER_AGENT,
    SOURCE_KINDS,
    now_iso,
)
from .dedup import audit_duplicate_fingerprints, backfill_missing_fingerprints
from .generation import build_generation_prompt, extract_json, refusal, rewrite_once, verify_static, verify_with_llm
from .ingest import collect_files, ingest_file
from .llama_cpp_client import llama_chat
from .retrieval import evidence_to_json, gate_evidence, retrieve_evidence
from .store import connect, ensure_db, init_db
from .tasks import (
    create_or_update_task,
    duplicate_points_against_prior,
    get_task,
    list_tasks,
    load_task_context,
    prior_question_context,
    read_json_arg,
    record_review,
    task_status,
    task_to_json,
)
from .validation import (
    ValidationError,
    validate_evidence_contract,
    validate_generation_request,
    validate_ingest_request,
    validate_output_contract,
    validate_review_request,
    validate_task_completion,
)

def cmd_init_db(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    init_db(conn)
    print(json.dumps({"ok": True, "db": args.db}, ensure_ascii=False, indent=2))

def cmd_ingest(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    files = collect_files(Path(args.input))
    if not files:
        raise SystemExit(f"no supported files found in {args.input}")
    results = []
    for path in files:
        validate_ingest_request(
            input_path=path,
            kind=args.kind,
            source_name=args.source_name,
            url=args.url,
            published_at=args.published_at,
            allow_duplicate_chunks=args.allow_duplicate_chunks,
        )
        print(f"[ingest] {path}", file=sys.stderr)
        result = ingest_file(
            conn,
            path,
            kind=args.kind,
            title=args.title if len(files) == 1 else None,
            source_name=args.source_name,
            url=args.url,
            published_at=args.published_at,
            version=args.version,
            embed=args.embed,
            embed_url=args.embed_url,
            embed_model=args.embed_model,
            max_chars=args.max_chars,
            dedup=not args.allow_duplicate_chunks,
            dedup_threshold=args.dedup_threshold,
            semantic_dedup_threshold=args.semantic_dedup_threshold,
        )
        results.append(result)
    print(json.dumps({"ok": True, "files": len(files), "results": results}, ensure_ascii=False, indent=2))

def cmd_collect_urls(args: argparse.Namespace) -> None:
    urls = read_url_list(args.url, args.url_file)
    if not urls:
        raise SystemExit("no URLs provided; use --url or --url-file")
    result = collect_urls(
        urls=urls,
        out_dir=Path(args.out_dir),
        jsonl_path=Path(args.output_jsonl),
        source_name=args.source_name,
        tags=args.tag or [],
        query=args.query,
        timeout=args.timeout,
        user_agent=args.user_agent,
    )
    ingest_results: list[dict[str, Any]] = []
    if args.ingest:
        if not args.db:
            raise SystemExit("--ingest requires --db")
        validate_ingest_request(
            input_path=Path(args.output_jsonl),
            kind=args.kind,
            source_name=args.source_name,
            url=None,
            published_at=args.published_at,
            allow_duplicate_chunks=args.allow_duplicate_chunks,
        )
        conn = connect(args.db)
        ensure_db(conn)
        ingest_results.append(
            ingest_file(
                conn,
                Path(args.output_jsonl),
                kind=args.kind,
                title=args.title,
                source_name=args.source_name,
                url=None,
                published_at=args.published_at,
                version=args.version,
                embed=args.embed,
                embed_url=args.embed_url,
                embed_model=args.embed_model,
                max_chars=args.max_chars,
                dedup=not args.allow_duplicate_chunks,
                dedup_threshold=args.dedup_threshold,
                semantic_dedup_threshold=args.semantic_dedup_threshold,
            )
        )
    print(
        json.dumps(
            {
                "ok": True,
                "collected": result["count"],
                "jsonl": result["jsonl"],
                "ingested": ingest_results,
                "records": [
                    {
                        "title": r.get("title"),
                        "source": r.get("source"),
                        "date": r.get("date"),
                        "url": r.get("url"),
                        "raw_path": r.get("raw_path"),
                        "chars": len(r.get("full_text") or ""),
                    }
                    for r in result["records"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

def cmd_retrieve(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    embed_url = args.embed_url if args.embed_url else None
    evidence = retrieve_evidence(conn, args.query, top_k=args.top_k, embed_url=embed_url, embed_model=args.embed_model)
    print(json.dumps({"query": args.query, "evidence": evidence_to_json(evidence, max_chars=args.max_chars)}, ensure_ascii=False, indent=2))

def cmd_generate(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    task_context = load_task_context(conn, args.task_id)
    validate_generation_request(
        conn=conn,
        task_context=task_context,
        question_type=args.question_type,
        count=args.count,
        difficulty=args.difficulty,
        llm_verify=args.llm_verify,
    )
    prior_context = prior_question_context(conn, task_id=args.task_id, limit=args.prior_limit)
    evidence = retrieve_evidence(
        conn,
        args.topic,
        top_k=args.top_k,
        embed_url=args.embed_url,
        embed_model=args.embed_model,
        layers={"parent", "content", "overview", "toc"},
    )
    ok, gate = gate_evidence(evidence, args.min_evidence, args.strict_current)
    if ok:
        try:
            validate_evidence_contract(evidence=evidence, task_context=task_context, strict_current=args.strict_current)
        except ValidationError as exc:
            ok = False
            gate = {
                "ok": False,
                "issues": gate.get("issues", []) + exc.issues,
                "usable_evidence": gate.get("usable_evidence", 0),
            }
    prompt_record = {
        "topic": args.topic,
        "question_type": args.question_type,
        "count": args.count,
        "difficulty": args.difficulty,
        "min_evidence": args.min_evidence,
        "strict_current": args.strict_current,
        "task_id": args.task_id,
        "task_context": task_context,
        "prior_context": prior_context,
    }
    if not ok:
        output = refusal(args.topic, gate, evidence)
        verification = {"ok": False, "mode": "gate", "issues": gate["issues"]}
        status = "refused"
    else:
        messages = build_generation_prompt(
            args.topic,
            args.question_type,
            args.count,
            args.difficulty,
            evidence,
            args.language,
            task_context=task_context,
            prior_context=prior_context,
        )
        raw = llama_chat(messages, args.llm_url, args.llm_model, temperature=args.temperature, max_tokens=args.max_tokens)
        try:
            output = extract_json(raw)
        except Exception as exc:
            output = {"status": "refused", "reason": "generation_returned_non_json", "raw": raw[:2000], "error": str(exc)}
            verification = {"ok": False, "mode": "parse", "issues": ["generation returned non-JSON"]}
            status = "refused"
        else:
            if not isinstance(output, dict):
                output = {"status": "refused", "reason": "generation_returned_non_object_json", "raw": output}
            verification = (
                verify_with_llm(output, evidence, args.llm_url, args.llm_model)
                if args.llm_verify
                else verify_static(output, evidence)
            )
            policy_report = validate_output_contract(
                output=output,
                evidence=evidence,
                task_context=task_context,
                question_type=args.question_type,
                count=args.count,
                difficulty=args.difficulty,
            )
            verification["policy"] = policy_report
            if not policy_report.get("ok"):
                verification["ok"] = False
                verification.setdefault("issues", []).extend(policy_report.get("issues", []))
            duplicate_issues = duplicate_points_against_prior(output, prior_context)
            if duplicate_issues:
                verification["ok"] = False
                verification.setdefault("issues", []).extend(duplicate_issues)
                verification["duplicate_knowledge_points"] = duplicate_issues
            if not verification.get("ok") and args.rewrite_on_fail and output.get("status") != "refused":
                try:
                    output = rewrite_once(
                        output,
                        verification,
                        args.topic,
                        args.question_type,
                        args.count,
                        args.difficulty,
                        evidence,
                        args.language,
                        args.llm_url,
                        args.llm_model,
                        task_context=task_context,
                        prior_context=prior_context,
                    )
                    verification = (
                        verify_with_llm(output, evidence, args.llm_url, args.llm_model)
                        if args.llm_verify
                        else verify_static(output, evidence)
                    )
                    policy_report = validate_output_contract(
                        output=output,
                        evidence=evidence,
                        task_context=task_context,
                        question_type=args.question_type,
                        count=args.count,
                        difficulty=args.difficulty,
                    )
                    verification["policy"] = policy_report
                    if not policy_report.get("ok"):
                        verification["ok"] = False
                        verification.setdefault("issues", []).extend(policy_report.get("issues", []))
                    duplicate_issues = duplicate_points_against_prior(output, prior_context)
                    if duplicate_issues:
                        verification["ok"] = False
                        verification.setdefault("issues", []).extend(duplicate_issues)
                        verification["duplicate_knowledge_points"] = duplicate_issues
                except Exception as exc:
                    verification = {"ok": False, "mode": "rewrite", "issues": [f"rewrite failed: {exc}"]}
            status = "ok" if verification.get("ok") and output.get("status") == "ok" else "refused"
            if status != "ok" and output.get("status") != "refused":
                output = {
                    "status": "refused",
                    "reason": "verification_failed",
                    "verification": verification,
                    "strongest_evidence": evidence_to_json(evidence[:5], max_chars=700),
                    "draft": output,
                }

    qid = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO questions(id, topic, question_type, task_id, prompt_json, evidence_json, output_json, verification_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            qid,
            args.topic,
            args.question_type,
            args.task_id,
            json.dumps(prompt_record, ensure_ascii=False),
            json.dumps(evidence_to_json(evidence), ensure_ascii=False),
            json.dumps(output, ensure_ascii=False),
            json.dumps(verification, ensure_ascii=False),
            status,
            now_iso(),
        ),
    )
    conn.commit()
    result = {
        "id": qid,
        "status": status,
        "gate": gate,
        "verification": verification,
        "evidence": evidence_to_json(evidence, max_chars=900),
        "output": output,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

def cmd_create_task(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    task = create_or_update_task(
        conn,
        task_id=args.task_id,
        name=args.name,
        outline=read_json_arg(args.outline, "outline"),
        source_policy=read_json_arg(args.source_policy, "source-policy"),
        question_rules=read_json_arg(args.question_rules, "question-rules"),
        requirements=read_json_arg(args.requirements, "requirements"),
        coverage=read_json_arg(args.coverage, "coverage"),
        status=args.status,
    )
    print(json.dumps({"ok": True, "task": task}, ensure_ascii=False, indent=2))

def cmd_list_tasks(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    print(json.dumps({"tasks": list_tasks(conn)}, ensure_ascii=False, indent=2))

def cmd_task_status(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    print(json.dumps(task_status(conn, args.task_id), ensure_ascii=False, indent=2))

def cmd_review_question(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    validate_review_request(
        conn=conn,
        question_id=args.question_id,
        decision=args.decision,
        notes=args.notes,
    )
    review = record_review(
        conn,
        question_id=args.question_id,
        reviewer=args.reviewer,
        decision=args.decision,
        notes=args.notes,
        patch=read_json_arg(args.patch, "patch") if args.patch else {},
    )
    print(json.dumps({"ok": True, "review": review}, ensure_ascii=False, indent=2))

def cmd_complete_task(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    task = task_to_json(get_task(conn, args.task_id))
    report = validate_task_completion(conn, task)
    if not report["ok"]:
        raise ValidationError(report["issues"])
    conn.execute(
        "UPDATE exam_tasks SET status = ?, updated_at = ? WHERE id = ?",
        ("completed", now_iso(), args.task_id),
    )
    conn.commit()
    print(json.dumps({"ok": True, "task_id": args.task_id, "completion": report}, ensure_ascii=False, indent=2))

def cmd_audit_duplicates(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    backfilled = backfill_missing_fingerprints(conn) if args.backfill else 0
    report = audit_duplicate_fingerprints(conn)
    report["backfilled_fingerprints"] = backfilled
    print(json.dumps(report, ensure_ascii=False, indent=2))

def cmd_stats(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    data = {
        "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
        "layers": {
            row["layer"]: row["n"]
            for row in conn.execute("SELECT layer, COUNT(*) AS n FROM chunks GROUP BY layer").fetchall()
        },
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))

def cmd_vacuum(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    conn.execute("VACUUM")
    print(json.dumps({"ok": True, "db": args.db, "action": "vacuum"}, ensure_ascii=False, indent=2))

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local evidence-gated senior exam writer with SQLite and llama.cpp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python scripts/senior_exam_writer.py init-db --db ./exam.sqlite
              python scripts/senior_exam_writer.py create-task --db ./exam.sqlite --name "期末政治理论" --outline ./outline.json --coverage ./coverage.json
              python scripts/senior_exam_writer.py ingest --db ./exam.sqlite --input ./materials --kind book --embed
              python scripts/senior_exam_writer.py retrieve --db ./exam.sqlite --query "共同富裕"
              python scripts/senior_exam_writer.py generate --db ./exam.sqlite --task-id TASK_ID --topic "共同富裕" --count 3 --llm-verify
              python scripts/senior_exam_writer.py review-question --db ./exam.sqlite --question-id QUESTION_ID --decision approved
            """
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init-db", help="create or migrate the SQLite evidence database")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("ingest", help="ingest files into the evidence database")
    p.add_argument("--db", required=True)
    p.add_argument("--input", required=True, help="file or directory")
    p.add_argument("--kind", default="book", choices=SOURCE_KINDS)
    p.add_argument("--title")
    p.add_argument("--source-name")
    p.add_argument("--url")
    p.add_argument("--published-at")
    p.add_argument("--version")
    p.add_argument("--embed", action="store_true", help="call local llama.cpp embedding server")
    p.add_argument("--no-embed", action="store_false", dest="embed")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--max-chars", type=int, default=900)
    p.add_argument("--dedup-threshold", type=float, default=0.9, help="near-duplicate threshold for chunk blocking")
    p.add_argument("--semantic-dedup-threshold", type=float, default=0.985, help="embedding cosine threshold used for semantic duplicate blocking when --embed is enabled")
    p.add_argument("--allow-duplicate-chunks", action="store_true", help="store duplicate chunks instead of recording them as blocked duplicates")
    p.set_defaults(func=cmd_ingest, embed=False)

    p = sub.add_parser("create-task", help="create or update an exam-writing task with outline, rules, requirements, and coverage plan")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", help="existing task id to update; omitted means create")
    p.add_argument("--name", required=True)
    p.add_argument("--outline", help="JSON string or JSON file path for exam outline/syllabus requirements")
    p.add_argument("--source-policy", help="JSON string or JSON file path for permitted/required source policy")
    p.add_argument("--question-rules", help="JSON string or JSON file path for item-writing rules")
    p.add_argument("--requirements", help="JSON string or JSON file path for other user/exam requirements")
    p.add_argument("--coverage", help="JSON string or JSON file path for coverage plan and quotas")
    p.add_argument("--status", default="active", choices=["draft", "active", "paused", "completed"])
    p.set_defaults(func=cmd_create_task)

    p = sub.add_parser("list-tasks", help="list exam-writing tasks")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_list_tasks)

    p = sub.add_parser("task-status", help="show task coverage, source, question, and review status")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=cmd_task_status)

    p = sub.add_parser("complete-task", help="mark a task completed only after script-enforced coverage, review, and de-duplication checks pass")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=cmd_complete_task)

    p = sub.add_parser("collect-urls", help="download URLs, extract text, and write current-affairs JSONL")
    p.add_argument("--url", action="append", help="source URL; repeatable")
    p.add_argument("--url-file", help="text file with one URL per line")
    p.add_argument("--out-dir", default="./collected_sources", help="directory for raw downloaded files")
    p.add_argument("--output-jsonl", default="./current_affairs_collected.jsonl")
    p.add_argument("--kind", default="current_affairs", choices=SOURCE_KINDS, help="source kind to use when --ingest is set")
    p.add_argument("--source-name")
    p.add_argument("--title")
    p.add_argument("--published-at")
    p.add_argument("--version")
    p.add_argument("--tag", action="append", help="tag to store on collected records; repeatable")
    p.add_argument("--query", help="search/query context that led to these URLs")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--ingest", action="store_true", help="ingest the generated JSONL into --db as current_affairs")
    p.add_argument("--db")
    p.add_argument("--embed", action="store_true")
    p.add_argument("--no-embed", action="store_false", dest="embed")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--max-chars", type=int, default=900)
    p.add_argument("--dedup-threshold", type=float, default=0.9)
    p.add_argument("--semantic-dedup-threshold", type=float, default=0.985)
    p.add_argument("--allow-duplicate-chunks", action="store_true")
    p.set_defaults(func=cmd_collect_urls, embed=False)

    p = sub.add_parser("retrieve", help="retrieve evidence for inspection")
    p.add_argument("--db", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL, help="set empty string to disable semantic query embedding")
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--max-chars", type=int, default=900)
    p.set_defaults(func=cmd_retrieve)

    p = sub.add_parser("generate", help="generate evidence-gated exam questions")
    p.add_argument("--db", required=True)
    p.add_argument("--topic", required=True)
    p.add_argument("--question-type", default="single_choice", choices=["single_choice", "multiple_choice", "material_analysis", "short_answer"])
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    p.add_argument("--language", default="zh-CN")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--min-evidence", type=int, default=3)
    p.add_argument("--strict-current", action="store_true")
    p.add_argument("--task-id", help="exam task id whose outline/rules/coverage/prior items should constrain generation")
    p.add_argument("--prior-limit", type=int, default=50, help="number of prior task question runs to use for duplicate knowledge-point avoidance")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--llm-url", default=DEFAULT_LLM_URL)
    p.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.add_argument("--llm-verify", action="store_true")
    p.add_argument("--rewrite-on-fail", action="store_true", default=True)
    p.add_argument("--no-rewrite-on-fail", action="store_false", dest="rewrite_on_fail")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("review-question", help="record human reviewer approval, revision request, or rejection")
    p.add_argument("--db", required=True)
    p.add_argument("--question-id", required=True)
    p.add_argument("--decision", required=True, choices=["approved", "revise", "rejected"])
    p.add_argument("--reviewer")
    p.add_argument("--notes")
    p.add_argument("--patch", help="JSON string or JSON file path describing reviewer edits")
    p.set_defaults(func=cmd_review_question)

    p = sub.add_parser("audit-duplicates", help="audit duplicate fingerprints and chunks blocked during ingestion")
    p.add_argument("--db", required=True)
    p.add_argument("--backfill", action="store_true", help="create fingerprints for existing chunks before auditing")
    p.set_defaults(func=cmd_audit_duplicates)

    p = sub.add_parser("stats", help="show database counts")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("vacuum", help="vacuum the SQLite database")
    p.add_argument("--db", required=True)
    p.set_defaults(func=cmd_vacuum)
    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    started = time.time()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except ValidationError as exc:
        print(json.dumps({"ok": False, "error": "validation_failed", "issues": exc.issues}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        elapsed = time.time() - started
        if elapsed > 5:
            print(f"[done] {elapsed:.1f}s", file=sys.stderr)
    return 0
