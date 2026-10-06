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
    pedido: str
    height_mm: float
    vpos_mm: float
    real_m: float
    source_path: str
    tipo: str = ""


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
    # DELETE (journal tradicional, baseado em lock de arquivo) em vez de WAL —
    # WAL depende de memória compartilhada (mmap) que não funciona de forma
    # confiável em pastas de rede, e o base_dir pode apontar pra uma pasta de
    # rede compartilhada entre vários computadores.
    con.execute("PRAGMA journal_mode = DELETE;")
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
            pedido TEXT,
            tipo TEXT,
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

        CREATE TABLE IF NOT EXISTS roll_sequence (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        );
        """
    )
    con.commit()


def _migrate_schema(con: sqlite3.Connection) -> None:
    cols = [row[1] for row in con.execute("PRAGMA table_info(orders)").fetchall()]
    if "pedido" not in cols:
        con.execute("ALTER TABLE orders ADD COLUMN pedido TEXT")
        con.commit()
    if "tipo" not in cols:
        con.execute("ALTER TABLE orders ADD COLUMN tipo TEXT")
        con.commit()


def ensure_schema(con: sqlite3.Connection) -> None:
    # alias para evitar “ensure_schema não definido”
    init_schema(con)
    _migrate_schema(con)


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


def next_roll_sequence() -> int:
    """
    Próximo número sequencial de rolo/lote, de forma atômica — seguro mesmo
    com vários computadores usando o mesmo banco compartilhado (base_dir
    apontando pra uma pasta de rede), já que o AUTOINCREMENT do SQLite
    garante que cada INSERT recebe um id novo e único, mesmo sob escrita
    concorrente no mesmo arquivo.
    """
    con = connect()
    try:
        ensure_schema(con)
        con.execute("BEGIN IMMEDIATE;")
        cur = con.execute("INSERT INTO roll_sequence DEFAULT VALUES")
        seq = int(cur.lastrowid)
        con.commit()
        return seq
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


def save_export_transactional(
    machine: str,
    roll_name: str,
    export_mode: str,
    app_version: str,
    orders: list[OrderRow],
    event_type: str = "EXPORT_ROLL",
    event_payload: Optional[dict] = None,
) -> tuple[int, bool]:
    """
    Salva 1 exportação (roll + orders + evento) de forma transacional.

    Regra:
    - Se source_hash já existir, NÃO cria novo roll nem reinsere orders.
      Apenas grava novo evento (reexport=True) e retorna o roll_id existente.

    Retorna (roll_id, is_new) — is_new=False quando o source_hash já existia
    (reexport do mesmo conteúdo) e nada novo foi inserido.
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
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        roll_id,
                        o.end_time,
                        o.document,
                        o.fabric,
                        o.pedido,
                        o.tipo,
                        float(o.height_mm),
                        float(o.vpos_mm),
                        float(o.real_m),
                        o.source_path,
                        job_hash,
                    ),
                )

            log_event(con, event_type, "rolls", roll_id, payload)

            con.commit()
            return roll_id, True

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
            return roll_id, False

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
    tipo: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Lista rolls com métricas agregadas:
    - total_m (soma real_m)
    - orders_count
    - events_count

    Filtros:
    - name_like: filtra pelo nome do rolo (roll_name)
    - order_like: filtra rolos que tenham ao menos 1 order cujo document contenha o texto
    - tipo: filtra rolos que tenham ao menos 1 order com esse tipo exato (Pedido/Reposição/...)
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

        if tipo:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM orders o3
                    WHERE o3.roll_id = r.id
                      AND o3.tipo = ?
                )
                """
            )
            params.append(tipo)

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
            SELECT id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path
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


def find_pedido_fabric_rolls(pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """
    Para cada par (pedido, tecido), retorna os rolos já salvos no banco que
    contêm esse mesmo par — usado para detectar duplicidade entre rolos
    (o mesmo pedido com o mesmo tecido impresso em mais de um rolo).
    """
    pairs = [(p.strip(), f.strip()) for p, f in pairs if p and f]
    if not pairs:
        return {}

    con = connect()
    try:
        ensure_schema(con)

        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for pedido, fabric in pairs:
            rows = con.execute(
                """
                SELECT DISTINCT r.id AS roll_id, r.roll_name, r.machine, r.created_at
                FROM orders o
                JOIN rolls r ON r.id = o.roll_id
                WHERE o.pedido = ? AND o.fabric = ?
                ORDER BY r.created_at DESC
                """,
                (pedido, fabric),
            ).fetchall()

            if rows:
                out[(pedido, fabric)] = [dict(row) for row in rows]

        return out
    finally:
        con.close()


def get_roll_latest_payload(roll_id: int) -> dict[str, Any]:
    """
    Payload (JSON) do evento mais recente de exportação/atualização desse
    rolo — usado para recuperar metadados que não têm coluna própria
    (módulo de origem, pedaço cortado associado etc.).
    """
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            """
            SELECT payload_json
            FROM events
            WHERE ref_table='rolls' AND ref_id = ?
              AND event_type IN ('EXPORT_ROLL', 'UPDATE_ROLL')
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(roll_id),),
        ).fetchone()
        if not row or not row["payload_json"]:
            return {}
        try:
            data = json.loads(row["payload_json"])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    finally:
        con.close()


def get_roll_module(roll_id: int) -> str:
    return str(get_roll_latest_payload(roll_id).get("module", "") or "")


def get_roll_scrap_key(roll_id: int) -> str:
    return str(get_roll_latest_payload(roll_id).get("scrap_key", "") or "")


def update_roll_orders(
    roll_id: int,
    machine: str,
    roll_name: str,
    export_mode: str,
    app_version: str,
    orders: list[OrderRow],
    event_type: str = "UPDATE_ROLL",
    event_payload: Optional[dict] = None,
) -> None:
    """
    Atualiza um rolo já registrado (mesmo roll_id) com um novo conjunto de
    orders — usado quando um rolo fechado é reaberto/editado (acrescentaram
    serviços nele) em vez de ser reexportado como um rolo novo e desconexo.

    Substitui por completo as orders desse roll_id pelo conjunto informado
    e grava um evento UPDATE_ROLL (ou o event_type informado) com o payload.
    """
    con = connect()
    try:
        ensure_schema(con)

        source_hash = make_source_hash(machine, roll_name, export_mode, orders)
        # Garante unicidade mesmo se o conteúdo coincidir com outro roll —
        # source_hash aqui é só auditoria, não é usado para dedupe no update.
        source_hash = hashlib.sha1(f"{source_hash}|roll:{int(roll_id)}".encode("utf-8")).hexdigest()

        payload = dict(event_payload or {})
        payload.setdefault("orders_count", len(orders))
        payload.setdefault("export_mode", export_mode)

        con.execute("BEGIN;")
        try:
            cur = con.execute("SELECT id FROM rolls WHERE id = ?", (int(roll_id),))
            if not cur.fetchone():
                raise ValueError(f"Rolo {roll_id} não encontrado.")

            con.execute(
                """
                UPDATE rolls
                SET roll_name = ?, machine = ?, export_mode = ?, app_version = ?, source_hash = ?
                WHERE id = ?
                """,
                (roll_name, machine, export_mode, app_version, source_hash, int(roll_id)),
            )

            con.execute("DELETE FROM orders WHERE roll_id = ?", (int(roll_id),))

            for o in orders:
                job_hash = make_job_hash(machine, o.end_time, o.document, o.height_mm)
                con.execute(
                    """
                    INSERT OR IGNORE INTO orders(
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        int(roll_id),
                        o.end_time,
                        o.document,
                        o.fabric,
                        o.pedido,
                        o.tipo,
                        float(o.height_mm),
                        float(o.vpos_mm),
                        float(o.real_m),
                        o.source_path,
                        job_hash,
                    ),
                )

            log_event(con, event_type, "rolls", int(roll_id), payload)

            con.commit()

        except Exception:
            con.rollback()
            raise

    finally:
        con.close()


def list_distinct_tipos() -> list[str]:
    """Tipos de impressão já registrados no banco (Pedido/Reposição/...) —
    usado para preencher o filtro de 'Tipo' no Registros."""
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT DISTINCT tipo FROM orders
            WHERE tipo IS NOT NULL AND tipo != ''
            ORDER BY tipo
            """
        ).fetchall()
        return [str(r["tipo"]) for r in rows]
    finally:
        con.close()