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
from core.logging_config import get_logger, log_exception
from core.sqlite_maintenance import DatabaseUnavailableError


_logger = get_logger(__name__)

# Marca de "rolo de teste" (ver Operação · caixa "Rolo de teste") — de propósito, só o nome
# do rolo carrega essa marca, sem coluna própria no banco: assim ela aparece automaticamente
# em TUDO que já exibe o nome do rolo (PDF, JPG, nome de arquivo, Registros), sem precisar
# duplicar lógica em cada lugar. Efeitos funcionais no banco hoje: find_pedido_fabric_rolls (ver
# comentário lá) nunca conta pedidos de um rolo de teste como "já impresso" em outro rolo;
# find_orders_by_source_path (mais abaixo) também ignora rolos de teste ao decidir qual foi a
# importação mais recente de um arquivo.
TEST_ROLL_SUFFIX = "_TESTE"

# Nomes de módulo gravados no payload do evento de exportação (ver
# `get_roll_module` abaixo) — duplicados aqui de propósito, nunca importados
# de `modules/planejador.py`/`modules/operacao/paths.py` (core/ não pode
# depender de modules/, mesma regra já documentada em core/fabrics.py).
# Incluem os nomes antigos (antes do rebrand pra Nexor) de propósito — sem
# isso, todo rolo exportado antes do rebrand (payload["module"] =
# "PXPrintCalc"/"PXPrintLogs") ficaria de fora de toda reconciliação,
# métrica e separação de avanço/tecido — achado real conferindo o banco de
# produção (16 rolos "PXPrintLogs", 27 "PXPrintCalc", sumindo dos dois
# lados). Mesmo mapeamento já usado em `modules/registros/ui.py:_EDIT_ROUTES`.
_PLANEJADOR_MODULE_NAMES = {"Planejador", "PXPrintCalc"}
_OPERACAO_MODULE_NAMES = {"Operacao", "PXPrintLogs"}


def is_test_roll_name(roll_name: str) -> bool:
    return str(roll_name or "").strip().upper().endswith(TEST_ROLL_SUFFIX)


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
    # Início real da impressão (campo "StartTime" do log) — "" quando não
    # disponível (log sem o campo, ou origem Planejador, que nunca tem
    # tempo real, só estimativa de metragem). Usado pra calcular duração
    # (fim - início) como métrica verificável, nunca pra nada além disso.
    start_time: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_db_path() -> Path:
    cfg = load_config()
    base_dir = Path(getattr(cfg, "base_dir", r"C:\PXCore"))
    return base_dir / "data" / "printlogs.db"


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    con = None
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(db_path), timeout=5.0)
        con.row_factory = sqlite3.Row  # permite dict(row)
        con.execute("PRAGMA busy_timeout = 5000;")
        con.execute("PRAGMA foreign_keys = ON;")
        # DELETE evita a memória compartilhada exigida por WAL em rede.
        # Ainda depende dos locks do filesystem: não garante concorrência
        # segura em qualquer servidor/cliente SMB.
        con.execute("PRAGMA journal_mode = DELETE;")
        con.execute("PRAGMA synchronous = NORMAL;")
        return con
    except (sqlite3.Error, OSError) as exc:
        if con is not None:
            con.close()
        log_exception(_logger, "SQLite connection unavailable", exc)
        raise DatabaseUnavailableError.from_exception(exc, operation="acessar o banco de dados") from exc


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
            start_time TEXT,
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

        -- order_id aqui é uma referência LÓGICA, sem FOREIGN KEY de propósito: update_roll_orders
        -- apaga e reinsere as orders de um rolo a cada edição, então orders.id não é estável
        -- entre edições. Uma FK real quebraria "Atualizar Rolo" (sem CASCADE) ou apagaria
        -- silenciosamente vínculos de vendedor já confirmados manualmente (com CASCADE) — as
        -- duas violam a regra de nunca sobrescrever silenciosamente uma correção manual. Editar
        -- um rolo nunca toca nestas tabelas; um vínculo pode ficar "órfão" (apontando pra um
        -- order_id que não existe mais) depois de uma edição, mas nunca é apagado.
        CREATE TABLE IF NOT EXISTS order_vendor_links (
            order_id INTEGER PRIMARY KEY,
            vendor_key TEXT NOT NULL,
            vendor_name_snapshot TEXT NOT NULL,
            origin TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_vendor_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            vendor_key TEXT NOT NULL,
            vendor_name_snapshot TEXT NOT NULL,
            origin TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );

        -- Mesma lógica/razão de order_vendor_links (ver comentário acima): order_id é uma
        -- referência lógica, sem FOREIGN KEY, porque não é estável entre edições de rolo (Etapa
        -- D — seleção do PDF original do pedido, em cima da pasta já localizada na Etapa B/C).
        CREATE TABLE IF NOT EXISTS order_pdf_links (
            order_id INTEGER PRIMARY KEY,
            pdf_path TEXT NOT NULL,
            origin TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_pdf_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            pdf_path TEXT NOT NULL,
            origin TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );

        -- "Registrar ocorrências operacionais" (roadmap Fase 3) — pedido do
        -- usuário. Uma ocorrência é vinculada ao ROLO inteiro (não a um
        -- pedido/item específico dentro dele — decisão confirmada com o
        -- usuário, item individual fica para depois, se precisar).
        -- occurrence_entries é a única fonte do CONTEÚDO (descrição/status)
        -- e funciona como histórico completo e append-only: cada edição
        -- grava uma linha NOVA em vez de sobrescrever a anterior (mesma
        -- técnica já usada em roll_order_versions pra histórico de
        -- edição) — "estado atual" é sempre a entrada de maior id/created_at
        -- daquela ocorrência; nada aqui é apagado ou sobrescrito.
        CREATE TABLE IF NOT EXISTS occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (roll_id) REFERENCES rolls(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS occurrence_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurrence_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
        );
        """
    )
    con.commit()


VENDOR_LINK_ORIGIN_AUTO = "auto"
VENDOR_LINK_ORIGIN_MANUAL = "manual"
VENDOR_LINK_STATUS_ACTIVE = "active"
VENDOR_LINK_STATUS_CLEARED = "cleared"
_VENDOR_LINK_ORIGINS = {VENDOR_LINK_ORIGIN_AUTO, VENDOR_LINK_ORIGIN_MANUAL}
_VENDOR_LINK_STATUSES = {VENDOR_LINK_STATUS_ACTIVE, VENDOR_LINK_STATUS_CLEARED}

PDF_LINK_ORIGIN_AUTO = "auto"
PDF_LINK_ORIGIN_MANUAL = "manual"
PDF_LINK_STATUS_ACTIVE = "active"
PDF_LINK_STATUS_CLEARED = "cleared"
_PDF_LINK_ORIGINS = {PDF_LINK_ORIGIN_AUTO, PDF_LINK_ORIGIN_MANUAL}
_PDF_LINK_STATUSES = {PDF_LINK_STATUS_ACTIVE, PDF_LINK_STATUS_CLEARED}


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
    if "start_time" not in cols:
        # Habilita duração (fim - início) como métrica verificável — até
        # aqui start_time só existia em memória (Job.start_time, lido do
        # campo "StartTime" do log real) e se perdia ao salvar o rolo.
        # Rolos salvos antes desta coluna existir ficam com start_time=''
        # (sem duração calculável, nunca um erro) — histórico incompleto,
        # não inválido.
        con.execute("ALTER TABLE orders ADD COLUMN start_time TEXT")
        con.commit()

    # roll_original_orders (só uma cópia, "o original") foi substituída por
    # roll_order_versions (uma cópia por edição: Original, Edição 1, Edição
    # 2...) — copia o que existir como version_no=0, preservando a tabela
    # legada e seu histórico. Reabrir a base não sobrescreve a versão
    # original que já tiver sido migrada.
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
                "INSERT OR IGNORE INTO roll_order_versions(roll_id, version_no, orders_json, saved_at) VALUES(?,0,?,?)",
                (row["roll_id"], row["orders_json"], row["saved_at"]),
            )
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
    except Exception as exc:
        log_exception(_logger, "SQLite roll sequence transaction failed", exc)
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
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao, start_time, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        o.start_time,
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

    except Exception as exc:
        log_exception(_logger, "SQLite roll export transaction failed", exc)
        try:
            con.rollback()
        except Exception as rollback_exc:
            log_exception(_logger, "SQLite roll export rollback failed", rollback_exc)
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
    pedido_like: Optional[str] = None,
    tipo: Optional[str] = None,
    vendor_key: Optional[str] = None,
    vendor_unidentified: bool = False,
) -> list[dict[str, Any]]:
    """
    Lista rolls com métricas agregadas:
    - total_m (soma real_m)
    - orders_count
    - events_count

    Filtros:
    - name_like: filtra pelo nome do rolo (roll_name)
    - order_like: filtra rolos que tenham ao menos 1 order cujo NOME DE ARQUIVO (document)
      contenha o texto — nunca confundir com pedido_like (abaixo): o nome do arquivo pode
      divergir do pedido já normalizado (ex.: Reposição tem pedido fixo configurado,
      diferente do nome real do arquivo reposto).
    - pedido_like: filtra rolos que tenham ao menos 1 order cujo PEDIDO já normalizado
      (o.pedido — o mesmo valor mostrado em "Pedidos no rolo"/Reconciliação) contenha o texto.
    - tipo: filtra rolos que tenham ao menos 1 order com esse tipo exato (Pedido/Reposição/...)
    - vendor_key: filtra rolos que tenham ao menos 1 order com vínculo ATIVO a este vendedor
      (ver order_vendor_links — Etapa A/C do recurso de identificação de vendedor)
    - vendor_unidentified: filtra rolos que tenham ao menos 1 order REAL (tipo não vazio —
      avanço/espaço nunca tem vendedor, então nunca conta aqui) sem vínculo de vendedor ativo.
      Mutuamente exclusivo com vendor_key na prática (a UI só usa um por vez), mas ambos podem
      ser passados juntos sem erro — neste caso as duas condições se somam com AND.
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

        if pedido_like:
            # Nunca confundir com order_like (acima): aquele filtra pelo
            # NOME DO ARQUIVO (document); este filtra pelo PEDIDO já
            # normalizado (o.pedido) — podem divergir de propósito (ex.:
            # Reposição tem pedido fixo "Variados" configurado, mas o nome
            # do arquivo continua sendo o nome real do item reposto).
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM orders o5
                    WHERE o5.roll_id = r.id
                      AND o5.pedido LIKE ?
                )
                """
            )
            params.append(f"%{pedido_like}%")

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

        if vendor_key:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM orders o4
                    JOIN order_vendor_links l4 ON l4.order_id = o4.id
                    WHERE o4.roll_id = r.id
                      AND l4.vendor_key = ?
                      AND l4.status = 'active'
                )
                """
            )
            params.append(vendor_key)

        if vendor_unidentified:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM orders o5
                    WHERE o5.roll_id = r.id
                      AND o5.tipo != ''
                      AND NOT EXISTS (
                          SELECT 1 FROM order_vendor_links l5
                          WHERE l5.order_id = o5.id AND l5.status = 'active'
                      )
                )
                """
            )

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
            SELECT id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao, start_time
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
        except Exception as exc:
            # Melhor esforço, igual ao installation_id (core/config.py) — a exportação não
            # pode falhar só por isso; o campo opcional simplesmente não entra no documento.
            log_exception(_logger, "SQLite optional database identity unavailable", exc)
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


OCCURRENCE_STATUS_OPEN = "Aberta"
OCCURRENCE_STATUS_RESOLVED = "Resolvida"
OCCURRENCE_STATUSES = (OCCURRENCE_STATUS_OPEN, OCCURRENCE_STATUS_RESOLVED)


def create_occurrence(roll_id: int, description: str, status: str = OCCURRENCE_STATUS_OPEN) -> int:
    """Registra uma ocorrência operacional nova, vinculada ao ROLO inteiro
    (ex.: "máquina travou", "tecido rasgado") — diferente da "Observação"
    livre já existente em orders.observacao. Grava a ocorrência
    (occurrences, só id/roll_id/created_at — nunca muda depois) e sua
    primeira entrada de histórico (occurrence_entries, com a descrição e o
    status) numa transação só. Devolve o id da ocorrência."""
    description = (description or "").strip()
    if not description:
        raise ValueError("Descrição da ocorrência não pode ser vazia.")
    if status not in OCCURRENCE_STATUSES:
        raise ValueError(f"Status inválido: {status!r}")

    con = connect()
    try:
        ensure_schema(con)
        now = _now_iso()
        cur = con.execute(
            "INSERT INTO occurrences(roll_id, created_at) VALUES (?, ?)",
            (int(roll_id), now),
        )
        occurrence_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO occurrence_entries(occurrence_id, created_at, description, status) VALUES (?, ?, ?, ?)",
            (occurrence_id, now, description, status),
        )
        con.commit()
        return occurrence_id
    finally:
        con.close()


def add_occurrence_entry(occurrence_id: int, description: str, status: str) -> int:
    """Edita uma ocorrência já existente — NUNCA sobrescreve a entrada
    anterior, grava uma NOVA (histórico completo, mesma técnica de
    roll_order_versions). Devolve o id da entrada criada."""
    description = (description or "").strip()
    if not description:
        raise ValueError("Descrição da ocorrência não pode ser vazia.")
    if status not in OCCURRENCE_STATUSES:
        raise ValueError(f"Status inválido: {status!r}")

    con = connect()
    try:
        ensure_schema(con)
        exists = con.execute(
            "SELECT 1 FROM occurrences WHERE id = ?", (int(occurrence_id),)
        ).fetchone()
        if not exists:
            raise ValueError(f"Ocorrência {occurrence_id} não encontrada.")

        cur = con.execute(
            "INSERT INTO occurrence_entries(occurrence_id, created_at, description, status) VALUES (?, ?, ?, ?)",
            (int(occurrence_id), _now_iso(), description, status),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def list_occurrences_for_roll(roll_id: int) -> list[dict[str, Any]]:
    """Ocorrências do rolo, cada uma no seu estado ATUAL (a entrada de
    histórico mais recente) — mais recente primeiro (por quando a
    ocorrência foi criada, não pela última edição)."""
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT
                o.id AS occurrence_id,
                o.created_at AS created_at,
                e.description AS description,
                e.status AS status
            FROM occurrences o
            JOIN occurrence_entries e ON e.id = (
                SELECT e2.id FROM occurrence_entries e2
                WHERE e2.occurrence_id = o.id
                ORDER BY e2.id DESC
                LIMIT 1
            )
            WHERE o.roll_id = ?
            ORDER BY o.id DESC
            """,
            (int(roll_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_occurrence_history(occurrence_id: int) -> list[dict[str, Any]]:
    """Histórico completo de uma ocorrência (todas as entradas, mais
    antiga primeiro) — a entrada mais recente é o estado atual."""
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            """
            SELECT id AS entry_id, created_at, description, status
            FROM occurrence_entries
            WHERE occurrence_id = ?
            ORDER BY id ASC
            """,
            (int(occurrence_id),),
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

        if module in _OPERACAO_MODULE_NAMES:
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

    Rolos de teste (nome terminado em "_TESTE" — ver TEST_ROLL_SUFFIX) nunca
    entram no resultado: um pedido impresso só num rolo de teste não é
    produção real, então nunca deve soar como "já impresso" quando o mesmo
    pedido/tecido for fechado de verdade depois.
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

            rows = [row for row in rows if not is_test_roll_name(row["roll_name"])]

            if rows:
                out[(pedido, fabric)] = [dict(row) for row in rows]

        return out
    finally:
        con.close()


def find_orders_by_source_path(paths: Iterable[str]) -> dict[str, dict[str, Any]]:
    """
    Para cada caminho de arquivo de origem (source_path, o mesmo
    `Job.src_file`) em `paths`, devolve o registro mais recente já salvo em
    algum rolo (não-teste) com esse mesmo arquivo — usado para detectar
    reimportação do MESMO arquivo físico entre sessões/rolos diferentes
    (importação incremental/idempotente): o mesmo caminho com o mesmo
    `job_hash` de antes é "já importado sem alteração"; o mesmo caminho com
    `job_hash` diferente é "alterado desde a última importação" (ver
    `modules/operacao/parser.py:classify_reimported_jobs`).

    Rolos de teste nunca entram no resultado (mesmo motivo de
    `find_pedido_fabric_rolls`: não é produção real, não deve suprimir a
    detecção quando o mesmo arquivo for importado de verdade depois).
    """
    paths = [p.strip() for p in paths if p and p.strip()]
    if not paths:
        return {}

    con = connect()
    try:
        ensure_schema(con)

        out: dict[str, dict[str, Any]] = {}
        # Em lotes para nunca ultrapassar o limite de parâmetros de uma
        # consulta SQLite (padrão 999), mesmo numa importação de pasta
        # inteira com muitos arquivos de uma vez.
        batch_size = 400
        for i in range(0, len(paths), batch_size):
            batch = paths[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = con.execute(
                f"""
                SELECT o.source_path, o.job_hash, o.height_mm, o.fabric, o.pedido,
                       r.id AS roll_id, r.roll_name, r.machine, r.created_at
                FROM orders o
                JOIN rolls r ON r.id = o.roll_id
                WHERE o.source_path IN ({placeholders})
                ORDER BY r.id DESC
                """,
                batch,
            ).fetchall()
            for row in rows:
                if is_test_roll_name(row["roll_name"]):
                    continue
                path = row["source_path"]
                if path not in out:  # primeira ocorrência = rolo mais recente (ORDER BY r.id DESC —
                    # created_at só tem resolução de segundo, insuficiente pra desempatar dois
                    # salvamentos próximos; o id autoincrement nunca empata).
                    out[path] = dict(row)

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


def _bulk_roll_modules(con: sqlite3.Connection, roll_ids: Iterable[int]) -> dict[int, str]:
    """Como `get_roll_module`, mas pra vários rolos de uma vez, na mesma
    conexão já aberta — evita N consultas (uma por rolo) numa reconciliação
    que pode cruzar dezenas de rolos de uma vez."""
    roll_ids = sorted({int(r) for r in roll_ids})
    if not roll_ids:
        return {}

    out: dict[int, str] = {}
    batch_size = 400
    for i in range(0, len(roll_ids), batch_size):
        batch = roll_ids[i : i + batch_size]
        placeholders = ",".join("?" for _ in batch)
        rows = con.execute(
            f"""
            SELECT ref_id AS roll_id, payload_json
            FROM events
            WHERE ref_table='rolls' AND ref_id IN ({placeholders})
              AND event_type IN ('EXPORT_ROLL', 'UPDATE_ROLL')
            ORDER BY id DESC
            """,
            batch,
        ).fetchall()
        for row in rows:
            roll_id = int(row["roll_id"])
            if roll_id in out:  # primeira ocorrência = evento mais recente (ORDER BY id DESC)
                continue
            try:
                data = json.loads(row["payload_json"] or "{}")
            except Exception:
                data = {}
            out[roll_id] = str(data.get("module", "") or "") if isinstance(data, dict) else ""

    return out


def reconcile_planned_vs_logged(
    pairs: Optional[Iterable[tuple[str, str]]] = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Para cada par (pedido, tecido), soma a metragem (`real_m`) gravada de
    cada lado — rolos salvos pelo Planejador (`length_m`, estimativa por
    pixels/DPI da imagem — ver `modules/planejador.py:_build_order_rows`) e
    rolos salvos pela Operação (medição do log real da impressora,
    `HeightMM`) — e devolve a diferença entre os dois totais, com os rolos
    de cada lado para rastreabilidade (nome, máquina, data).

    `pairs=None` (padrão) descobre todos os pares (pedido, tecido) que têm
    produção salva em qualquer rolo, de qualquer módulo — relatório
    completo. Passar pares específicos restringe a um subconjunto (ex.:
    reconciliar só os pedidos de um rolo recém-fechado).

    Read-only: nunca corrige nem toca nas tabelas de origem — só expõe a
    divergência pro operador decidir. Um par com produção só de um lado
    (planejado mas nunca confirmado por log, ou confirmado por log sem
    nunca ter sido planejado) tem o outro lado com metragem 0.0 e lista de
    rolos vazia — também é uma divergência real, nunca omitida.

    Rolo cujo módulo de origem não pôde ser determinado (evento de
    exportação ausente, ou payload sem o campo, de uma versão anterior a
    esse campo existir) não entra em nenhum dos dois lados — não há como
    reconciliar o que não se sabe de onde veio. Rolo exportado antes do
    rebrand pra Nexor (payload["module"] = "PXPrintCalc"/"PXPrintLogs")
    conta normalmente pro lado certo — ver `_PLANEJADOR_MODULE_NAMES`/
    `_OPERACAO_MODULE_NAMES`.
    """
    if pairs is not None:
        pairs = [(p.strip(), f.strip()) for p, f in pairs if p and f]
        if not pairs:
            return {}

    con = connect()
    try:
        ensure_schema(con)

        if pairs is None:
            pairs = [
                (row["pedido"], row["fabric"])
                for row in con.execute(
                    "SELECT DISTINCT pedido, fabric FROM orders WHERE pedido != '' AND fabric != ''"
                ).fetchall()
            ]
            if not pairs:
                return {}

        rows_by_pair: dict[tuple[str, str], list[sqlite3.Row]] = {}
        all_roll_ids: set[int] = set()
        for pedido, fabric in pairs:
            rows = con.execute(
                """
                SELECT o.real_m, r.id AS roll_id, r.roll_name, r.machine, r.created_at
                FROM orders o
                JOIN rolls r ON r.id = o.roll_id
                WHERE o.pedido = ? AND o.fabric = ?
                """,
                (pedido, fabric),
            ).fetchall()
            rows_by_pair[(pedido, fabric)] = rows
            all_roll_ids.update(int(row["roll_id"]) for row in rows)

        modules = _bulk_roll_modules(con, all_roll_ids)

        out: dict[tuple[str, str], dict[str, Any]] = {}
        for pair, rows in rows_by_pair.items():
            planned_m = 0.0
            logged_m = 0.0
            planned_rolls: list[dict[str, Any]] = []
            logged_rolls: list[dict[str, Any]] = []
            for row in rows:
                roll_id = int(row["roll_id"])
                roll_info = {
                    "roll_id": roll_id,
                    "roll_name": row["roll_name"],
                    "machine": row["machine"],
                    "created_at": row["created_at"],
                    "real_m": float(row["real_m"] or 0.0),
                }
                module = modules.get(roll_id, "")
                if module in _PLANEJADOR_MODULE_NAMES:
                    planned_m += roll_info["real_m"]
                    planned_rolls.append(roll_info)
                elif module in _OPERACAO_MODULE_NAMES:
                    logged_m += roll_info["real_m"]
                    logged_rolls.append(roll_info)

            if not planned_rolls and not logged_rolls:
                continue

            out[pair] = {
                "planned_m": planned_m,
                "logged_m": logged_m,
                "delta_m": logged_m - planned_m,
                "planned_rolls": planned_rolls,
                "logged_rolls": logged_rolls,
            }

        return out
    finally:
        con.close()


def compute_machine_metrics(
    date_from: Optional[str] = None, date_to: Optional[str] = None
) -> dict[str, dict[str, Any]]:
    """
    Métricas verificáveis por máquina — metragem produzida, metragem de
    avanço entre tecidos (ESPAÇO), contagens e duração — rastreáveis até os
    registros de origem (cada número é uma soma direta de colunas de
    `orders`, nunca um valor derivado/arredondado guardado à parte).

    Só considera rolos do módulo Operação (confirmados pelo log real da
    impressora) — nunca mistura com a estimativa do Planejador, que já tem
    seu próprio lugar de comparação (`reconcile_planned_vs_logged`); somar
    os dois aqui arriscaria contar a mesma produção física duas vezes
    quando o mesmo tecido passa pelos dois caminhos. Inclui rolo exportado
    antes do rebrand pra Nexor (payload["module"] = "PXPrintLogs") — ver
    `_OPERACAO_MODULE_NAMES`.

    Identificação de avanço (ESPAÇO) usa o mesmo critério já em produção em
    `get_roll_summary` (ver o comentário real lá): dentro de um rolo da
    Operação, `tipo == ''` é exclusivo de avanços — qualquer item real sem
    regra de tipo correspondente já cai em "Fora do padrão"
    (`core/print_types.py:FALLBACK_TYPE`), nunca fica com `tipo` vazio.

    `duration_minutes` soma (end_time - start_time) só das orders que têm
    `start_time` gravado (coluna nova; rolos salvos antes dela existir não
    contribuem, nunca travam o cálculo) E uma duração calculada POSITIVA
    (um "start_time"/"end_time" invertido ou idêntico, ex. por um glitch de
    relógio, é descartado dos dois lados — nunca soma minutos negativos,
    nem conta como "coberto" algo que não é uma duração de verdade) —
    `timed_order_count` informa quantas orders de fato contribuíram pra
    essa soma, pra nunca apresentar a duração total como se cobrisse toda a
    produção quando só cobre uma fração dela (ver
    `tests/test_compute_machine_metrics.py:test_negative_or_zero_duration_is_never_counted`).

    `date_from`/`date_to` (strings ISO, inclusive) filtram por
    `rolls.created_at` quando informados; `None` em qualquer um não limita
    aquele lado.
    """
    con = connect()
    try:
        ensure_schema(con)

        where = []
        params: list[Any] = []
        if date_from:
            where.append("r.created_at >= ?")
            params.append(date_from)
        if date_to:
            # Achado de revisão de código: comparação de string pura
            # ("<= date_to") excluía o dia inteiro quando o chamador passa
            # uma data sem hora (ex.: "2026-11-22") — created_at tem hora
            # ("2026-11-22T14:03:05"), e essa string É MAIOR que a data
            # sozinha na ordem lexicográfica, então nada daquele dia batia
            # com "<=", apesar do docstring documentar o filtro como
            # inclusivo. Completa com "T23:59:59.999999" só quando o valor
            # já não tem hora, pra continuar aceitando um datetime completo
            # sem mudar esse caso.
            date_to_param = date_to if "T" in date_to else f"{date_to}T23:59:59.999999"
            where.append("r.created_at <= ?")
            params.append(date_to_param)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        rows = con.execute(
            f"""
            SELECT o.real_m, o.tipo, o.start_time, o.end_time, r.id AS roll_id, r.machine
            FROM orders o
            JOIN rolls r ON r.id = o.roll_id
            {where_sql}
            """,
            params,
        ).fetchall()

        roll_ids = {int(row["roll_id"]) for row in rows}
        modules = _bulk_roll_modules(con, roll_ids)

        out: dict[str, dict[str, Any]] = {}
        roll_ids_by_machine: dict[str, set[int]] = {}
        for row in rows:
            roll_id = int(row["roll_id"])
            if modules.get(roll_id) not in _OPERACAO_MODULE_NAMES:
                continue

            machine = row["machine"] or ""
            metrics = out.setdefault(
                machine,
                {
                    "produced_m": 0.0,
                    "gap_m": 0.0,
                    "order_count": 0,
                    "gap_count": 0,
                    "duration_minutes": 0.0,
                    "timed_order_count": 0,
                },
            )
            roll_ids_by_machine.setdefault(machine, set()).add(roll_id)

            real_m = float(row["real_m"] or 0.0)
            is_gap = (row["tipo"] or "") == ""
            if is_gap:
                metrics["gap_m"] += real_m
                metrics["gap_count"] += 1
            else:
                metrics["produced_m"] += real_m
                metrics["order_count"] += 1

            start_raw = row["start_time"] or ""
            end_raw = row["end_time"] or ""
            if start_raw and end_raw:
                try:
                    delta_min = (datetime.fromisoformat(end_raw) - datetime.fromisoformat(start_raw)).total_seconds() / 60.0
                except Exception:
                    delta_min = 0.0
                if delta_min > 0:
                    metrics["duration_minutes"] += delta_min
                    metrics["timed_order_count"] += 1

        for machine, metrics in out.items():
            metrics["roll_count"] = len(roll_ids_by_machine.get(machine, ()))

        return out
    finally:
        con.close()


def list_rework_candidates() -> list[dict[str, Any]]:
    """Item de roadmap (Fase 3) "acompanhar retrabalho de forma explícita,
    distinguindo-o da impressão original". Candidato a retrabalho: o MESMO
    par (pedido, tecido) aparecendo em MAIS DE UM rolo da Operação
    (confirmado pelo log real — nunca mistura com a estimativa do
    Planejador) — o rolo com o `end_time` mais antigo é tratado como a
    impressão ORIGINAL, cada rolo seguinte como um possível RETRABALHO
    (reimpressão por defeito/erro). Critério deliberadamente amplo —
    pedido+tecido, não o nome do arquivo — decisão confirmada com o
    usuário: pega reimpressão mesmo que o arquivo tenha sido reexportado
    com outro nome, ao custo de poder incluir um pedido novo que só por
    coincidência repete o mesmo nome de pedido+tecido num dia diferente.

    Read-only, nunca corrige nem agrupa nada nas tabelas de origem — é um
    RELATÓRIO pro operador conferir. Decisão confirmada com o usuário:
    nenhuma métrica existente muda por causa disto (`compute_machine_metrics`
    continua somando retrabalho e original igualmente, exatamente como
    hoje) — só uma marcação nova, à parte.

    Devolve uma linha por (pedido, tecido, rolo de retrabalho) — um pedido
    com 1 original + 2 reimpressões gera 2 linhas, cada uma com o mesmo
    rolo original ao lado."""
    con = connect()
    try:
        ensure_schema(con)

        rows = con.execute(
            """
            SELECT o.pedido, o.fabric, o.real_m, o.end_time, r.id AS roll_id,
                   r.roll_name, r.machine, r.created_at
            FROM orders o
            JOIN rolls r ON r.id = o.roll_id
            WHERE o.pedido != '' AND o.fabric != ''
            """
        ).fetchall()

        roll_ids = {int(row["roll_id"]) for row in rows}
        modules = _bulk_roll_modules(con, roll_ids)

        groups: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        for row in rows:
            roll_id = int(row["roll_id"])
            if modules.get(roll_id) not in _OPERACAO_MODULE_NAMES:
                continue

            key = (row["pedido"], row["fabric"])
            per_roll = groups.setdefault(key, {})
            info = per_roll.setdefault(
                roll_id,
                {
                    "roll_id": roll_id,
                    "roll_name": row["roll_name"],
                    "machine": row["machine"],
                    "created_at": row["created_at"],
                    "real_m": 0.0,
                    "earliest_end_time": row["end_time"] or "",
                },
            )
            info["real_m"] += float(row["real_m"] or 0.0)
            end_time = row["end_time"] or ""
            if end_time and (not info["earliest_end_time"] or end_time < info["earliest_end_time"]):
                info["earliest_end_time"] = end_time

        out: list[dict[str, Any]] = []
        for (pedido, fabric), per_roll in groups.items():
            if len(per_roll) < 2:
                continue

            rolls_sorted = sorted(per_roll.values(), key=lambda r: r["earliest_end_time"])
            original = rolls_sorted[0]
            for rework in rolls_sorted[1:]:
                out.append(
                    {
                        "pedido": pedido,
                        "fabric": fabric,
                        "original_roll_id": original["roll_id"],
                        "original_roll_name": original["roll_name"],
                        "original_created_at": original["created_at"],
                        "original_real_m": original["real_m"],
                        "rework_roll_id": rework["roll_id"],
                        "rework_roll_name": rework["roll_name"],
                        "rework_created_at": rework["created_at"],
                        "rework_real_m": rework["real_m"],
                    }
                )

        out.sort(key=lambda e: (e["pedido"], e["fabric"], e["rework_created_at"]))
        return out
    finally:
        con.close()


def list_duplicate_export_groups() -> list[dict[str, Any]]:
    """Achado real durante a investigação do item de roadmap de retrabalho:
    reexportação duplicada do mesmo lote — o MESMO `roll_name` salvo mais
    de uma vez como rolos DIFERENTES no banco, com o MESMO conteúdo entre
    as orders. Diferente de `list_rework_candidates` (mesmo pedido+tecido,
    pode ser reimpressão de verdade): aqui o conteúdo é o mesmo, então é
    sempre reexportação acidental do mesmo lote, nunca retrabalho físico —
    mas conta em dobro em `compute_machine_metrics`/
    `reconcile_planned_vs_logged` hoje.

    "Mesmo conteúdo" depende do módulo de origem, achado ao investigar os
    pares reais do banco de produção: no Operação, `end_time` é o horário
    real de término da impressão (vindo do log da impressora) — igual
    entre duas exportações do MESMO job físico, então `job_hash` (que já
    usa isso, mesma definição de `find_orders_by_source_path`) identifica
    corretamente duas cópias do mesmo log. No Planejador não existe
    horário real — `end_time` é só a hora da própria exportação, igual
    pra TODAS as orders de um rolo e SEMPRE diferente entre duas
    exportações (mesmo da mesma fila, minutos depois) — usar `job_hash`
    ali faria duas cópias idênticas nunca baterem. Por isso, pra rolos do
    Planejador a comparação ignora `end_time` (usa documento + tecido +
    altura); pra Operação (e módulo desconhecido, de registros antigos
    sem o campo `module` no payload — mais seguro assumir o critério mais
    estrito) usa `job_hash` normalmente.

    Read-only, nunca corrige nem remove nada — é um RELATÓRIO pro operador
    conferir. Decisão confirmada com o usuário: nenhuma métrica existente
    muda por causa disto, só uma marcação nova, à parte (mesmo princípio
    de `list_rework_candidates`). Grupos com `roll_name` repetido mas
    conteúdo DIFERENTE (ex.: o rolo cresceu entre as duas exportações, sem
    usar "Atualizar Rolo") não entram aqui — não são duplicata, são uma
    atualização que criou um registro novo em vez de editar o existente.

    Devolve uma linha por `roll_name` duplicado, com a lista de cópias
    (mais antiga primeiro) e a metragem total de uma cópia (todas têm a
    mesma, por definição de "conteúdo idêntico")."""
    con = connect()
    try:
        ensure_schema(con)

        rolls = con.execute("SELECT id, roll_name, created_at FROM rolls ORDER BY created_at").fetchall()
        by_name: dict[str, list[dict[str, Any]]] = {}
        for r in rolls:
            by_name.setdefault(r["roll_name"], []).append({"roll_id": int(r["id"]), "created_at": r["created_at"]})

        candidate_names = [name for name, copies in by_name.items() if len(copies) > 1]
        if not candidate_names:
            return []

        all_roll_ids = [copy["roll_id"] for name in candidate_names for copy in by_name[name]]
        modules = _bulk_roll_modules(con, all_roll_ids)

        out: list[dict[str, Any]] = []
        for roll_name in candidate_names:
            copies = by_name[roll_name]
            is_planejador = modules.get(copies[0]["roll_id"], "") in _PLANEJADOR_MODULE_NAMES
            signatures: list[frozenset] = []
            totals: list[float] = []
            for copy in copies:
                order_rows = con.execute(
                    "SELECT document, fabric, height_mm, job_hash, real_m FROM orders WHERE roll_id = ?",
                    (copy["roll_id"],),
                ).fetchall()
                if is_planejador:
                    signatures.append(frozenset(
                        (row["document"], row["fabric"], round(float(row["height_mm"]), 3))
                        for row in order_rows
                    ))
                else:
                    signatures.append(frozenset(row["job_hash"] for row in order_rows))
                totals.append(sum(float(row["real_m"] or 0.0) for row in order_rows))

            if not signatures[0] or len(set(signatures)) != 1:
                continue  # sem orders, ou conteúdo diferente entre as cópias — não é duplicata

            out.append(
                {
                    "roll_name": roll_name,
                    "module": modules.get(copies[0]["roll_id"], ""),
                    "order_count": len(signatures[0]),
                    "real_m_per_copy": round(totals[0], 4),
                    "copies": copies,
                }
            )

        out.sort(key=lambda g: g["copies"][0]["created_at"])
        return out
    finally:
        con.close()


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
            # Achado de revisão de código: faltava `start_time` nesta lista
            # (igual faltava em get_roll_orders, corrigido junto) — a versão
            # arquivada perdia essa coluna pra sempre, mesmo a linha viva
            # tendo o valor; a nova INSERT abaixo já gravava corretamente,
            # só o SNAPSHOT de versão que ficava incompleto.
            current_rows = con.execute(
                """
                SELECT end_time, document, fabric, pedido, tipo, height_mm, vpos_mm,
                       real_m, source_path, observacao, start_time
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
                        roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, real_m, source_path, observacao, start_time, job_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        o.start_time,
                        job_hash,
                    ),
                )

            log_event(con, event_type, "rolls", int(roll_id), payload)

            con.commit()

        except Exception:
            con.rollback()
            raise
    except Exception as exc:
        log_exception(_logger, "SQLite roll update transaction failed", exc)
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


def _validate_vendor_link_fields(vendor_key: str, vendor_name_snapshot: str, origin: str, status: str) -> None:
    if not str(vendor_key or "").strip():
        raise ValueError("Informe o vendedor.")
    if not str(vendor_name_snapshot or "").strip():
        raise ValueError("Informe o nome do vendedor.")
    if origin not in _VENDOR_LINK_ORIGINS:
        raise ValueError(f"Origem de vínculo inválida: {origin!r}.")
    if status not in _VENDOR_LINK_STATUSES:
        raise ValueError(f"Status de vínculo inválido: {status!r}.")


def get_vendor_link(order_id: int) -> Optional[dict[str, Any]]:
    """Vínculo ATUAL (ativo ou limpo) de um pedido com um vendedor — None se
    este pedido nunca recebeu um vínculo. Ver get_vendor_link_history para o
    histórico completo (nunca sobrescrito/apagado)."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            "SELECT * FROM order_vendor_links WHERE order_id = ?", (int(order_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def upsert_vendor_link(
    order_id: int,
    *,
    vendor_key: str,
    vendor_name_snapshot: str,
    origin: str,
    status: str = VENDOR_LINK_STATUS_ACTIVE,
    note: str = "",
) -> dict[str, Any]:
    """Cria ou substitui o vínculo ATUAL de um pedido com um vendedor — no
    máximo um vínculo atual por order_id (PRIMARY KEY). A substituição nunca
    perde o vínculo anterior: cada chamada também grava uma linha em
    order_vendor_history (append-only), então o histórico completo sobrevive
    mesmo quando o vínculo atual é trocado."""
    _validate_vendor_link_fields(vendor_key, vendor_name_snapshot, origin, status)
    now = _now_iso()
    con = connect()
    try:
        ensure_schema(con)
        con.execute(
            """
            INSERT INTO order_vendor_links
                (order_id, vendor_key, vendor_name_snapshot, origin, status, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                vendor_key=excluded.vendor_key,
                vendor_name_snapshot=excluded.vendor_name_snapshot,
                origin=excluded.origin,
                status=excluded.status,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (int(order_id), vendor_key, vendor_name_snapshot, origin, status, note, now, now),
        )
        con.execute(
            """
            INSERT INTO order_vendor_history
                (order_id, vendor_key, vendor_name_snapshot, origin, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(order_id), vendor_key, vendor_name_snapshot, origin, status, note, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM order_vendor_links WHERE order_id = ?", (int(order_id),)).fetchone()
        return dict(row)
    finally:
        con.close()


def clear_vendor_link(order_id: int, *, note: str = "") -> bool:
    """Marca o vínculo atual de um pedido como 'cleared' (nunca DELETE) e
    grava a mudança no histórico. False sem alterar nada se este pedido não
    tiver vínculo atual; True se a limpeza foi aplicada."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute("SELECT * FROM order_vendor_links WHERE order_id = ?", (int(order_id),)).fetchone()
        if not row:
            return False
        now = _now_iso()
        con.execute(
            "UPDATE order_vendor_links SET status = ?, note = ?, updated_at = ? WHERE order_id = ?",
            (VENDOR_LINK_STATUS_CLEARED, note, now, int(order_id)),
        )
        con.execute(
            """
            INSERT INTO order_vendor_history
                (order_id, vendor_key, vendor_name_snapshot, origin, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(order_id), row["vendor_key"], row["vendor_name_snapshot"], row["origin"], VENDOR_LINK_STATUS_CLEARED, note, now),
        )
        con.commit()
        return True
    finally:
        con.close()


def list_vendor_links(
    *, vendor_key: Optional[str] = None, status: Optional[str] = None, limit: int = 500
) -> list[dict[str, Any]]:
    con = connect()
    try:
        ensure_schema(con)
        clauses = []
        params: list[Any] = []
        if vendor_key:
            clauses.append("vendor_key = ?")
            params.append(vendor_key)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = con.execute(
            f"SELECT * FROM order_vendor_links {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_vendor_link_history(order_id: int) -> list[dict[str, Any]]:
    """Histórico completo (append-only, nunca apagado) de vínculos de
    vendedor de um pedido, do mais antigo pro mais recente."""
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            "SELECT * FROM order_vendor_history WHERE order_id = ? ORDER BY id ASC", (int(order_id),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _validate_pdf_link_fields(pdf_path: str, origin: str, status: str) -> None:
    if not str(pdf_path or "").strip():
        raise ValueError("Informe o caminho do PDF.")
    if origin not in _PDF_LINK_ORIGINS:
        raise ValueError(f"Origem de vínculo inválida: {origin!r}.")
    if status not in _PDF_LINK_STATUSES:
        raise ValueError(f"Status de vínculo inválido: {status!r}.")


def get_pdf_link(order_id: int) -> Optional[dict[str, Any]]:
    """Vínculo ATUAL (ativo ou limpo) de um pedido com o PDF original
    escolhido como o arquivo impresso — None se este pedido nunca recebeu um
    vínculo de PDF. Ver get_pdf_link_history para o histórico completo
    (nunca sobrescrito/apagado)."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute(
            "SELECT * FROM order_pdf_links WHERE order_id = ?", (int(order_id),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def upsert_pdf_link(
    order_id: int,
    *,
    pdf_path: str,
    origin: str,
    status: str = PDF_LINK_STATUS_ACTIVE,
    note: str = "",
) -> dict[str, Any]:
    """Cria ou substitui o vínculo ATUAL de um pedido com um PDF original —
    no máximo um vínculo atual por order_id (PRIMARY KEY). A substituição
    nunca perde o vínculo anterior: cada chamada também grava uma linha em
    order_pdf_history (append-only), então o histórico completo sobrevive
    mesmo quando o vínculo atual é trocado (ex.: "Escolher outro PDF")."""
    _validate_pdf_link_fields(pdf_path, origin, status)
    now = _now_iso()
    con = connect()
    try:
        ensure_schema(con)
        con.execute(
            """
            INSERT INTO order_pdf_links
                (order_id, pdf_path, origin, status, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                pdf_path=excluded.pdf_path,
                origin=excluded.origin,
                status=excluded.status,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (int(order_id), pdf_path, origin, status, note, now, now),
        )
        con.execute(
            """
            INSERT INTO order_pdf_history
                (order_id, pdf_path, origin, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(order_id), pdf_path, origin, status, note, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM order_pdf_links WHERE order_id = ?", (int(order_id),)).fetchone()
        return dict(row)
    finally:
        con.close()


def clear_pdf_link(order_id: int, *, note: str = "") -> bool:
    """Marca o vínculo atual de PDF de um pedido como 'cleared' (nunca
    DELETE — "Desvincular PDF") e grava a mudança no histórico. False sem
    alterar nada se este pedido não tiver vínculo atual; True se a limpeza
    foi aplicada."""
    con = connect()
    try:
        ensure_schema(con)
        row = con.execute("SELECT * FROM order_pdf_links WHERE order_id = ?", (int(order_id),)).fetchone()
        if not row:
            return False
        now = _now_iso()
        con.execute(
            "UPDATE order_pdf_links SET status = ?, note = ?, updated_at = ? WHERE order_id = ?",
            (PDF_LINK_STATUS_CLEARED, note, now, int(order_id)),
        )
        con.execute(
            """
            INSERT INTO order_pdf_history
                (order_id, pdf_path, origin, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (int(order_id), row["pdf_path"], row["origin"], PDF_LINK_STATUS_CLEARED, note, now),
        )
        con.commit()
        return True
    finally:
        con.close()


def get_pdf_link_history(order_id: int) -> list[dict[str, Any]]:
    """Histórico completo (append-only, nunca apagado) de vínculos de PDF
    original de um pedido, do mais antigo pro mais recente."""
    con = connect()
    try:
        ensure_schema(con)
        rows = con.execute(
            "SELECT * FROM order_pdf_history WHERE order_id = ? ORDER BY id ASC", (int(order_id),)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()
