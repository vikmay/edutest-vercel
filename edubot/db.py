
# -*- coding: utf-8 -*-
"""
Minimal Postgres layer for serverless (pg8000).
Designed for Supabase (Free) or Neon (Free).
"""

import os, urllib.parse
import pg8000.native as pg

DATABASE_URL = os.environ.get("DATABASE_URL")  # e.g. postgres://user:pass@host:5432/db

def _parse_dsn(dsn: str):
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    u = urllib.parse.urlparse(dsn)
    return {
        "user": urllib.parse.unquote(u.username or ""),
        "password": urllib.parse.unquote(u.password or ""),
        "host": u.hostname or "localhost",
        "port": u.port or 5432,
        "database": (u.path or "/").lstrip("/"),
        "ssl_context": True  # Supabase/Neon require SSL
    }

def _connect():
    params = _parse_dsn(DATABASE_URL)
    return pg.Connection(**params)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  tg_id BIGINT PRIMARY KEY,
  full_name TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  points INTEGER NOT NULL DEFAULT 0,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
  id BIGSERIAL PRIMARY KEY,
  tg_id BIGINT NOT NULL REFERENCES users(tg_id),
  topic TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  score INTEGER,
  total INTEGER,
  details JSONB,
  timer_minutes INTEGER
);
CREATE TABLE IF NOT EXISTS user_topics (
  tg_id BIGINT NOT NULL,
  topic TEXT NOT NULL,
  points INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (tg_id, topic)
);
"""

def ensure_schema():
    con = _connect()
    try:
        con.run(SCHEMA_SQL)
    finally:
        con.close()

def ensure_user(tg_id: int, full_name: str = "") -> dict:
    con = _connect()
    try:
        row = con.run("SELECT tg_id, full_name, approved, points FROM users WHERE tg_id=:id", id=tg_id)
        if not row:
            con.run("INSERT INTO users (tg_id, full_name, approved, points) VALUES (:id, :nm, 0, 0)",
                    id=tg_id, nm=full_name or "")
            return {"tg_id": tg_id, "full_name": full_name or "", "approved": 0, "points": 0}
        r = row[0]
        return {"tg_id": r[0], "full_name": r[1], "approved": r[2], "points": r[3]}
    finally:
        con.close()

def set_user_name(tg_id: int, name: str):
    con = _connect()
    try:
        con.run("UPDATE users SET full_name=:nm WHERE tg_id=:id", nm=name, id=tg_id)
    finally:
        con.close()

def set_approved(tg_id: int, val: int):
    con = _connect()
    try:
        con.run("UPDATE users SET approved=:v WHERE tg_id=:id", v=int(val), id=tg_id)
    finally:
        con.close()

def get_user_points(tg_id: int) -> int:
    con = _connect()
    try:
        row = con.run("SELECT points FROM users WHERE tg_id=:id", id=tg_id)
        return int(row[0][0]) if row else 0
    finally:
        con.close()

def add_points(tg_id: int, pts: int, topic: str | None = None):
    con = _connect()
    try:
        con.run("UPDATE users SET points=points + :p WHERE tg_id=:id", p=int(pts), id=tg_id)
        if topic:
            con.run("""INSERT INTO user_topics (tg_id, topic, points)
                       VALUES (:id, :t, :p)
                       ON CONFLICT (tg_id, topic) DO UPDATE SET points = user_topics.points + EXCLUDED.points""",
                    id=tg_id, t=topic, p=int(pts))
    finally:
        con.close()

def top_scores(limit: int = 10, topic: str | None = None):
    con = _connect()
    try:
        if topic:
            q = """SELECT u.full_name, ut.points
                   FROM user_topics ut JOIN users u ON ut.tg_id=u.tg_id
                   WHERE u.approved=1 AND ut.topic=:t
                   ORDER BY ut.points DESC, u.full_name LIMIT :lim"""
            return con.run(q, t=topic, lim=int(limit))
        else:
            q = """SELECT full_name, points FROM users WHERE approved=1
                   ORDER BY points DESC, full_name LIMIT :lim"""
            return con.run(q, lim=int(limit))
    finally:
        con.close()

def list_pending():
    con = _connect()
    try:
        return con.run("SELECT tg_id, full_name FROM users WHERE approved=0")
    finally:
        con.close()

def start_session(tg_id: int, topic: str, total: int, timer_minutes: int) -> int:
    con = _connect()
    try:
        row = con.run("""INSERT INTO sessions (tg_id, topic, total, timer_minutes)
                         VALUES (:id, :topic, :tot, :tm) RETURNING id""",
                      id=tg_id, topic=topic, tot=int(total), tm=int(timer_minutes))
        return int(row[0][0])
    finally:
        con.close()

def finish_session(session_id: int, score: int, details: dict):
    con = _connect()
    try:
        con.run("""UPDATE sessions SET finished_at=now(), score=:s, details=:d WHERE id=:sid""",
                s=int(score), d=details, sid=int(session_id))
    finally:
        con.close()

def last_sessions(tg_id: int, limit: int = 10):
    con = _connect()
    try:
        return con.run("""SELECT id, topic, started_at, finished_at, score, total
                          FROM sessions WHERE tg_id=:id ORDER BY id DESC LIMIT :lim""",
                       id=tg_id, lim=int(limit))
    finally:
        con.close()
