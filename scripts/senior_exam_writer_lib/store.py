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
          prompt_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          output_json TEXT NOT NULL,
          verification_json TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_layer ON chunks(layer);
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        """
    )
    conn.commit()

def ensure_db(conn: sqlite3.Connection) -> None:
    init_db(conn)

