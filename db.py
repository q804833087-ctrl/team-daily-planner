"""数据库抽象层：本地 SQLite / 云端 PostgreSQL（Neon 免费版）"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "planner.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def use_postgres():
    return bool(DATABASE_URL)


def _pg_conn():
    import psycopg2
    import psycopg2.extras

    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    conn = psycopg2.connect(url, sslmode="require")
    conn.autocommit = False
    return conn


def _sqlite_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_connection():
    """打开连接，调用方负责 commit/close"""
    return _pg_conn() if use_postgres() else _sqlite_conn()


@contextmanager
def get_connection():
    conn = open_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row, columns):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(columns, row))


class DB:
    """统一查询接口"""

    def __init__(self, conn):
        self.conn = conn
        self._pg = use_postgres()

    def execute(self, sql, params=()):
        sql = self._adapt(sql)
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def fetchone(self, sql, params=()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        if self._pg:
            cols = [d[0] for d in cur.description]
            return _row_to_dict(row, cols)
        return dict(row)

    def fetchall(self, sql, params=()):
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        if self._pg:
            cols = [d[0] for d in cur.description]
            return [_row_to_dict(r, cols) for r in rows]
        return [dict(r) for r in rows]

    def run(self, sql, params=()):
        cur = self.execute(sql, params)
        return cur

    @property
    def lastrowid(self):
        if self._pg:
            cur = self.conn.cursor()
            cur.execute("SELECT lastval()")
            return cur.fetchone()[0]
        return None

    def _adapt(self, sql):
        if self._pg:
            return sql.replace("?", "%s")
        return sql


def init_schema(conn):
    db = DB(conn)
    if use_postgres():
        db.run(
            """
            CREATE TABLE IF NOT EXISTS daily_plans (
                id SERIAL PRIMARY KEY,
                member_name TEXT NOT NULL,
                plan_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                noon_submitted_at TEXT,
                evening_submitted_at TEXT,
                UNIQUE(member_name, plan_date)
            )
            """
        )
        db.run(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                plan_id INTEGER NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                noon_done INTEGER NOT NULL DEFAULT 0,
                evening_done INTEGER NOT NULL DEFAULT 0
            )
            """
        )
    else:
        db.run(
            """
            CREATE TABLE IF NOT EXISTS daily_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_name TEXT NOT NULL,
                plan_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                noon_submitted_at TEXT,
                evening_submitted_at TEXT,
                UNIQUE(member_name, plan_date)
            )
            """
        )
        db.run(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                noon_done INTEGER NOT NULL DEFAULT 0,
                evening_done INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (plan_id) REFERENCES daily_plans(id) ON DELETE CASCADE
            )
            """
        )


def history_date_filter(days: int):
    if use_postgres():
        return f"dp.plan_date >= (CURRENT_DATE - INTERVAL '{int(days)} days')::text"
    return f"dp.plan_date >= date('now', '-{int(days)} days')"
