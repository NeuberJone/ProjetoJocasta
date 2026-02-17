# core/printlogs_db.py
from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from core.config import load_config


@dataclass
class OrderRow:
    end_time: str
    document: str
    fabric: str
    height_mm: float
    vpos_mm: float
    real_m: float
    source_path: str


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_db_path() -> Path:
    cfg = load_config()
    base_dir = Path(getattr(cfg, "base_dir", "C:\\PXCore"))
    return base_dir / "data" / "printlogs.db"


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("PRAGMA synchronous = NORMAL;")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS rolls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_name TEXT NOT NULL,
            machine TEXT NOT NULL,
            export_mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_hash TEXT NOT NULL UNIQUE,
            app_version TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_id INTEGER NOT NULL,
            end_time TEXT,
            document TEXT,
            fabric TEXT,
            height_mm REAL,
            vpos_mm REAL,
            real_m REAL,
            source_path TEXT,
            job_hash TEXT NOT NULL,
            FOREIGN KEY (roll_id) REFERENCES rolls(id) ON DELETE CASCADE,
            UNIQUE (roll_id, job_hash)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ref_table TEXT NOT NULL,
            ref_id INTEGER NOT NULL,
            payload_json TEXT
        );

        CREATE TABLE IF NOT EXISTS order_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            delta_m REAL NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );
        """
    )
    con.commit()


def make_job_hash(machine: str, end_time: str, document: str, height_mm: float) -> str:
    raw = f"{machine}|{end_time}|{document}|{height_mm}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def make_source_hash(machine: str, roll_name: str, export_mode: str, orders: Iterable[OrderRow]) -> str:
    """
    Hash do "conteúdo exportado".
    Se tentar exportar exatamente o mesmo conjunto, bloqueia como duplicado.
    """
    parts = [machine.strip(), roll_name.strip(), export_mode.strip()]
    # ordena para ficar determinístico
    normalized = sorted(
        (o.end_time, o.document, o.fabric, float(o.height_mm), float(o.real_m), Path(o.source_path).name)
        for o in orders
    )
    parts.append(json.dumps(normalized, ensure_ascii=False))
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def log_event(con: sqlite3.Connection, event_type: str, ref_table: str, ref_id: int, payload: Optional[dict] = None) -> None:
    con.execute(
        "INSERT INTO events(created_at, event_type, ref_table, ref_id, payload_json) VALUES(?,?,?,?,?)",
        (_now_iso(), event_type, ref_table, ref_id, json.dumps(payload or {}, ensure_ascii=False)),
    )


def save_export_transactional(
    machine: str,
    roll_name: str,
    export_mode: str,
    app_version: str,
    orders: list[OrderRow],
) -> int:
    """
    Salva 1 exportação (roll + orders + evento) de forma transacional.
    Retorna roll_id.
    """
    con = connect()
    try:
        init_schema(con)

        source_hash = make_source_hash(machine, roll_name, export_mode, orders)

        # Transação
        con.execute("BEGIN;")

        # cria roll (ou falha se duplicado)
        cur = con.execute(
            """
            INSERT INTO rolls(roll_name, machine, export_mode, created_at, source_hash, app_version)
            VALUES(?,?,?,?,?,?)
            """,
            (roll_name, machine, export_mode, _now_iso(), source_hash, app_version),
        )
        roll_id = int(cur.lastrowid)

        # insere orders
        for o in orders:
            job_hash = make_job_hash(machine, o.end_time, o.document, o.height_mm)
            con.execute(
                """
                INSERT OR IGNORE INTO orders(
                    roll_id, end_time, document, fabric, height_mm, vpos_mm, real_m, source_path, job_hash
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (roll_id, o.end_time, o.document, o.fabric, o.height_mm, o.vpos_mm, o.real_m, o.source_path, job_hash),
            )

        # evento de export
        log_event(con, "EXPORT", "rolls", roll_id, {"orders_count": len(orders)})

        con.commit()
        return roll_id

    except sqlite3.IntegrityError as e:
        con.rollback()
        # geralmente aqui cai duplicidade do source_hash
        raise
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
