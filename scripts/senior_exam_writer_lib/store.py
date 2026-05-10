from __future__ import annotations

import sqlite3

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

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          chunk_id UNINDEXED,
          title,
          path,
          text,
          tokenize = 'unicode61'
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

        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_layer ON chunks(layer);
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE INDEX IF NOT EXISTS idx_questions_task ON questions(task_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_question ON question_reviews(question_id);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_hash ON chunk_fingerprints(text_hash);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_layer ON chunk_fingerprints(layer);
        CREATE INDEX IF NOT EXISTS idx_duplicates_source ON ingest_duplicates(source_id);
        """
    )
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(questions)").fetchall()}
    if "task_id" not in existing_columns:
        conn.execute("ALTER TABLE questions ADD COLUMN task_id TEXT")
    conn.commit()

def ensure_db(conn: sqlite3.Connection) -> None:
    init_db(conn)
