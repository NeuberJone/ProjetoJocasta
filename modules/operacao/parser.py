from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from core.fabrics import FabricEntry, canonical_fabric_name, load_fabrics, register_fabric_name
from core.operators import operator_name_for_code
from core.logging_config import get_logger, log_exception
from core.print_types import (
    DEFAULT_RULES,
    classify_document,
    normalize_rules,
    pedido_override_for_type,
    warn_duplicate_for_type,
)
from core.printers import Printer, find_printer_by_computer_name, find_printer_by_display_name
from core.printlogs_db import find_orders_by_source_path, find_pedido_fabric_rolls, make_job_hash
from .models import Job, Block, PedidoSummary
from .m1_check import STATUS_ERROR as _M1_STATUS_ERROR
from .m1_check import STATUS_UNKNOWN_FORMAT as _M1_STATUS_UNKNOWN_FORMAT
from .m1_check import check_job as _m1_check_job
from .paths import versioned_path
from .print_check import check_completeness

_logger = get_logger(__name__)

_RE_KV = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$")
_RE_SECTION = re.compile(r"^\s*\[(.+?)\]\s*$")
# Seção numérica do primeiro arquivo do job — normalmente "[1]", mas um
# gráfico de cor (teste direto da impressora, sem passar pelo fluxo normal
# de pedido) já apareceu com FileCount=2 numerado "[2]"/"[3]" em vez de
# "[1]"/"[2]" (visto num log real da Mimaki TS55 — achado real, não
# hipotético). Por isso nunca fixamos o nome "1": pegamos a primeira seção
# puramente numérica que aparecer, seja ela qual for.
_RE_NUMERIC_SECTION = re.compile(r"^\d+$")
_RE_TRAILING_EXT = re.compile(r"\.[A-Za-z0-9]{2,5}$")
# Parênteses no fim do nome são controle de separação (ex.: "(Argentina)", "(Brasil)", "(13)"),
# não fazem parte da identidade do pedido — "Salum 12 (Argentina)" e "Salum 12 (Brasil)" são o mesmo pedido.
_RE_TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def parse_datetime(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def _strip_trailing_parens(raw: str) -> tuple[str, bool]:
    """Remove parênteses no fim (um ou mais, ex.: "Dryfit (2)" ou
    "Salum 12 (Argentina) (2)"), que marcam ruído/observação e não fazem
    parte da identidade (nome do tecido ou do pedido) — ex.: "Dryfit (2).jpeg"
    é só "Dryfit", e "Salum 12 (Argentina)"/"Salum 12 (Brasil)" são o mesmo
    pedido "Salum 12". A observação em si continua visível no nome completo
    do documento, exibido nos relatórios."""
    had_paren = False
    while True:
        stripped = _RE_TRAILING_PAREN.sub("", raw).strip()
        if stripped == raw:
            break
        raw = stripped
        had_paren = True
    return raw, had_paren


def fabric_from_document(doc: str, fabrics_map: Optional[Dict[str, FabricEntry]] = None) -> str:
    """Nome do tecido extraído do documento — se `fabrics_map` for passado
    (cadastro de 'Tecidos e variações'), o nome extraído é canonicalizado por
    ele, de forma que aliases do mesmo tecido (ex.: "Dryfit", "Dry Fit",
    "Drifit") sejam sempre agrupados sob o mesmo nome, em vez de aparecerem
    como tecidos diferentes só porque o arquivo foi nomeado de outro jeito."""
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if len(parts) >= 2 and parts[1].strip():
        fabric = _RE_TRAILING_EXT.sub("", parts[1].strip()).strip()
        fabric, _ = _strip_trailing_parens(fabric)
        fabric = fabric.strip()
        if not fabric:
            return "DESCONHECIDO"
        if fabrics_map:
            canonical = canonical_fabric_name(fabric, fabrics_map)
            if canonical:
                fabric = canonical
        return fabric.upper()
    return "DESCONHECIDO"


def pedido_from_document(doc: str) -> str:
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if len(parts) < 3:
        return "DESCONHECIDO"

    raw = " - ".join(parts[2:]).strip()
    raw = _RE_TRAILING_EXT.sub("", raw)

    # Só o que estiver entre parênteses no fim é ignorado na identidade do
    # pedido (ver _strip_trailing_parens) — um número solto no fim, sem
    # parênteses, pode ser parte do próprio nome do pedido (ex.: "Haras DRB
    # 4" é o pedido inteiro, não "Haras DRB" + contador "4"), então não é
    # removido. "09-11 - Ribana - Haras DRB 4.jpeg" e "09-11 - Dryfit -
    # Haras DRB 4 (2).jpeg" são o mesmo pedido "Haras DRB 4" — o segundo só
    # tem "(2)" de observação (2ª peça), que o paren-strip já cobre.
    raw, _had_paren = _strip_trailing_parens(raw)

    raw = raw.strip()

    return raw if raw else "DESCONHECIDO"


_RE_OPERATOR_CODE = re.compile(r"^([A-Za-z]+)\s*\d+$")


def operator_code_from_document(doc: str) -> str:
    """Identificador do operador (ex.: 'N' em 'N1 - Dryfit', 'NJ' em
    'NJ2 - Tactel') — só quando o primeiro segmento do documento é
    iniciais + número (formato de Reposição). Em outros formatos (ex.:
    Pedido, que começa com uma data) não há operador, e a função retorna ""."""
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if not parts:
        return ""
    first = _RE_TRAILING_EXT.sub("", parts[0].strip()).strip()
    m = _RE_OPERATOR_CODE.match(first)
    return m.group(1).upper() if m else ""


def tipo_from_document(document: str, rules: Optional[Iterable[dict]] = None) -> str:
    """Tipo de impressão (Pedido, Reposição, Fora do padrão, ...) conforme as
    regras configuradas em 'Tipos de impressão…' — primeira regra que casar
    com o nome do documento vence."""
    return classify_document(document, rules if rules is not None else DEFAULT_RULES)


def _normalize_doc_name(name: str) -> str:
    name = (name or "").strip()
    name = _RE_TRAILING_EXT.sub("", name)
    return name.casefold()


def normalize_space_entries(raw: Optional[Iterable[object]]) -> List[dict]:
    """Normaliza a lista de arquivos de espaço cadastrados para
    {"filename": ..., "display_name": ...} — aceita tanto o formato novo
    (dict) quanto o antigo (string simples, migrado com display_name
    padrão "ESPAÇO")."""
    out: List[dict] = []
    for item in (raw or []):
        if isinstance(item, dict):
            filename = str(item.get("filename", "")).strip()
            display_name = str(item.get("display_name", "")).strip() or "ESPAÇO"
        else:
            filename = str(item or "").strip()
            display_name = "ESPAÇO"
        if filename:
            out.append({"filename": filename, "display_name": display_name})
    return out


def match_space_entry(document: str, space_entries: Optional[Iterable[dict]]) -> Optional[dict]:
    """Entrada de arquivo de espaço cadastrada que corresponde a `document`
    (nome do arquivo/job registrado no log), ou None — usado por máquinas
    que não têm gap automático entre tecidos e imprimem um arquivo dedicado
    como espaço."""
    if not space_entries:
        return None
    norm_doc = _normalize_doc_name(document)
    if not norm_doc:
        return None
    for entry in space_entries:
        if _normalize_doc_name(str(entry.get("filename", ""))) == norm_doc:
            return entry
    return None


def split_dnd_files(data: str) -> List[str]:
    """Separa a lista de caminhos recebida de um evento de arrastar-e-soltar
    do tkinterdnd2 (`event.data`) — cada caminho vem espaçado, mas um
    caminho com espaço no nome vem entre chaves (`{...}`). Extraído de
    `modules/operacao/ui.py:_split_dnd_files` (mesma lógica, sem Tkinter) —
    só o parsing do formato, sem depender de um evento real."""
    out: List[str] = []
    buff = ""
    in_brace = False

    for ch in data:
        if ch == "{":
            in_brace = True
            buff = ""
        elif ch == "}":
            in_brace = False
            if buff:
                out.append(buff)
            buff = ""
        elif ch == " " and not in_brace:
            if buff:
                out.append(buff)
                buff = ""
        else:
            buff += ch

    if buff.strip():
        out.append(buff.strip())

    return [p.strip() for p in out if p.strip()]


def read_log_general_fields(path: str) -> Dict[str, str]:
    """Lê só a seção [General] de um log .txt (ex.: ComputerName, Document,
    EndTime), sem exigir que o resto do arquivo seja válido — usada pra
    identificar/pré-visualizar o arquivo (ex.: detectar automaticamente a
    impressora de origem pelo ComputerName) antes do parse completo."""
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        log_exception(_logger, "Printer log metadata read failed", exc)
        return {}

    section = None
    general: Dict[str, str] = {}
    for line in txt:
        msec = _RE_SECTION.match(line)
        if msec:
            section = msec.group(1).strip()
            continue
        mkv = _RE_KV.match(line)
        if not mkv:
            continue
        if section == "General":
            general[mkv.group(1).strip()] = mkv.group(2).strip()
    return general


def detect_machine_from_logs(
    paths: Iterable[str], printers: Optional[List[Printer]] = None
) -> Optional[str]:
    """Olha o campo ComputerName (seção [General]) dos logs sendo
    importados e, se todos vierem do mesmo computador e esse computador
    estiver cadastrado numa impressora (Gerenciamento → Impressoras),
    sugere essa máquina — evita o operador ter que lembrar/escolher na mão
    toda vez. Só sugere quando não há ambiguidade; senão retorna None e a
    escolha continua manual. Extraído de
    `modules/operacao/ui.py:_detect_machine_from_logs` (mesma lógica, sem
    Tkinter) — `printers`, quando informado, substitui o cadastro real
    (`core.printers.load_printers`), só para possibilitar testes sem
    depender da configuração em disco."""
    names = set()
    for path in paths:
        cn = (read_log_general_fields(path).get("ComputerName") or "").strip()
        if cn:
            names.add(cn)
    if len(names) != 1:
        return None
    printer = find_printer_by_computer_name(next(iter(names)), printers)
    return printer.display_name if printer else None


def parse_log_txt(
    path: str,
    space_entries: Optional[Iterable[dict]] = None,
    type_rules: Optional[Iterable[dict]] = None,
    operators: Optional[Iterable[dict]] = None,
    fabrics_map: Optional[Dict[str, FabricEntry]] = None,
) -> Optional[Job]:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:
        log_exception(_logger, "Printer log read failed", exc)
        return None

    section = None
    first_item_section = None
    general = {}
    costs = {}
    item1 = {}

    for line in txt:
        msec = _RE_SECTION.match(line)
        if msec:
            section = msec.group(1).strip()
            if first_item_section is None and _RE_NUMERIC_SECTION.match(section):
                first_item_section = section
            continue

        mkv = _RE_KV.match(line)
        if not mkv:
            continue

        k, v = mkv.group(1).strip(), mkv.group(2).strip()
        if section == "General":
            general[k] = v
        elif section == "Costs":
            costs[k] = v
        elif section == first_item_section:
            item1[k] = v

    end_dt = parse_datetime(general.get("EndTime", ""))
    if not end_dt:
        return None

    start_dt = parse_datetime(general.get("StartTime", ""))

    document = general.get("Document") or item1.get("Name") or Path(path).stem

    def _f(x: str) -> float:
        x = (x or "").strip().replace(",", ".")
        try:
            return float(x)
        except Exception:
            return 0.0

    height_mm = _f(item1.get("HeightMM", "0"))
    width_mm = _f(item1.get("WidthMM", "0"))
    vpos_mm = _f(item1.get("VPositionMM", "0"))
    real_mm = height_mm

    try:
        file_count = int(_f(general.get("FileCount", "1")))
    except Exception:
        file_count = 1
    print_height_mm = _f(costs["PrintHeightMM"]) if "PrintHeightMM" in costs else None
    completeness = check_completeness(
        height_mm=height_mm, vpos_mm=vpos_mm, print_height_mm=print_height_mm, file_count=file_count
    )

    space_match = match_space_entry(document, space_entries)
    is_gap = space_match is not None
    if is_gap:
        display_name = str(space_match.get("display_name") or "ESPAÇO")
        fabric = display_name
        pedido = display_name
        tipo = ""
        operador = ""
    else:
        fabric = fabric_from_document(document, fabrics_map)
        tipo = tipo_from_document(document, type_rules)
        pedido_fixed = pedido_override_for_type(tipo, type_rules)
        pedido = pedido_fixed if pedido_fixed is not None else pedido_from_document(document)
        operador = operator_name_for_code(operator_code_from_document(document), operators)

    return Job(
        end_time=end_dt,
        document=document,
        fabric=fabric,
        pedido=pedido,
        height_mm=height_mm,
        vpos_mm=vpos_mm,
        real_mm=real_mm,
        src_file=str(path),
        is_gap=is_gap,
        tipo=tipo,
        operador=operador,
        width_mm=width_mm,
        start_time=start_dt,
        print_status=completeness.status,
        print_status_detail=completeness.detail,
    )


def build_auto_gap_job(job: Job) -> Optional[Job]:
    """Algumas impressoras não imprimem um arquivo dedicado pra marcar o
    espaço entre tecidos — elas deixam esse avanço em branco automaticamente
    e só registram o quanto avançaram no próprio log do arquivo real
    seguinte, no campo VPositionMM. Quando isso acontece (`job.vpos_mm > 0`
    num item que não é ele mesmo um arquivo de espaço cadastrado), esse
    avanço precisa entrar na listagem como um item de ESPAÇO próprio —
    senão aquela metragem em branco do rolo fica invisível. Retorna None
    quando não há avanço a registrar (vpos_mm == 0 ou o próprio job já é
    um ESPAÇO)."""
    if job.is_gap or job.vpos_mm <= 0:
        return None

    gap_end = job.start_time or (job.end_time - timedelta(seconds=1))

    return Job(
        end_time=gap_end,
        document=f"{job.document} (avanço)",
        fabric="ESPAÇO",
        pedido="ESPAÇO",
        height_mm=job.vpos_mm,
        vpos_mm=0.0,
        real_mm=job.vpos_mm,
        src_file=f"{job.src_file}::gap",
        is_gap=True,
        tipo="",
        operador="",
        width_mm=0.0,
        start_time=None,
    )


def build_blocks(jobs: List[Job], machine: str) -> List[Block]:
    jobs_sorted = sorted(jobs, key=lambda j: j.end_time, reverse=True)

    blocks: List[Block] = []
    current_jobs: List[Job] = []
    current_fabric: Optional[str] = None

    for j in jobs_sorted:
        if current_fabric is None:
            current_fabric = j.fabric
            current_jobs = [j]
            continue

        if j.fabric == current_fabric:
            current_jobs.append(j)
        else:
            blocks.append(Block(fabric=current_fabric, machine=machine, Jobs=current_jobs))
            current_fabric = j.fabric
            current_jobs = [j]

    if current_fabric is not None and current_jobs:
        blocks.append(Block(fabric=current_fabric, machine=machine, Jobs=current_jobs))

    return blocks


def _group_tipo(jlist: List[Job]) -> str:
    """Tipo representativo do grupo — se todos os itens do pedido tiverem o
    mesmo tipo, usa esse; se houver mistura (raro), mostra 'Vários'."""
    types = {j.tipo for j in jlist if j.tipo}
    if len(types) == 1:
        return next(iter(types))
    if len(types) > 1:
        return "Vários"
    return ""


def build_pedido_summary(jobs: List[Job]) -> List[PedidoSummary]:
    groups: dict[str, List[Job]] = {}
    for j in jobs:
        if j.is_gap:
            continue
        groups.setdefault(j.pedido, []).append(j)

    summaries = [
        PedidoSummary(
            pedido=pedido,
            total_m=sum(j.real_m for j in jlist),
            job_count=len(jlist),
            newest_end=max(j.end_time for j in jlist),
            tipo=_group_tipo(jlist),
        )
        for pedido, jlist in groups.items()
    ]

    summaries.sort(key=lambda s: s.newest_end, reverse=True)
    return summaries


@dataclass
class ImportOutcome:
    """Resultado de `import_log_files` — sem nenhum efeito de interface
    (sem `messagebox`, sem ler/escrever estado de widget); quem chama decide
    o que mostrar a partir destes campos."""

    jobs: List[Job] = field(default_factory=list)
    files_added: int = 0
    skipped_invalid: int = 0
    sec_alerts: int = 0
    sec_unknown_format: bool = False


def import_log_files(
    paths: Iterable[str],
    *,
    existing_src: Iterable[str] = (),
    space_entries: Optional[Iterable[dict]] = None,
    type_rules: Optional[Iterable[dict]] = None,
    operators: Optional[Iterable[dict]] = None,
    fabrics_map: Optional[Dict[str, FabricEntry]] = None,
    secondary_log_enabled: bool = False,
    secondary_log_folder: Optional[str] = None,
) -> ImportOutcome:
    """Lê, valida e converte um lote de caminhos de log .txt em `Job`s —
    extraído de `modules/operacao/ui.py:_import_paths` pra ser testável sem
    Tkinter (base para reprocessar lotes ou validar formatos novos sem abrir
    o aplicativo). Reproduz exatamente a mesma decisão que a UI já tomava:
    pular arquivo já importado (`existing_src`) ou com métricas inválidas
    (altura <= 0, ou `real_m` inconsistente com `height_mm`), inserir o item
    de ESPAÇO automático quando há avanço (`build_auto_gap_job`), e cruzar
    com o log secundário (M1) — chamado para todo job não-ESPAÇO sempre que
    `secondary_log_enabled` for True, mesmo com `secondary_log_folder` vazio
    (nesse caso quem decide "pasta não configurada" é o próprio
    `m1_check.check_job`, não esta função). Não lê nada de configuração nem
    de disco além dos próprios arquivos de log — quem chama decide o que
    configurar (pastas, regras, impressora)."""
    existing = set(existing_src)
    outcome = ImportOutcome()

    for path in paths:
        path_full = str(path)
        if path_full in existing:
            continue

        job = parse_log_txt(
            path_full,
            space_entries=space_entries,
            type_rules=type_rules,
            operators=operators,
            fabrics_map=fabrics_map,
        )
        if not job:
            outcome.skipped_invalid += 1
            continue

        if job.height_mm <= 0:
            outcome.skipped_invalid += 1
            continue

        correct_real_m = job.height_mm / 1000.0
        if abs(job.real_m - correct_real_m) > 0.001:
            outcome.skipped_invalid += 1
            continue

        gap_job = build_auto_gap_job(job)
        if gap_job:
            outcome.jobs.append(gap_job)
            existing.add(gap_job.src_file)

        outcome.jobs.append(job)
        existing.add(job.src_file)
        outcome.files_added += 1

    if secondary_log_enabled and outcome.jobs:
        sec_folder = (secondary_log_folder or "").strip()
        for job in outcome.jobs:
            if job.is_gap:
                continue
            res = _m1_check_job(folder=sec_folder, end_time=job.end_time)
            job.m1_status = res.status
            job.m1_detail = res.detail
            if res.status == _M1_STATUS_ERROR:
                outcome.sec_alerts += 1
            elif res.status == _M1_STATUS_UNKNOWN_FORMAT:
                outcome.sec_unknown_format = True

    return outcome


def canonicalize_fabric_name(typed: str) -> str:
    """Extraído de modules/operacao/ui.py:_canonicalize_fabric_name. Casa `typed`
    com o cadastro compartilhado de tecidos (core/fabrics.py) e, se não existir
    ainda, cadastra; sempre retorna em caixa alta."""
    typed = typed.strip()
    fabrics_map = load_fabrics()
    canonical = canonical_fabric_name(typed, fabrics_map)
    if not canonical:
        try:
            canonical = register_fabric_name(typed)
        except ValueError:
            canonical = typed
    return canonical.upper()


def resolve_default_import_dir(
    machine: Optional[str], mcfg: dict, printers: Optional[List[Printer]] = None
) -> Optional[str]:
    """Extraído de modules/operacao/ui.py:_default_import_dir. Com a máquina
    do lote já definida, usa a pasta cadastrada pra ela (Gerenciar
    Impressoras → "Pasta dos logs desta impressora"); sem isso — ou na
    primeira importação do rolo, quando a máquina ainda não é conhecida —
    cai pra "Pasta de logs (geral)" (Configurações → Operação)."""
    if machine:
        pr = find_printer_by_display_name(machine, printers)
        folder = (pr.log_import_dir.strip() if pr else "")
        if folder:
            return folder

    return str(mcfg.get("general_log_dir", "") or "").strip() or None


def find_cross_roll_duplicates(
    jobs: Iterable[Job], mcfg: dict, exclude_roll_id: Optional[int] = None
) -> dict:
    """Extraído de modules/operacao/ui.py:_find_cross_roll_duplicates. Pares
    (pedido, tecido) do rolo atual que, segundo as regras de tipo de
    impressão configuradas, merecem checar duplicidade contra outros rolos
    já salvos (core.printlogs_db.find_pedido_fabric_rolls); nunca propaga
    erro de banco — devolve vazio nesse caso, como já era."""
    rules = normalize_rules(mcfg.get("print_type_rules", DEFAULT_RULES))
    pairs = {
        (j.pedido, j.fabric)
        for j in jobs
        if not j.is_gap and warn_duplicate_for_type(j.tipo, rules)
    }
    try:
        return find_pedido_fabric_rolls(pairs, exclude_roll_id=exclude_roll_id)
    except Exception:
        return {}


@dataclass
class ReimportCheck:
    """Resultado de `classify_reimported_jobs` — nunca decide por conta
    própria o que fazer com cada grupo (avisar, bloquear, permitir); só
    classifica. `already_imported`/`changed` guardam (job, registro do
    histórico) para quem avisa poder citar em qual rolo e quando."""

    already_imported: List[Tuple[Job, dict]] = field(default_factory=list)
    changed: List[Tuple[Job, dict]] = field(default_factory=list)
    new: List[Job] = field(default_factory=list)


def classify_reimported_jobs(
    jobs: Iterable[Job], machine: str, history: Dict[str, dict]
) -> ReimportCheck:
    """Parte do item de roadmap (Fase 2) "importação incremental e
    idempotente, com estado de progresso e tratamento de arquivos
    incompletos/alterados". `history` vem de
    `core.printlogs_db.find_orders_by_source_path` (chave = `Job.src_file`)
    — o mesmo arquivo físico já importado antes, em qualquer rolo salvo
    (não só na sessão atual). Compara o `job_hash` de hoje contra o
    registrado: igual = "já importado sem alteração" (não é erro, é
    progresso: o operador pode estar reimportando por engano, ou só
    conferindo de novo); diferente = "alterado desde a última importação"
    (mesmo caminho, conteúdo do log mudou — vale avisar, nunca decidir
    por conta própria). Sem registro = "novo", o caso comum.

    Arquivo incompleto (log ainda sendo escrito pela impressora) não entra
    aqui: já é tratado antes, em `import_log_files` — `parse_log_txt`
    devolve `None` e o arquivo nem chega a gerar um `Job`, então a próxima
    tentativa de importação ainda o vê como pendente, sem precisar de nada
    adicional aqui."""
    result = ReimportCheck()
    for job in jobs:
        record = history.get(job.src_file)
        if record is None:
            result.new.append(job)
            continue
        current_hash = make_job_hash(
            machine, job.end_time.isoformat(timespec="seconds"), job.document, job.height_mm
        )
        if current_hash == record.get("job_hash"):
            result.already_imported.append((job, record))
        else:
            result.changed.append((job, record))
    return result


def check_reimported_jobs(jobs: Iterable[Job], machine: str) -> ReimportCheck:
    """`classify_reimported_jobs` com o histórico lido do banco de verdade
    (`core.printlogs_db.find_orders_by_source_path`) — mesmo padrão de
    `find_cross_roll_duplicates`: nunca propaga erro de banco; sem
    conseguir consultar o histórico, trata tudo como "novo" (mesmo
    comportamento de antes desta verificação existir)."""
    jobs = list(jobs)
    try:
        history = find_orders_by_source_path([j.src_file for j in jobs])
    except Exception:
        history = {}
    return classify_reimported_jobs(jobs, machine, history)


def format_reimport_warning(check: ReimportCheck) -> str:
    """Extraído como parte do mesmo item de roadmap. Só monta aviso para
    `changed` — "já importado sem alteração" não é um alerta, é informação
    de progresso (contagem simples, feita por quem chama, sem precisar
    desta função)."""
    lines = []
    for job, record in check.changed:
        when = (record.get("created_at") or "")[:16].replace("T", " ")
        roll_name = record.get("roll_name") or "?"
        lines.append(
            f"- {job.document}: já importado antes no rolo \"{roll_name}\" ({when}), "
            "mas o conteúdo do log mudou desde então."
        )
    return "\n".join(lines)


def resolve_mirror_target_cm(mode: str, custom: str) -> float:
    """Extraído de modules/operacao/ui.py:_get_mirror_target_cm. Levanta
    ValueError para largura personalizada inválida ou fora de 8–40 cm."""
    mode = (mode or "").strip()
    if mode in ("17", "21"):
        return float(mode)

    s = (custom or "").replace(",", ".").strip()
    try:
        value = float(s)
    except Exception:
        raise ValueError("Largura personalizada inválida.")

    if value < 8 or value > 40:
        raise ValueError("Use entre 8 cm e 40 cm.")
    return value


def resolve_mirror_jpg_path(
    machine: Optional[str],
    out_jpg_dir: Path,
    base_name: str,
    printers: Optional[List[Printer]] = None,
) -> Path:
    """Extraído de modules/operacao/ui.py:_resolve_mirror_jpg_path. Quando a
    impressora cadastrada para `machine` tiver uma pasta de espelho JPG
    própria, usa essa pasta (criando-a se preciso) e o nome de arquivo fixo
    configurado, se houver; senão cai para `out_jpg_dir`/`base_name`. O
    cadastro de impressoras pode ser passado por parâmetro (em vez do real,
    via `core.printers.load_printers`) só para permitir testar sem depender
    de configuração em disco."""
    pr = find_printer_by_display_name(machine or "", printers)
    if pr and pr.jpg_output_dir.strip():
        folder = Path(pr.jpg_output_dir.strip())
        folder.mkdir(parents=True, exist_ok=True)

        filename = pr.jpg_output_filename.strip()
        if filename:
            if not filename.lower().endswith((".jpg", ".jpeg")):
                filename += ".jpg"
            return folder / filename

        return versioned_path(folder / f"{base_name}.jpg")

    return versioned_path(out_jpg_dir / f"{base_name}.jpg")


def format_duplicate_message(matches: Dict[tuple, list]) -> str:
    """Extraído de modules/operacao/ui.py:_format_duplicate_message."""
    lines = []
    for (pedido, fabric), rolls in matches.items():
        rolls_txt = ", ".join(
            f"{r['roll_name']} ({r['machine']}, {(r['created_at'] or '')[:16].replace('T', ' ')})"
            for r in rolls
        )
        lines.append(f"- Pedido \"{pedido}\" + Tecido \"{fabric}\" já impresso em: {rolls_txt}")
    return "\n".join(lines)
