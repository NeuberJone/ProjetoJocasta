from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
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
    observacao: str = ""


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
            observacao TEXT,
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

        CREATE TABLE IF NOT EXISTS roll_order_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_id INTEGER NOT NULL,
            version_no INTEGER NOT NULL,
            orders_json TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            FOREIGN KEY (roll_id) REFERENCES rolls(id) ON DELETE CASCADE,
            UNIQUE (roll_id, version_no)
        );

        CREATE TABLE IF NOT EXISTS db_identity (
            id TEXT NOT NULL
        );
        """
    )
    con.commit()


def get_database_id(con: sqlite3.Connection) -> str:
    """Id curto e opaco GRAVADO NESTE ARQUIVO printlogs.db (tabela db_identity, uma única
    linha, gerada na primeira chamada que a encontrar vazia). Diferente de
    core.config.get_installation_id (esse é por instalação/máquina, na config local) — este
    aqui viaja COM o arquivo da base: uma cópia/restauração em outra máquina, ou várias
    instalações apontando pro mesmo arquivo (base_dir em pasta de rede compartilhada — ver
    connect(), comentário do journal_mode), preservam o MESMO valor, porque ele está dentro do
    próprio arquivo .db, não em configuração externa a ele. Usado para dar ao PX Tool Box uma
    forma de reconhecer que dois contextos vieram do MESMO arquivo de banco, mesmo que as
    exportações tenham sido feitas por instalações/máquinas diferentes."""
    row = con.execute("SELECT id FROM db_identity WHERE rowid = 1").fetchone()
    if row and row["id"]:
        return str(row["id"])

    # rowid fixo (1) + OR IGNORE: se duas instalações num base_dir de rede baterem nesta
    # primeira criação ao mesmo tempo, só uma INSERT vence — a outra é ignorada (nunca duas
    # linhas) — e o SELECT final sempre lê o valor que realmente persistiu, nunca o que esta
    # chamada tentou gravar, então as duas instalações convergem pro mesmo id.
    new_id = uuid.uuid4().hex[:12]
    con.execute("INSERT OR IGNORE INTO db_identity (rowid, id) VALUES (1, ?)", (new_id,))
    con.commit()
    row = con.execute("SELECT id FROM db_identity WHERE rowid = 1").fetchone()
    return str(row["id"]) if row else new_id


def _migrate_schema(con: sqlite3.Connection) -> None:
    cols = [row[1] for row in con.execute("PRAGMA table_info(orders)").fetchall()]
    if "pedido" not in cols:
        con.execute("ALTER TABLE orders ADD COLUMN pedido TEXT")
        con.commit()
    if "tipo" not in cols:
        con.execute("ALTER TABLE orders ADD COLUMN tipo TEXT")
        con.commit()
    if "observacao" not in cols:
        con.execute("ALTER TABLE orders ADD COLUMN observacao TEXT")
        con.commit()

    # roll_original_orders (só uma cópia, "o original") foi substituída por
    # roll_order_versions (uma cópia por edição: Original, Edição 1, Edição
    # 2...) — migra o que existir da tabela antiga como version_no=0 antes
    # de descartá-la, pra não perder o que já tinha sido preservado em
    # versões anteriores do Nexor.
    tables = {
        row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "roll_original_orders" in tables:
        already = {
            row[0] for row in con.execute("SELECT roll_id FROM roll_order_versions WHERE version_no = 0").fetchall()
        }
        for row in con.execute("SELECT roll_id, orders_json, saved_at FROM roll_original_orders").fetchall():
            if row["roll_id"] in already:
                continue
            con.execute(
                "INSERT INTO roll_order_versions(roll_id, version_no, orders_json, saved_at) VALUES(?,0,?,?)",
                (row["roll_id"], row["orders_json"], row["saved_at"]),
            )
        con.execute("DROP TABLE roll_original_orders")
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
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
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
                        o.observacao,
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
            COUNT(DISTINCT e.id) AS events_count,
            COUNT(DISTINCT CASE WHEN o.observacao IS NOT NULL AND o.observacao != '' THEN o.id END) AS obs_count
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
            SELECT id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao
            FROM orders
            WHERE roll_id = ?
            ORDER BY end_time DESC
            """,
            (int(roll_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_order_context(order_id: int) -> dict[str, Any] | None:
    """Pedido (linha de orders) e o rolo correspondente, para a exportação do contexto de
    pedido ao PX Tool Box (ver docs/integrations/nexor-order-context.md no repositório
    PXToolBox, seção 2) — SOMENTE LEITURA, nunca altera nenhuma coluna. Retorna None se o id
    não existir (nunca inventa um pedido vazio)."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            """
            SELECT o.id, o.roll_id, o.pedido, o.fabric, o.tipo, o.source_path, o.job_hash,
                   r.roll_name, r.machine
            FROM orders o
            JOIN rolls r ON r.id = o.roll_id
            WHERE o.id = ?
            """,
            (int(order_id),),
        ).fetchone()
        if row is None:
            return None

        result = dict(row)
        try:
            result["database_id"] = get_database_id(con)
        except Exception:
            # Melhor esforço, igual ao installation_id (core/config.py) — a exportação não
            # pode falhar só por isso; o campo opcional simplesmente não entra no documento.
            pass
        return result
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


def get_roll_summary(roll_id: int, *, group_consecutive_spaces: bool = False) -> dict[str, Any]:
    # Na Operação, os avanços entre tecidos (ESPAÇO) entram como orders com
    # tipo='' — agrupá-los junto com os tecidos (como se fossem um só) some
    # com a contagem individual, e os operadores da calandra conferem um a
    # um fisicamente. Por isso, só para rolos da Operação, eles ficam de
    # fora do agrupamento por tecido e saem numa lista à parte. Por padrão
    # cada avanço é uma linha; group_consecutive_spaces (opção em
    # Configurações) funde em uma linha só os avanços que se seguem direto,
    # sem nenhum tecido real entre eles na sequência física do rolo — dois
    # avanços separados por um tecido continuam em linhas separadas mesmo
    # com a opção ligada.
    # No Planejador, tipo também é sempre '' (nunca classificado), mas lá os
    # avanços nem chegam a virar order — então o agrupamento normal não
    # precisa dessa separação.
    module = get_roll_module(roll_id)

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

        if module == "Operacao":
            fabrics = con.execute(
                """
                SELECT fabric, COUNT(*) AS n, COALESCE(SUM(real_m), 0) AS m
                FROM orders
                WHERE roll_id = ? AND tipo <> ''
                GROUP BY fabric
                ORDER BY m DESC
                """,
                (int(roll_id),),
            ).fetchall()

            all_rows = con.execute(
                """
                SELECT fabric, tipo, end_time, real_m
                FROM orders
                WHERE roll_id = ?
                ORDER BY end_time ASC, id ASC
                """,
                (int(roll_id),),
            ).fetchall()

            spaces: list[dict] = []
            run: list[sqlite3.Row] = []

            def _flush_run() -> None:
                if not run:
                    return
                if group_consecutive_spaces and len(run) > 1:
                    spaces.append({
                        "fabric": run[0]["fabric"],
                        "real_m": sum(float(x["real_m"] or 0) for x in run),
                        "n": len(run),
                        "end_time": run[-1]["end_time"],
                    })
                else:
                    for x in run:
                        spaces.append({
                            "fabric": x["fabric"], "real_m": x["real_m"],
                            "n": 1, "end_time": x["end_time"],
                        })
                run.clear()

            for row in all_rows:
                if (row["tipo"] or "") == "":
                    run.append(row)
                else:
                    _flush_run()
            _flush_run()
        else:
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
            spaces = []

        out = dict(r)
        out.update(dict(s or {}))
        out["fabrics"] = [dict(x) for x in fabrics]
        out["spaces"] = [dict(x) for x in spaces]
        return out
    finally:
        con.close()


def find_pedido_fabric_rolls(
    pairs: Iterable[tuple[str, str]],
    *,
    exclude_roll_id: Optional[int] = None,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """
    Para cada par (pedido, tecido), retorna os rolos já salvos no banco que
    contêm esse mesmo par — usado para detectar duplicidade entre rolos
    (o mesmo pedido com o mesmo tecido impresso em mais de um rolo).

    `exclude_roll_id` tira o próprio rolo em edição/atualização do
    resultado — sem isso, fechar de novo (ou reabrir e "Atualizar Rolo")
    o MESMO rolo acusa duplicidade contra ele mesmo, o que não é duplicidade
    real nenhuma.
    """
    pairs = [(p.strip(), f.strip()) for p, f in pairs if p and f]
    if not pairs:
        return {}

    con = connect()
    try:
        ensure_schema(con)

        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for pedido, fabric in pairs:
            if exclude_roll_id is not None:
                rows = con.execute(
                    """
                    SELECT DISTINCT r.id AS roll_id, r.roll_name, r.machine, r.created_at
                    FROM orders o
                    JOIN rolls r ON r.id = o.roll_id
                    WHERE o.pedido = ? AND o.fabric = ? AND r.id != ?
                    ORDER BY r.created_at DESC
                    """,
                    (pedido, fabric, int(exclude_roll_id)),
                ).fetchall()
            else:
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

            # Antes de sobrescrever as orders, preserva o estado atual como
            # uma VERSÃO — a 1ª chamada guarda version_no=0 ("Original", o
            # rolo como fechou da 1ª vez), a 2ª guarda version_no=1
            # ("Edição 1", o estado depois da 1ª atualização), e assim por
            # diante. O estado mais recente de todos nunca precisa de cópia
            # própria — já é o que está em orders.
            next_version_row = con.execute(
                "SELECT COALESCE(MAX(version_no), -1) AS mx FROM roll_order_versions WHERE roll_id = ?",
                (int(roll_id),),
            ).fetchone()
            next_version_no = int(next_version_row["mx"]) + 1

            # Mesma ordenação de get_roll_orders (end_time DESC) — sem isso,
            # a versão guardada sai na ordem "natural" da tabela (ordem de
            # inserção, não cronológica), e ao reabrir essa versão depois a
            # lista aparece fora de ordem mesmo sem o conteúdo ter mudado.
            current_rows = con.execute(
                """
                SELECT end_time, document, fabric, pedido, tipo, height_mm, vpos_mm,
                       real_m, source_path, observacao
                FROM orders WHERE roll_id = ?
                ORDER BY end_time DESC
                """,
                (int(roll_id),),
            ).fetchall()
            con.execute(
                "INSERT INTO roll_order_versions(roll_id, version_no, orders_json, saved_at) VALUES(?,?,?,?)",
                (
                    int(roll_id),
                    next_version_no,
                    json.dumps([dict(r) for r in current_rows], ensure_ascii=False),
                    _now_iso(),
                ),
            )

            con.execute("DELETE FROM orders WHERE roll_id = ?", (int(roll_id),))

            for o in orders:
                job_hash = make_job_hash(machine, o.end_time, o.document, o.height_mm)
                con.execute(
                    """
                    INSERT OR IGNORE INTO orders(
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
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
                        o.observacao,
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


def was_roll_edited(roll_id: int) -> bool:
    """True quando esse rolo já foi atualizado pelo menos uma vez depois
    de fechado (ver update_roll_orders) — ou seja, existe pelo menos uma
    versão guardada em roll_order_versions."""
    return get_roll_order_version_count(roll_id) > 0


def get_roll_order_version_count(roll_id: int) -> int:
    """Quantas versões anteriores (Original, Edição 1, Edição 2...) estão
    guardadas pra esse rolo — não conta a versão atual (que é só o que
    está em orders, não precisa de cópia própria). 0 = nunca editado."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            "SELECT COUNT(*) AS n FROM roll_order_versions WHERE roll_id = ?", (int(roll_id),)
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        con.close()


def get_roll_order_version(roll_id: int, version_no: int) -> list[dict[str, Any]]:
    """Orders de uma versão anterior guardada (version_no=0 é "Original",
    1 é "Edição 1" etc. — ver update_roll_orders). [] se essa versão não
    existir (ex.: version_no inválido)."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            "SELECT orders_json FROM roll_order_versions WHERE roll_id = ? AND version_no = ?",
            (int(roll_id), int(version_no)),
        ).fetchone()
    finally:
        con.close()

    if not row or not row["orders_json"]:
        return []

    try:
        data = json.loads(row["orders_json"])
        if not isinstance(data, list):
            return []
        # Mesma ordenação de get_roll_orders (end_time DESC), aplicada na
        # leitura — cobre também versões guardadas antes da ordenação ter
        # sido adicionada à query de gravação (ver update_roll_orders).
        return sorted(data, key=lambda o: str(o.get("end_time") or ""), reverse=True)
    except Exception:
        return []


def get_roll_original_payload(roll_id: int) -> dict[str, Any]:
    """Payload do PRIMEIRO evento de exportação desse rolo (EXPORT_ROLL,
    sempre o fechamento inicial) — ao contrário de get_roll_latest_payload
    (o mais recente), usado para recuperar o caminho do comprovante
    ORIGINAL, de antes de qualquer "Atualizar Rolo"."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            """
            SELECT payload_json
            FROM events
            WHERE ref_table='rolls' AND ref_id = ? AND event_type = 'EXPORT_ROLL'
            ORDER BY id ASC
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

def reclassify_unmatched_orders(classify) -> int:
    """Reaplica as regras de tipo aos pedidos gravados como 'Fora do padrão'
    (ou sem tipo). Subtipos escolhidos à mão (Teste, Terceirizado...) não são
    tocados. `classify(document) -> tipo`. Retorna quantos foram alterados."""
    from core.print_types import FALLBACK_TYPE

    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT id, document FROM orders
            WHERE (tipo IS NULL OR tipo = '' OR tipo = ?)
              AND document IS NOT NULL AND document != ''
            """,
            (FALLBACK_TYPE,),
        ).fetchall()
        changed = 0
        for r in rows:
            new_tipo = classify(str(r["document"]))
            if new_tipo and new_tipo != FALLBACK_TYPE:
                con.execute("UPDATE orders SET tipo = ? WHERE id = ?", (new_tipo, int(r["id"])))
                changed += 1
        con.commit()
        return changed
    finally:
        con.close()
