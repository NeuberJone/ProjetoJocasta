from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

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
    base_dir = Path(getattr(cfg, "base_dir", r"C:\PXCore"))
    return base_dir / "data" / "printlogs.db"


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row  # permite dict(row)

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


def ensure_schema(con: sqlite3.Connection) -> None:
    # alias para evitar “ensure_schema não definido”
    init_schema(con)


def make_job_hash(machine: str, end_time: str, document: str, height_mm: float) -> str:
    raw = f"{machine}|{end_time}|{document}|{height_mm}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def make_source_hash(machine: str, roll_name: str, export_mode: str, orders: Iterable[OrderRow]) -> str:
    """
    Hash do "conteúdo exportado".
    Se tentar exportar exatamente o mesmo conjunto (mesma lista de orders normalizada),
    bloqueia como duplicado.
    """
    parts = [machine.strip(), roll_name.strip(), export_mode.strip()]
    normalized = sorted(
        (
            o.end_time,
            o.document,
            o.fabric,
            float(o.height_mm),
            float(o.real_m),
            Path(o.source_path).name,
        )
        for o in orders
    )
    parts.append(json.dumps(normalized, ensure_ascii=False))
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def log_event(
    con: sqlite3.Connection,
    event_type: str,
    ref_table: str,
    ref_id: int,
    payload: Optional[dict] = None,
) -> None:
    con.execute(
        "INSERT INTO events(created_at, event_type, ref_table, ref_id, payload_json) VALUES(?,?,?,?,?)",
        (_now_iso(), event_type, ref_table, int(ref_id), json.dumps(payload or {}, ensure_ascii=False)),
    )


def save_export_transactional(
    machine: str,
    roll_name: str,
    export_mode: str,
    app_version: str,
    orders: list[OrderRow],
    event_type: str = "EXPORT_ROLL",
    event_payload: Optional[dict] = None,
) -> int:
    """
    Salva 1 exportação (roll + orders + evento) de forma transacional.

    Regra:
    - Se source_hash já existir, NÃO cria novo roll nem reinsere orders.
      Apenas grava novo evento (reexport=True) e retorna o roll_id existente.

    Retorna roll_id.
    """
    con = connect()
    try:
        ensure_schema(con)

        source_hash = make_source_hash(machine, roll_name, export_mode, orders)

        payload = dict(event_payload or {})
        payload.setdefault("orders_count", len(orders))
        payload.setdefault("export_mode", export_mode)
        payload.setdefault("reexport", False)

        con.execute("BEGIN;")
        try:
            cur = con.execute(
                """
                INSERT INTO rolls(roll_name, machine, export_mode, created_at, source_hash, app_version)
                VALUES(?,?,?,?,?,?)
                """,
                (roll_name, machine, export_mode, _now_iso(), source_hash, app_version),
            )
            roll_id = int(cur.lastrowid)

            for o in orders:
                job_hash = make_job_hash(machine, o.end_time, o.document, o.height_mm)
                con.execute(
                    """
                    INSERT OR IGNORE INTO orders(
                        roll_id, end_time, document, fabric, height_mm, vpos_mm, real_m, source_path, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        roll_id,
                        o.end_time,
                        o.document,
                        o.fabric,
                        float(o.height_mm),
                        float(o.vpos_mm),
                        float(o.real_m),
                        o.source_path,
                        job_hash,
                    ),
                )

            log_event(con, event_type, "rolls", roll_id, payload)

            con.commit()
            return roll_id

        except sqlite3.IntegrityError:
            # duplicado pelo source_hash
            con.rollback()
            row = con.execute("SELECT id FROM rolls WHERE source_hash = ?", (source_hash,)).fetchone()
            if not row:
                raise

            roll_id = int(row["id"]) if isinstance(row, sqlite3.Row) else int(row[0])

            payload["reexport"] = True

            con.execute("BEGIN;")
            log_event(con, event_type, "rolls", roll_id, payload)
            con.commit()
            return roll_id

    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


def list_rolls(
    *,
    limit: int = 200,
    machine: Optional[str] = None,
    export_mode: Optional[str] = None,
    name_like: Optional[str] = None,
    order_like: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Lista rolls com métricas agregadas:
    - total_m (soma real_m)
    - orders_count
    - events_count

    Filtros:
    - name_like: filtra pelo nome do rolo (roll_name)
    - order_like: filtra rolos que tenham ao menos 1 order cujo document contenha o texto
    """
    con = connect()
    try:
        ensure_schema(con)

        where: list[str] = []
        params: list[Any] = []

        if machine:
            where.append("r.machine = ?")
            params.append(machine)

        if export_mode:
            where.append("r.export_mode = ?")
            params.append(export_mode)

        if name_like:
            where.append("r.roll_name LIKE ?")
            params.append(f"%{name_like}%")

        if order_like:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM orders o2
                    WHERE o2.roll_id = r.id
                      AND o2.document LIKE ?
                )
                """
            )
            params.append(f"%{order_like}%")

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        sql = f"""
        SELECT
            r.id,
            r.roll_name,
            r.machine,
            r.export_mode,
            r.created_at,
            r.app_version,
            COALESCE(SUM(o.real_m), 0) AS total_m,
            COUNT(DISTINCT o.id) AS orders_count,
            COUNT(DISTINCT e.id) AS events_count
        FROM rolls r
        LEFT JOIN orders o ON o.roll_id = r.id
        LEFT JOIN events e ON e.ref_table='rolls' AND e.ref_id = r.id
        {where_sql}
        GROUP BY r.id
        ORDER BY r.id DESC
        LIMIT ?
        """
        params.append(int(limit))

        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_roll_orders(roll_id: int) -> list[dict[str, Any]]:
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT id, end_time, document, fabric, height_mm, vpos_mm, real_m, source_path
            FROM orders
            WHERE roll_id = ?
            ORDER BY end_time DESC
            """,
            (int(roll_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_roll_events(roll_id: int) -> list[dict[str, Any]]:
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT id, created_at, event_type, payload_json
            FROM events
            WHERE ref_table='rolls' AND ref_id = ?
            ORDER BY id DESC
            """,
            (int(roll_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_roll_summary(roll_id: int) -> dict[str, Any]:
    con = connect()
    try:
        ensure_schema(con)

        r = con.execute(
            """
            SELECT id, roll_name, machine, export_mode, created_at, app_version
            FROM rolls
            WHERE id = ?
            """,
            (int(roll_id),),
        ).fetchone()
        if not r:
            return {}

        s = con.execute(
            """
            SELECT
                COALESCE(SUM(real_m), 0) AS total_m,
                COUNT(*) AS orders_count,
                MIN(end_time) AS oldest_end,
                MAX(end_time) AS newest_end
            FROM orders
            WHERE roll_id = ?
            """,
            (int(roll_id),),
        ).fetchone()

        fabrics = con.execute(
            """
            SELECT fabric, COUNT(*) AS n, COALESCE(SUM(real_m), 0) AS m
            FROM orders
            WHERE roll_id = ?
            GROUP BY fabric
            ORDER BY m DESC
            """,
            (int(roll_id),),
        ).fetchall()

        out = dict(r)
        out.update(dict(s or {}))
        out["fabrics"] = [dict(x) for x in fabrics]
        return out
    finally:
        con.close()