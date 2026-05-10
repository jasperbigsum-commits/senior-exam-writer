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
from urllib.parse import urlparse

from .collection import collect_exam_sources, collect_urls, read_url_list
from .common import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_EMBED_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_URL,
    DEFAULT_USER_AGENT,
    SOURCE_KINDS,
    now_iso,
    stable_id,
)
from .dedup import audit_duplicate_fingerprints, backfill_missing_fingerprints
from .evidence_planning import _collect_evidence_bundle, classify_support
from .generation import (
    build_candidate_prompt_record,
    build_generation_prompt,
    extract_json,
    refusal,
    rewrite_once,
    verify_static,
    verify_with_llm,
)
from .historical_review import THRESHOLD_POLICY, audit_candidate_batch, audit_question_batch
from .ingest import collect_files, ingest_file
from .llama_cpp_client import llama_chat
from .planning import build_planning_units
from .requirement_prompts import build_requirement_prompt_package, prompt_package_to_jsonl
from .retrieval import evidence_to_json, gate_evidence, retrieve_evidence
from .runtime import init_runtime_layout, persist_fetch_cache, probe_json
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
    validate_candidate_approval_gate,
    validate_candidate_review_decision,
    validate_evidence_contract,
    validate_generation_request,
    validate_ingest_request,
    validate_local_endpoint,
    validate_output_contract,
    validate_review_request,
    validate_task_completion,
)

def cmd_init_db(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    init_db(conn)
    print(json.dumps({"ok": True, "db": args.db}, ensure_ascii=False, indent=2))


def cmd_init_runtime(args: argparse.Namespace) -> None:
    validate_local_endpoint(args.embed_url, "embed_url")
    validate_local_endpoint(args.llm_url, "llm_url")
    runtime = init_runtime_layout(args.db, sidecar_root=args.sidecar_root)
    embed_probe = probe_json(args.embed_url)
    llm_probe = probe_json(args.llm_url)
    ok = bool(embed_probe.get("ok")) and bool(llm_probe.get("ok"))
    result = {
        "ok": ok,
        "runtime": runtime,
        "embed_probe": embed_probe,
        "llm_probe": llm_probe,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


def validate_embed_endpoint_when_used(embed: bool, embed_url: str) -> None:
    if embed:
        validate_local_endpoint(embed_url, "embed_url")


def cmd_ingest(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    validate_embed_endpoint_when_used(args.embed, args.embed_url)
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
        validate_embed_endpoint_when_used(args.embed, args.embed_url)
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


def cmd_collect_exam_sources(args: argparse.Namespace) -> None:
    urls = read_url_list(args.url, args.url_file)
    local_values = (args.local_path or []) + (args.input or [])
    local_paths = [Path(path) for path in local_values]
    if not urls and not local_paths:
        raise SystemExit("no sources provided; use --local-path, --input, --url, or --url-file")
    tags = args.tag or ["historical_exam"]
    result = collect_exam_sources(
        urls=urls,
        local_paths=local_paths,
        out_dir=Path(args.out_dir),
        jsonl_path=Path(args.output_jsonl),
        source_name=args.source_name,
        tags=tags,
        query=args.query,
        timeout=args.timeout,
        user_agent=args.user_agent,
    )
    whitelist_domains = {domain.lower() for domain in (args.whitelist_domain or []) if domain}
    for record in result["records"]:
        hostname = urlparse(str(record.get("url") or "")).hostname
        record["is_whitelisted"] = bool(hostname and hostname.lower() in whitelist_domains)
    if args.db:
        conn = connect(args.db)
        ensure_db(conn)
        persist_fetch_cache(conn, result["records"], False)
        if args.ingest:
            validate_embed_endpoint_when_used(args.embed, args.embed_url)
            ingest_result = ingest_file(
                conn,
                Path(args.output_jsonl),
                kind="historical_exam",
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
            ingest_result = {"kind": "historical_exam", **ingest_result}
        else:
            ingest_result = None
    elif args.ingest:
        raise SystemExit("--ingest requires --db")
    else:
        ingest_result = None
    print(json.dumps({"ok": True, **result, "ingested": ingest_result}, ensure_ascii=False, indent=2))


def cmd_split_requirements(args: argparse.Namespace) -> None:
    if args.requirements_file:
        requirement_text = Path(args.requirements_file).read_text(encoding="utf-8", errors="replace")
    else:
        requirement_text = args.requirements or ""
    package = build_requirement_prompt_package(
        requirement_text,
        task_name=args.task_name,
        language=args.language,
        writer_count=args.writer_count,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_jsonl:
        output_path = Path(args.output_jsonl)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(prompt_package_to_jsonl(package), encoding="utf-8")
    print(json.dumps({"ok": True, "prompt_package": package}, ensure_ascii=False, indent=2))

def cmd_retrieve(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    embed_url = args.embed_url if args.embed_url else None
    if embed_url:
        validate_local_endpoint(embed_url, "embed_url")
    evidence = retrieve_evidence(conn, args.query, top_k=args.top_k, embed_url=embed_url, embed_model=args.embed_model)
    print(json.dumps({"query": args.query, "evidence": evidence_to_json(evidence, max_chars=args.max_chars)}, ensure_ascii=False, indent=2))

def cmd_generate(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    validate_local_endpoint(args.embed_url, "embed_url")
    validate_local_endpoint(args.llm_url, "llm_url")
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


def cmd_generate_candidates(args: argparse.Namespace) -> None:
    if args.writer_count <= 0:
        raise ValueError("--writer-count must be greater than 0")
    conn = connect(args.db)
    ensure_db(conn)
    row = conn.execute(
        """
        SELECT *
        FROM planning_units
        WHERE id = ?
        """,
        (args.planning_unit_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"planning unit not found: {args.planning_unit_id}")

    try:
        raw_points = json.loads(row["knowledge_points_json"] or "[]")
    except json.JSONDecodeError:
        raw_points = []
    knowledge_points = [str(point) for point in raw_points if str(point).strip()] if isinstance(raw_points, list) else []

    evidence_rows = conn.execute(
        """
        SELECT claim_text, evidence_id
        FROM evidence_points
        WHERE planning_unit_id = ?
        ORDER BY created_at, id
        """,
        (args.planning_unit_id,),
    ).fetchall()
    evidence_points: dict[str, list[str]] = {}
    for evidence_row in evidence_rows:
        point = str(evidence_row["claim_text"] or "").strip()
        evidence_id = str(evidence_row["evidence_id"] or "").strip()
        if not point or not evidence_id:
            continue
        evidence_points.setdefault(point, []).append(evidence_id)

    created_at = now_iso()
    writer_round = int(row["writer_round"] or 0) + 1
    candidates: list[dict[str, Any]] = []
    for index in range(1, args.writer_count + 1):
        writer_id = f"writer-{index}"
        prompt_record = build_candidate_prompt_record(
            writer_id=writer_id,
            planning_unit_id=args.planning_unit_id,
            topic=args.topic,
            knowledge_points=knowledge_points,
            evidence_points=evidence_points,
        )
        candidate_id = str(uuid.uuid4())
        output_record = {"status": "pending"}
        verification_record = {"ok": False, "issues": []}
        conn.execute(
            """
            INSERT INTO candidate_questions
            (
              id, task_id, planning_unit_id, question_type, writer_id, round,
              prompt_json, output_json, verification_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                row["task_id"],
                args.planning_unit_id,
                row["question_type"] or "single_choice",
                writer_id,
                writer_round,
                json.dumps(prompt_record, ensure_ascii=False),
                json.dumps(output_record, ensure_ascii=False),
                json.dumps(verification_record, ensure_ascii=False),
                "pending_generation",
                created_at,
                created_at,
            ),
        )
        candidates.append(
            {
                "id": candidate_id,
                "planning_unit_id": args.planning_unit_id,
                "writer_id": writer_id,
                "round": writer_round,
                "prompt_json": prompt_record,
                "output_json": output_record,
                "verification_json": verification_record,
                "status": "pending_generation",
                "created_at": created_at,
            }
        )
    conn.execute(
        """
        UPDATE planning_units
        SET writer_round = ?, updated_at = ?
        WHERE id = ?
        """,
        (writer_round, created_at, args.planning_unit_id),
    )
    conn.commit()
    print(json.dumps({"ok": True, "candidates": candidates}, ensure_ascii=False, indent=2))


def cmd_audit_question_similarity(args: argparse.Namespace) -> None:
    validate_local_endpoint(args.embed_url, "embed_url")
    conn = connect(args.db)
    ensure_db(conn)
    question_id = getattr(args, "question_id", None)
    planning_unit_id = getattr(args, "planning_unit_id", None)
    task_id = getattr(args, "task_id", None)
    if question_id:
        rows = conn.execute(
            """
            SELECT *
            FROM questions
            WHERE id = ?
            """,
            (question_id,),
        ).fetchall()
        if not rows:
            raise ValueError(f"question not found: {question_id}")
        payload = audit_question_batch(conn, rows, args.embed_url, args.embed_model)
    else:
        if not planning_unit_id:
            raise ValueError("--planning-unit-id is required unless --question-id is provided")
        rows = conn.execute(
            """
            SELECT *
            FROM candidate_questions
            WHERE planning_unit_id = ?
            ORDER BY created_at, id
            """,
            (planning_unit_id,),
        ).fetchall()
        if not rows:
            raise ValueError(f"no candidate questions found for planning unit: {planning_unit_id}")
        payload = audit_candidate_batch(conn, rows, args.embed_url, args.embed_model)

    now = now_iso()
    threshold_json = json.dumps(THRESHOLD_POLICY, ensure_ascii=False)
    for result in payload:
        audit_id = str(uuid.uuid4())
        summary = {
            "audit_result": result["audit_result"],
            "top_score": result["top_score"],
            "matched_source_kind": result["matched_source_kind"],
            "matched_source_id": result["matched_source_id"],
            "matched_chunk_id": result["matched_chunk_id"],
            "candidate_text": result.get("candidate_text", "")[:500],
        }
        conn.execute(
            """
            INSERT INTO question_similarity_audits
            (
              id, candidate_question_id, question_id, task_id, embed_model, embed_url,
              threshold_policy_json, audit_result, audit_summary_json,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                result["candidate_id"],
                result.get("question_id"),
                task_id or (rows[0]["task_id"] if "task_id" in rows[0].keys() else None),
                args.embed_model,
                args.embed_url,
                threshold_json,
                result["audit_result"],
                json.dumps(summary, ensure_ascii=False),
                now,
            ),
        )
        if result.get("matched_chunk_id") or result.get("top_score", 0.0) > 0:
            conn.execute(
                """
                INSERT INTO question_similarity_hits
                (
                  id, audit_id, matched_source_kind, matched_source_id, matched_chunk_id,
                  matched_question_id, similarity_score, match_reason, snippet,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_id(
                        audit_id,
                        str(result.get("candidate_id") or result.get("question_id") or ""),
                        str(result.get("matched_chunk_id") or ""),
                    ),
                    audit_id,
                    result["matched_source_kind"],
                    result.get("matched_source_id"),
                    result.get("matched_chunk_id"),
                    result.get("matched_question_id"),
                    float(result.get("top_score") or 0.0),
                    result["match_reason"],
                    result["snippet"],
                    now,
                ),
            )
    conn.commit()
    print(json.dumps({"ok": True, "audits": payload}, ensure_ascii=False, indent=2))


def cmd_plan_knowledge(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    task = load_task_context(conn, args.task_id)
    if task is None:
        raise ValueError(f"task not found: {args.task_id}")
    units = build_planning_units(task)
    for unit in units:
        conn.execute(
            """
            INSERT OR REPLACE INTO planning_units
            (
              id, task_id, unit_type, title, objective, coverage_target, question_type, difficulty,
              knowledge_points_json, knowledge_status, evidence_status, writer_round, review_status,
              constraints_json, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                unit["id"],
                unit["task_id"],
                "knowledge_plan",
                unit["coverage_target"],
                unit["objective"],
                unit["coverage_target"],
                unit["question_type"],
                unit["difficulty"],
                json.dumps(unit["knowledge_points"], ensure_ascii=False),
                unit["knowledge_status"],
                unit["evidence_status"],
                unit["writer_round"],
                unit["review_status"],
                "{}",
                "{}",
                unit["created_at"],
                unit["updated_at"],
            ),
        )
    conn.commit()
    print(json.dumps({"ok": True, "planning_units": units}, ensure_ascii=False, indent=2))


def cmd_plan_evidence(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    validate_local_endpoint(args.embed_url, "embed_url")
    rows = conn.execute(
        """
        SELECT *
        FROM planning_units
        WHERE task_id = ?
          AND unit_type = 'knowledge_plan'
        ORDER BY created_at, id
        """,
        (args.task_id,),
    ).fetchall()
    payload: list[dict[str, Any]] = []
    for row in rows:
        try:
            knowledge_points = json.loads(row["knowledge_points_json"] or "[]")
        except json.JSONDecodeError:
            knowledge_points = []
        unit = {
            "id": row["id"],
            "task_id": row["task_id"],
            "coverage_target": row["coverage_target"] or row["title"],
            "question_type": row["question_type"] or "",
            "difficulty": row["difficulty"] or "",
            "knowledge_points": knowledge_points if isinstance(knowledge_points, list) else [],
            "knowledge_status": row["knowledge_status"] or "planned",
            "evidence_status": row["evidence_status"] or "pending",
            "writer_round": row["writer_round"] if row["writer_round"] is not None else 0,
            "review_status": row["review_status"] or "pending",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        bundle = _collect_evidence_bundle(conn, unit, args.embed_url, args.embed_model)
        result = {
            "planning_unit_id": unit["id"],
            "mapping": bundle["mapping"],
            "support_status": classify_support(bundle["mapping"]),
        }
        evidence_records = bundle["records"]
        conn.execute("DELETE FROM evidence_points WHERE planning_unit_id = ?", (unit["id"],))
        for point, evidence_ids in result["mapping"].items():
            records_by_id = {
                str(item.get("evidence_id") or ""): item
                for item in evidence_records.get(point, [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
            for evidence_id in evidence_ids:
                evidence_row = records_by_id.get(evidence_id, {})
                created_at = now_iso()
                conn.execute(
                    """
                    INSERT INTO evidence_points
                    (
                      id, planning_unit_id, evidence_id, source_id, chunk_id, support_status,
                      role, claim_text, citation_text, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_id(unit["id"], point, evidence_id),
                        unit["id"],
                        evidence_id,
                        evidence_row.get("source_id"),
                        evidence_row.get("chunk_id"),
                        result["support_status"],
                        "evidence_plan",
                        point,
                        evidence_id,
                        "{}",
                        created_at,
                    ),
                )
        conn.execute(
            """
            UPDATE planning_units
            SET evidence_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                result["support_status"],
                now_iso(),
                unit["id"],
            ),
        )
        payload.append(result)
    conn.commit()
    print(json.dumps({"ok": True, "evidence_points": payload}, ensure_ascii=False, indent=2))

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


def cmd_review_candidate(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    ensure_db(conn)
    validate_candidate_review_decision(args.decision, args.reason_code, args.notes)
    validate_candidate_approval_gate(conn, args.candidate_id, args.decision)
    now = now_iso()
    review_id = str(uuid.uuid4())
    review_json = {
        "route": args.reason_code,
        "decision": args.decision,
        "notes": args.notes,
    }
    conn.execute(
        """
        INSERT INTO candidate_reviews
        (id, candidate_question_id, reviewer, decision, reason_code, notes, review_json, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_id,
            args.candidate_id,
            args.reviewer,
            args.decision,
            args.reason_code,
            args.notes,
            json.dumps(review_json, ensure_ascii=False),
            now,
        ),
    )
    status_by_decision = {
        "approved_candidate": "approved_candidate",
        "revise_candidate": "revision_requested",
        "replan_required": "replan_required",
        "evidence_gap": "evidence_gap",
        "rejected_candidate": "rejected_candidate",
    }
    conn.execute(
        """
        UPDATE candidate_questions
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status_by_decision[args.decision], now, args.candidate_id),
    )
    if args.decision in {"replan_required", "evidence_gap"}:
        row = conn.execute(
            "SELECT planning_unit_id FROM candidate_questions WHERE id = ?",
            (args.candidate_id,),
        ).fetchone()
        if row and row["planning_unit_id"]:
            conn.execute(
                """
                UPDATE planning_units
                SET review_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (args.decision, now, row["planning_unit_id"]),
            )
    conn.commit()
    print(
        json.dumps(
            {
                "ok": True,
                "review": {
                    "id": review_id,
                    "candidate_question_id": args.candidate_id,
                    "decision": args.decision,
                    "reason_code": args.reason_code,
                    "reviewer": args.reviewer,
                    "notes": args.notes,
                    "reviewed_at": now,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


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

    p = sub.add_parser("init-runtime", help="create local runtime sidecar folders and probe local endpoints")
    p.add_argument("--db", required=True)
    p.add_argument("--sidecar-root")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--llm-url", default=DEFAULT_LLM_URL)
    p.set_defaults(func=cmd_init_runtime)

    p = sub.add_parser("split-requirements", help="split an entry requirement into executable stage prompts")
    p.add_argument("--requirements", help="natural-language requirement text")
    p.add_argument("--requirements-file", help="file containing natural-language requirement text")
    p.add_argument("--task-name")
    p.add_argument("--language", default="zh-CN")
    p.add_argument("--writer-count", type=int, default=3)
    p.add_argument("--output-json", help="optional path for the full prompt package JSON")
    p.add_argument("--output-jsonl", help="optional path for per-stage prompt JSONL")
    p.set_defaults(func=cmd_split_requirements)

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

    p = sub.add_parser("plan-knowledge", help="expand task coverage into planning units")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", required=True)
    p.set_defaults(func=cmd_plan_knowledge)

    p = sub.add_parser("plan-evidence", help="retrieve evidence support for planning units")
    p.add_argument("--db", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.set_defaults(func=cmd_plan_evidence)

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

    p = sub.add_parser("collect-exam-sources", help="collect local files and URLs into historical exam JSONL")
    p.add_argument("--db", help="optional SQLite DB used to persist fetch cache metadata")
    p.add_argument("--local-path", action="append", help="local file or directory; repeatable")
    p.add_argument("--input", action="append", help="alias for --local-path; repeatable")
    p.add_argument("--url", action="append", help="source URL; repeatable")
    p.add_argument("--url-file", help="text file with one URL per line")
    p.add_argument("--whitelist-domain", action="append", help="domain allowlist entries used for caller policy context")
    p.add_argument("--out-dir", default="./historical_downloads", help="directory for raw downloaded files")
    p.add_argument("--output-jsonl", default="./historical_exam_collected.jsonl")
    p.add_argument("--source-name")
    p.add_argument("--title")
    p.add_argument("--published-at")
    p.add_argument("--version")
    p.add_argument("--tag", action="append", help="tag to store on collected records; repeatable")
    p.add_argument("--query", help="search/query context that led to these sources")
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    p.add_argument("--ingest", action="store_true", help="ingest generated JSONL as historical_exam")
    p.add_argument("--embed", action="store_true")
    p.add_argument("--no-embed", action="store_false", dest="embed")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--max-chars", type=int, default=900)
    p.add_argument("--dedup-threshold", type=float, default=0.9)
    p.add_argument("--semantic-dedup-threshold", type=float, default=0.985)
    p.add_argument("--allow-duplicate-chunks", action="store_true")
    p.set_defaults(func=cmd_collect_exam_sources, embed=False)

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

    p = sub.add_parser("generate-candidates", help="create pending multi-writer candidate generation records")
    p.add_argument("--db", required=True)
    p.add_argument("--planning-unit-id", required=True)
    p.add_argument("--topic", required=True)
    p.add_argument("--writer-count", type=int, default=3)
    p.set_defaults(func=cmd_generate_candidates)

    p = sub.add_parser("audit-question-similarity", help="run local similarity review against historical and prior corpora")
    p.add_argument("--db", required=True)
    p.add_argument("--planning-unit-id")
    p.add_argument("--question-id")
    p.add_argument("--task-id")
    p.add_argument("--embed-url", default=DEFAULT_EMBED_URL)
    p.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    p.set_defaults(func=cmd_audit_question_similarity)

    p = sub.add_parser("review-candidate", help="review one candidate and route failures back to writers, planning, or evidence backfill")
    p.add_argument("--db", required=True)
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--reviewer")
    p.add_argument("--decision", required=True, choices=["approved_candidate", "revise_candidate", "replan_required", "evidence_gap", "rejected_candidate"])
    p.add_argument("--reason-code", required=True)
    p.add_argument("--notes", required=True)
    p.set_defaults(func=cmd_review_candidate)

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
