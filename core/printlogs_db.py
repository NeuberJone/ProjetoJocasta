from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from core.config import load_config


def get_db_path() -> Path:
    cfg = load_config()
    base = Path(cfg.base_dir)
    return base / "data" / "printlogs.db"


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS print_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine TEXT NOT NULL,
            roll_name TEXT NOT NULL,
            end_time TEXT NOT NULL,
            document TEXT NOT NULL,
            height_mm REAL,
            vpos_mm REAL,
            real_m REAL,
            source_path TEXT NOT NULL,
            source_hash TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL,
            valid INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_doc ON print_jobs(document);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_roll ON print_jobs(roll_name);")
    con.execute("CREATE INDEX IF NOT EXISTS idx_print_jobs_end ON print_jobs(end_time);")


def file_sha1(path: str) -> str:
    h = hashlib.sha1()
    p = Path(path)
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class JobRow:
    machine: str
    roll_name: str
    end_time: datetime
    document: str
    height_mm: float
    vpos_mm: float
    real_m: float
    source_path: str


def upsert_jobs(con: sqlite3.Connection, jobs: Iterable[JobRow]) -> int:
    ensure_schema(con)
    now = datetime.now().isoformat(timespec="seconds")

    inserted = 0
    for j in jobs:
        sh = file_sha1(j.source_path)
        cur = con.execute(
            """
            INSERT OR IGNORE INTO print_jobs
            (machine, roll_name, end_time, document, height_mm, vpos_mm, real_m, source_path, source_hash, imported_at, valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1);
            """,
            (
                j.machine,
                j.roll_name,
                j.end_time.isoformat(timespec="seconds"),
                j.document,
                float(j.height_mm),
                float(j.vpos_mm),
                float(j.real_m),
                j.source_path,
                sh,
                now,
            ),
        )
        if cur.rowcount == 1:
            inserted += 1

    con.commit()
    return inserted


def find_orders(con: sqlite3.Connection, query: str, limit: int = 200):
    ensure_schema(con)
    q = f"%{query.strip()}%"
    cur = con.execute(
        """
        SELECT machine, roll_name, end_time, document, real_m, source_path, valid
        FROM print_jobs
        WHERE document LIKE ?
        ORDER BY end_time DESC
        LIMIT ?;
        """,
        (q, int(limit)),
    )
    return cur.fetchall()


def find_roll(con: sqlite3.Connection, roll_name: str, machine: str | None = None, limit: int = 500):
    ensure_schema(con)
    if machine:
        cur = con.execute(
            """
            SELECT machine, roll_name, end_time, document, real_m, source_path, valid
            FROM print_jobs
            WHERE roll_name = ? AND machine = ?
            ORDER BY end_time ASC
            LIMIT ?;
            """,
            (roll_name, machine, int(limit)),
        )
    else:
        cur = con.execute(
            """
            SELECT machine, roll_name, end_time, document, real_m, source_path, valid
            FROM print_jobs
            WHERE roll_name = ?
            ORDER BY end_time ASC
            LIMIT ?;
            """,
            (roll_name, int(limit)),
        )
    return cur.fetchall()
