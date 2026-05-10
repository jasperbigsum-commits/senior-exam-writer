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
from .common import DEFAULT_EMBED_MODEL, DEFAULT_EMBED_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_URL, DEFAULT_USER_AGENT, now_iso
from .generation import build_generation_prompt, extract_json, refusal, rewrite_once, verify_static, verify_with_llm
from .ingest import collect_files, ingest_file
from .llama_cpp_client import llama_chat
from .retrieval import evidence_to_json, gate_evidence, retrieve_evidence
from .store import connect, ensure_db, init_db

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
        conn = connect(args.db)
        ensure_db(conn)
        ingest_results.append(
            ingest_file(
                conn,
                Path(args.output_jsonl),
                kind="current_affairs",
                title=args.title,
                source_name=args.source_name,
                url=None,
                published_at=args.published_at,
                version=args.version,
                embed=args.embed,
                embed_url=args.embed_url,
                embed_model=args.embed_model,
                max_chars=args.max_chars,
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
    evidence = retrieve_evidence(
        conn,
        args.topic,
        top_k=args.top_k,
        embed_url=args.embed_url,
        embed_model=args.embed_model,
        layers={"parent", "content", "overview", "toc"},
    )
    ok, gate = gate_evidence(evidence, args.min_evidence, args.strict_current)
    prompt_record = {
        "topic": args.topic,
        "question_type": args.question_type,
        "count": args.count,
        "difficulty": args.difficulty,
        "min_evidence": args.min_evidence,
        "strict_current": args.strict_current,
    }
    if not ok:
        output = refusal(args.topic, gate, evidence)
        verification = {"ok": False, "mode": "gate", "issues": gate["issues"]}
        status = "refused"
    else:
        messages = build_generation_prompt(args.topic, args.question_type, args.count, args.difficulty, evidence, args.language)
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
                    )
                    verification = (
                        verify_with_llm(output, evidence, args.llm_url, args.llm_model)
                        if args.llm_verify
                        else verify_static(output, evidence)
                    )
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
        INSERT INTO questions(id, topic, question_type, prompt_json, evidence_json, output_json, verification_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            qid,
            args.topic,
            args.question_type,
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
              python scripts/senior_exam_writer.py ingest --db ./exam.sqlite --input ./materials --kind book --embed
              python scripts/senior_exam_writer.py retrieve --db ./exam.sqlite --query "共同富裕"
              python scripts/senior_exam_writer.py generate --db ./exam.sqlite --topic "共同富裕" --count 3 --llm-verify
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
    p.add_argument("--kind", default="book", choices=["book", "handout", "outline", "current_affairs", "notes"])
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
    p.set_defaults(func=cmd_ingest, embed=False)

    p = sub.add_parser("collect-urls", help="download URLs, extract text, and write current-affairs JSONL")
    p.add_argument("--url", action="append", help="source URL; repeatable")
    p.add_argument("--url-file", help="text file with one URL per line")
    p.add_argument("--out-dir", default="./collected_sources", help="directory for raw downloaded files")
    p.add_argument("--output-jsonl", default="./current_affairs_collected.jsonl")
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
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        elapsed = time.time() - started
        if elapsed > 5:
            print(f"[done] {elapsed:.1f}s", file=sys.stderr)
    return 0

