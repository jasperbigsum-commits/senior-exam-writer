from __future__ import annotations

import sqlite3


QUESTION_TASK_ID_FK_NOTE = (
    "Legacy databases upgraded in place receive questions.task_id via ALTER TABLE, "
    "so SQLite cannot retroactively attach the REFERENCES exam_tasks(id) ON DELETE SET NULL "
    "constraint without rebuilding the table. Fresh databases get the foreign key; upgraded "
    "databases intentionally keep a nullable plain TEXT column for compatibility."
)

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          path TEXT,
          source_name TEXT,
          url TEXT,
          published_at TEXT,
          version TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
          parent_id TEXT REFERENCES chunks(id) ON DELETE CASCADE,
          layer TEXT NOT NULL CHECK(layer IN ('overview', 'toc', 'parent', 'content')),
          path TEXT,
          title TEXT,
          locator TEXT,
          text TEXT NOT NULL,
          token_count INTEGER NOT NULL DEFAULT 0,
          embedding_json TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
          id TEXT PRIMARY KEY,
          topic TEXT NOT NULL,
          question_type TEXT NOT NULL,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE SET NULL,
          prompt_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          output_json TEXT NOT NULL,
          verification_json TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exam_tasks (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          outline_json TEXT NOT NULL DEFAULT '{}',
          source_policy_json TEXT NOT NULL DEFAULT '{}',
          question_rules_json TEXT NOT NULL DEFAULT '{}',
          requirements_json TEXT NOT NULL DEFAULT '{}',
          coverage_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS question_reviews (
          id TEXT PRIMARY KEY,
          question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
          reviewer TEXT,
          decision TEXT NOT NULL CHECK(decision IN ('approved', 'revise', 'rejected')),
          notes TEXT,
          patch_json TEXT NOT NULL DEFAULT '{}',
          reviewed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunk_fingerprints (
          chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
          source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
          layer TEXT NOT NULL,
          text_hash TEXT NOT NULL,
          normalized_text TEXT NOT NULL,
          knowledge_key TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ingest_duplicates (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
          candidate_id TEXT NOT NULL,
          duplicate_of_chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
          layer TEXT NOT NULL,
          path TEXT,
          title TEXT,
          locator TEXT,
          text_hash TEXT NOT NULL,
          similarity REAL NOT NULL,
          reason TEXT NOT NULL,
          sample_text TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fetch_cache (
          cache_key TEXT PRIMARY KEY,
          url TEXT NOT NULL,
          response_status INTEGER,
          response_headers_json TEXT NOT NULL DEFAULT '{}',
          response_body_path TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          fetched_at TEXT NOT NULL,
          expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS planning_units (
          id TEXT PRIMARY KEY,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE,
          unit_type TEXT NOT NULL,
          title TEXT NOT NULL,
          objective TEXT,
          coverage_target TEXT,
          question_type TEXT,
          difficulty TEXT,
          knowledge_points_json TEXT NOT NULL DEFAULT '[]',
          knowledge_status TEXT NOT NULL DEFAULT 'planned',
          evidence_status TEXT NOT NULL DEFAULT 'pending',
          writer_round INTEGER NOT NULL DEFAULT 0,
          review_status TEXT NOT NULL DEFAULT 'pending',
          constraints_json TEXT NOT NULL DEFAULT '{}',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence_points (
          id TEXT PRIMARY KEY,
          planning_unit_id TEXT REFERENCES planning_units(id) ON DELETE CASCADE,
          evidence_id TEXT,
          source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
          chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL,
          support_status TEXT NOT NULL DEFAULT 'missing',
          role TEXT NOT NULL,
          claim_text TEXT NOT NULL,
          citation_text TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_questions (
          id TEXT PRIMARY KEY,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE,
          planning_unit_id TEXT REFERENCES planning_units(id) ON DELETE SET NULL,
          question_type TEXT NOT NULL,
          writer_id TEXT NOT NULL DEFAULT '',
          round INTEGER NOT NULL DEFAULT 0,
          prompt_json TEXT NOT NULL DEFAULT '{}',
          output_json TEXT NOT NULL DEFAULT '{}',
          verification_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_reviews (
          id TEXT PRIMARY KEY,
          candidate_question_id TEXT NOT NULL REFERENCES candidate_questions(id) ON DELETE CASCADE,
          reviewer TEXT,
          decision TEXT NOT NULL,
          reason_code TEXT NOT NULL DEFAULT '',
          notes TEXT,
          review_json TEXT NOT NULL DEFAULT '{}',
          reviewed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS question_similarity_audits (
          id TEXT PRIMARY KEY,
          candidate_question_id TEXT REFERENCES candidate_questions(id) ON DELETE CASCADE,
          question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE,
          embed_model TEXT NOT NULL DEFAULT '',
          embed_url TEXT NOT NULL DEFAULT '',
          threshold_policy_json TEXT NOT NULL DEFAULT '{}',
          audit_result TEXT NOT NULL DEFAULT '',
          audit_summary_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS question_similarity_hits (
          id TEXT PRIMARY KEY,
          audit_id TEXT NOT NULL REFERENCES question_similarity_audits(id) ON DELETE CASCADE,
          matched_source_kind TEXT NOT NULL DEFAULT '',
          matched_source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
          matched_chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL,
          matched_question_id TEXT,
          similarity_score REAL,
          match_reason TEXT NOT NULL DEFAULT '',
          snippet TEXT,
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_layer ON chunks(layer);
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE INDEX IF NOT EXISTS idx_reviews_question ON question_reviews(question_id);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON chunk_fingerprints(text_hash);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_layer ON chunk_fingerprints(layer);
        CREATE INDEX IF NOT EXISTS idx_duplicates_source ON ingest_duplicates(source_id);
        CREATE INDEX IF NOT EXISTS idx_planning_units_task ON planning_units(task_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_points_unit ON evidence_points(planning_unit_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_questions_task ON candidate_questions(task_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_questions_unit ON candidate_questions(planning_unit_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_reviews_question ON candidate_reviews(candidate_question_id);
        CREATE INDEX IF NOT EXISTS idx_similarity_audits_question ON question_similarity_audits(candidate_question_id);
        CREATE INDEX IF NOT EXISTS idx_similarity_hits_audit ON question_similarity_hits(audit_id);
        """
    )
    _ensure_questions_task_id_column(conn)
    _ensure_planning_units_columns(conn)
    _ensure_evidence_points_columns(conn)
    _ensure_candidate_questions_columns(conn)
    _ensure_candidate_reviews_columns(conn)
    _ensure_similarity_review_columns(conn)
    _drop_legacy_chunks_fts(conn)
    conn.commit()


def _column_name(row: sqlite3.Row | tuple[object, ...]) -> str:
    return row["name"] if isinstance(row, sqlite3.Row) else row[1]


def _ensure_questions_task_id_column(conn: sqlite3.Connection) -> None:
    existing_columns = {_column_name(row) for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
    if "task_id" in existing_columns:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id)")
        return
    # SQLite cannot add a foreign key constraint with ALTER TABLE ADD COLUMN.
    # We keep the upgrade path explicit so callers understand why fresh and upgraded
    # databases differ here; later tasks can rebuild the table if strict parity is needed.
    conn.execute("ALTER TABLE questions ADD COLUMN task_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id)")


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    existing_columns = {_column_name(row) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name in existing_columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _ensure_planning_units_columns(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "planning_units", "coverage_target", "coverage_target TEXT")
    _ensure_column(conn, "planning_units", "question_type", "question_type TEXT")
    _ensure_column(conn, "planning_units", "difficulty", "difficulty TEXT")
    _ensure_column(
        conn,
        "planning_units",
        "knowledge_points_json",
        "knowledge_points_json TEXT NOT NULL DEFAULT '[]'",
    )
    _ensure_column(
        conn,
        "planning_units",
        "knowledge_status",
        "knowledge_status TEXT NOT NULL DEFAULT 'planned'",
    )
    _ensure_column(
        conn,
        "planning_units",
        "evidence_status",
        "evidence_status TEXT NOT NULL DEFAULT 'pending'",
    )
    _ensure_column(
        conn,
        "planning_units",
        "writer_round",
        "writer_round INTEGER NOT NULL DEFAULT 0",
    )
    _ensure_column(
        conn,
        "planning_units",
        "review_status",
        "review_status TEXT NOT NULL DEFAULT 'pending'",
    )


def _ensure_evidence_points_columns(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "evidence_points", "evidence_id", "evidence_id TEXT")
    _ensure_column(
        conn,
        "evidence_points",
        "support_status",
        "support_status TEXT NOT NULL DEFAULT 'missing'",
    )


def _ensure_candidate_questions_columns(conn: sqlite3.Connection) -> None:
    _rebuild_candidate_questions_if_legacy(conn)
    _ensure_column(conn, "candidate_questions", "writer_id", "writer_id TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "candidate_questions", "round", "round INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "candidate_questions", "prompt_json", "prompt_json TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "candidate_questions", "output_json", "output_json TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "candidate_questions", "verification_json", "verification_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_candidate_reviews_columns(conn: sqlite3.Connection) -> None:
    _rebuild_candidate_reviews_if_legacy(conn)
    _ensure_column(conn, "candidate_reviews", "reason_code", "reason_code TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "candidate_reviews", "review_json", "review_json TEXT NOT NULL DEFAULT '{}'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_reviews_question ON candidate_reviews(candidate_question_id)")


def _ensure_similarity_review_columns(conn: sqlite3.Connection) -> None:
    _rebuild_similarity_audits_if_legacy(conn)
    _rebuild_similarity_hits_if_legacy(conn)
    _ensure_column(
        conn,
        "question_similarity_audits",
        "question_id",
        "question_id TEXT REFERENCES questions(id) ON DELETE CASCADE",
    )
    _ensure_column(
        conn,
        "question_similarity_audits",
        "task_id",
        "task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE",
    )
    _ensure_column(
        conn,
        "question_similarity_audits",
        "embed_model",
        "embed_model TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(conn, "question_similarity_audits", "embed_url", "embed_url TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn,
        "question_similarity_audits",
        "threshold_policy_json",
        "threshold_policy_json TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(
        conn,
        "question_similarity_audits",
        "audit_result",
        "audit_result TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        conn,
        "question_similarity_audits",
        "audit_summary_json",
        "audit_summary_json TEXT NOT NULL DEFAULT '{}'",
    )
    _ensure_column(conn, "question_similarity_audits", "created_at", "created_at TEXT NOT NULL DEFAULT ''")
    _ensure_column(
        conn,
        "question_similarity_hits",
        "matched_source_kind",
        "matched_source_kind TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(conn, "question_similarity_hits", "matched_question_id", "matched_question_id TEXT")
    _ensure_column(conn, "question_similarity_hits", "similarity_score", "similarity_score REAL")
    _ensure_column(conn, "question_similarity_hits", "match_reason", "match_reason TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "question_similarity_hits", "snippet", "snippet TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_similarity_audits_question ON question_similarity_audits(candidate_question_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_similarity_hits_audit ON question_similarity_hits(audit_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_similarity_audits_task ON question_similarity_audits(task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_similarity_audits_result ON question_similarity_audits(audit_result)")


def _drop_legacy_chunks_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS chunks_fts")


def _table_sql(conn: sqlite3.Connection, table_name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row["sql"] if isinstance(row, sqlite3.Row) else row[0]) if row else ""


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {_column_name(row) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _rebuild_candidate_questions_if_legacy(conn: sqlite3.Connection) -> None:
    existing_columns = _table_columns(conn, "candidate_questions")
    if not {"prompt_text", "draft_json", "metadata_json"} & existing_columns:
        return
    prompt_expr = "prompt_json" if "prompt_json" in existing_columns else "prompt_text"
    output_expr = "output_json" if "output_json" in existing_columns else "draft_json"
    verification_expr = "verification_json" if "verification_json" in existing_columns else _sql_literal("{}")
    writer_expr = "writer_id" if "writer_id" in existing_columns else _sql_literal("")
    round_expr = "round" if "round" in existing_columns else "0"
    conn.executescript(
        """
        ALTER TABLE candidate_questions RENAME TO candidate_questions_legacy;
        CREATE TABLE candidate_questions (
          id TEXT PRIMARY KEY,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE,
          planning_unit_id TEXT REFERENCES planning_units(id) ON DELETE SET NULL,
          question_type TEXT NOT NULL,
          writer_id TEXT NOT NULL DEFAULT '',
          round INTEGER NOT NULL DEFAULT 0,
          prompt_json TEXT NOT NULL DEFAULT '{}',
          output_json TEXT NOT NULL DEFAULT '{}',
          verification_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        f"""
        INSERT INTO candidate_questions
        (
          id, task_id, planning_unit_id, question_type, writer_id, round,
          prompt_json, output_json, verification_json, status, created_at, updated_at
        )
        SELECT
          id, task_id, planning_unit_id, question_type, {writer_expr}, {round_expr},
          {prompt_expr}, {output_expr}, {verification_expr}, status, created_at, updated_at
        FROM candidate_questions_legacy
        """
    )
    conn.execute("DROP TABLE candidate_questions_legacy")


def _rebuild_candidate_reviews_if_legacy(conn: sqlite3.Connection) -> None:
    table_sql = _table_sql(conn, "candidate_reviews")
    existing_columns = _table_columns(conn, "candidate_reviews")
    legacy_check = "CHECK(decision IN ('approved', 'revise', 'rejected'))" in table_sql
    if not legacy_check and "patch_json" not in existing_columns:
        return
    reason_expr = "reason_code" if "reason_code" in existing_columns else "''"
    review_expr = "review_json" if "review_json" in existing_columns else "'{}'"
    conn.executescript(
        """
        ALTER TABLE candidate_reviews RENAME TO candidate_reviews_legacy;
        CREATE TABLE candidate_reviews (
          id TEXT PRIMARY KEY,
          candidate_question_id TEXT NOT NULL REFERENCES candidate_questions(id) ON DELETE CASCADE,
          reviewer TEXT,
          decision TEXT NOT NULL,
          reason_code TEXT NOT NULL DEFAULT '',
          notes TEXT,
          review_json TEXT NOT NULL DEFAULT '{}',
          reviewed_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        f"""
        INSERT INTO candidate_reviews
        (id, candidate_question_id, reviewer, decision, reason_code, notes, review_json, reviewed_at)
        SELECT id, candidate_question_id, reviewer, decision, {reason_expr}, notes, {review_expr}, reviewed_at
        FROM candidate_reviews_legacy
        """
    )
    conn.execute("DROP TABLE candidate_reviews_legacy")


def _rebuild_similarity_audits_if_legacy(conn: sqlite3.Connection) -> None:
    existing_columns = _table_columns(conn, "question_similarity_audits")
    notnull_by_column = {
        _column_name(row): int(row["notnull"] if isinstance(row, sqlite3.Row) else row[3])
        for row in conn.execute("PRAGMA table_info(question_similarity_audits)").fetchall()
    }
    legacy_columns = {"compared_at", "threshold", "summary_json"} & existing_columns
    if not legacy_columns and notnull_by_column.get("candidate_question_id") != 1:
        return
    summary_expr = (
        "audit_summary_json"
        if "audit_summary_json" in existing_columns
        else "summary_json"
        if "summary_json" in existing_columns
        else _sql_literal("{}")
    )
    created_expr = (
        "CASE WHEN created_at IS NOT NULL AND created_at != '' THEN created_at ELSE compared_at END"
        if {"created_at", "compared_at"}.issubset(existing_columns)
        else "created_at"
        if "created_at" in existing_columns
        else "compared_at"
        if "compared_at" in existing_columns
        else _sql_literal("")
    )
    exprs = {
        "question_id": "question_id" if "question_id" in existing_columns else "NULL",
        "task_id": "task_id" if "task_id" in existing_columns else "NULL",
        "embed_model": "embed_model" if "embed_model" in existing_columns else "''",
        "embed_url": "embed_url" if "embed_url" in existing_columns else "''",
        "threshold_policy_json": "threshold_policy_json" if "threshold_policy_json" in existing_columns else "'{}'",
        "audit_result": "audit_result" if "audit_result" in existing_columns else "''",
        "audit_summary_json": summary_expr,
        "created_at": created_expr,
    }
    conn.executescript(
        """
        ALTER TABLE question_similarity_audits RENAME TO question_similarity_audits_legacy;
        CREATE TABLE question_similarity_audits (
          id TEXT PRIMARY KEY,
          candidate_question_id TEXT REFERENCES candidate_questions(id) ON DELETE CASCADE,
          question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
          task_id TEXT REFERENCES exam_tasks(id) ON DELETE CASCADE,
          embed_model TEXT NOT NULL DEFAULT '',
          embed_url TEXT NOT NULL DEFAULT '',
          threshold_policy_json TEXT NOT NULL DEFAULT '{}',
          audit_result TEXT NOT NULL DEFAULT '',
          audit_summary_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        f"""
        INSERT INTO question_similarity_audits
        (
          id, candidate_question_id, question_id, task_id, embed_model, embed_url,
          threshold_policy_json, audit_result, audit_summary_json,
          created_at
        )
        SELECT
          id, candidate_question_id, {exprs["question_id"]}, {exprs["task_id"]},
          {exprs["embed_model"]}, {exprs["embed_url"]}, {exprs["threshold_policy_json"]},
          {exprs["audit_result"]}, {exprs["audit_summary_json"]}, {exprs["created_at"]}
        FROM question_similarity_audits_legacy
        """
    )
    conn.execute("DROP TABLE question_similarity_audits_legacy")


def _rebuild_similarity_hits_if_legacy(conn: sqlite3.Connection) -> None:
    existing_columns = _table_columns(conn, "question_similarity_hits")
    if not {"similarity", "match_kind", "excerpt_text", "metadata_json"} & existing_columns:
        return
    similarity_expr = "similarity_score" if "similarity_score" in existing_columns else "similarity"
    reason_expr = (
        "CASE WHEN match_reason IS NOT NULL AND match_reason != '' THEN match_reason ELSE match_kind END"
        if {"match_reason", "match_kind"}.issubset(existing_columns)
        else "match_reason"
        if "match_reason" in existing_columns
        else "match_kind"
        if "match_kind" in existing_columns
        else _sql_literal("")
    )
    snippet_expr = (
        "CASE WHEN snippet IS NOT NULL AND snippet != '' THEN snippet ELSE excerpt_text END"
        if {"snippet", "excerpt_text"}.issubset(existing_columns)
        else "snippet"
        if "snippet" in existing_columns
        else "excerpt_text"
        if "excerpt_text" in existing_columns
        else "NULL"
    )
    exprs = {
        "matched_source_kind": "matched_source_kind" if "matched_source_kind" in existing_columns else "''",
        "matched_source_id": "matched_source_id" if "matched_source_id" in existing_columns else "NULL",
        "matched_chunk_id": "matched_chunk_id" if "matched_chunk_id" in existing_columns else "NULL",
        "matched_question_id": "matched_question_id" if "matched_question_id" in existing_columns else "NULL",
        "similarity_score": similarity_expr,
        "match_reason": reason_expr,
        "snippet": snippet_expr,
    }
    conn.executescript(
        """
        ALTER TABLE question_similarity_hits RENAME TO question_similarity_hits_legacy;
        CREATE TABLE question_similarity_hits (
          id TEXT PRIMARY KEY,
          audit_id TEXT NOT NULL REFERENCES question_similarity_audits(id) ON DELETE CASCADE,
          matched_source_kind TEXT NOT NULL DEFAULT '',
          matched_source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
          matched_chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL,
          matched_question_id TEXT,
          similarity_score REAL,
          match_reason TEXT NOT NULL DEFAULT '',
          snippet TEXT,
          created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        f"""
        INSERT INTO question_similarity_hits
        (
          id, audit_id, matched_source_kind, matched_source_id, matched_chunk_id,
          matched_question_id, similarity_score, match_reason, snippet, created_at
        )
        SELECT
          id, audit_id, {exprs["matched_source_kind"]}, {exprs["matched_source_id"]},
          {exprs["matched_chunk_id"]}, {exprs["matched_question_id"]},
          {exprs["similarity_score"]}, {exprs["match_reason"]}, {exprs["snippet"]}, created_at
        FROM question_similarity_hits_legacy
        """
    )
    conn.execute("DROP TABLE question_similarity_hits_legacy")


def ensure_db(conn: sqlite3.Connection) -> None:
    init_db(conn)
