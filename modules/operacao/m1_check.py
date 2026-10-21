"""Verificação de impressão real da M1.

A M1 gera o mesmo formato de log .txt por arquivo que a M2/M3, mas esse log
só registra o PROCESSAMENTO (RIP) do arquivo — ela entrega o trabalho a um
outro programa, que comanda a impressora física e grava um log diário
único (formato chinês, em "Log/main/Log[AAAA_MM_DD].txt", encoding
gb18030). Só esse log diário sabe se a impressão física terminou e se
houve erro.

O log diário não conhece o nome do arquivo original (só o nome interno
"~section0.prn") nem imprime um arquivo por vez — vários arquivos
processados em sequência pela M1 são agrupados num único envio físico à
impressora (um "lote"). Por isso a correspondência não é 1 para 1 por
tamanho: cada arquivo pertence ao PRÓXIMO lote físico que a impressora
envia depois que o processamento daquele arquivo termina (fila FIFO) — e
o resultado desse lote (campo "错误码": 0 = sem erro) vale para todos os
arquivos que entraram nele. Validado contra dados reais de produção (ver
CHANGELOG): a atribuição por "próximo lote após o fim do processamento"
bate 100% dos arquivos da M1 fornecidos como referência, com tamanhos de
lote e atrasos (processamento -> envio) plausíveis.

Limitação conhecida: nos logs de referência disponíveis (3 dias de
produção real) nunca apareceu um lote com código de erro diferente de 0,
então o caminho de "erro na impressão" não foi validado contra um caso
real — só documentado a partir do formato do campo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_RE_DATE_IN_NAME = re.compile(r"(\d{4})_(\d{2})_(\d{2})")
_RE_QUEUED = re.compile(r"\[(\d{2}:\d{2}:\d{2})\].*作业ID:\s*(\d+),\s*作业状态\s*:\s*10")
_RE_IMAGE_SIZE = re.compile(r"\[(\d{2}:\d{2}:\d{2})\].*图像大小\s*:\s*([\d.]+)mm\s*X\s*([\d.]+)mm")
_RE_FINAL = re.compile(
    r"\[(\d{2}:\d{2}:\d{2})\].*发送打印结果到RIP.*作业ID\s*:\s*(\d+),\s*错误码\s*:\s*(-?\d+)"
)

STATUS_OK = "ok"
STATUS_ERROR = "erro"
STATUS_NOT_FOUND = "sem_correspondencia"
STATUS_NOT_CONFIGURED = "nao_configurado"
STATUS_UNKNOWN_FORMAT = "formato_desconhecido"

STATUS_LABELS = {
    STATUS_OK: "✓ Impressão confirmada",
    STATUS_ERROR: "⚠ Erro na impressão",
    STATUS_NOT_FOUND: "? Sem correspondência no log adicional",
    STATUS_NOT_CONFIGURED: "",
    STATUS_UNKNOWN_FORMAT: "⚠ Formato do log adicional não reconhecido",
}

# Tamanho mínimo (bytes) pra um arquivo "sem nenhuma linha reconhecida"
# ser tratado como formato errado em vez de só um dia sem jobs — um log
# do formato certo mas vazio normalmente é só um cabeçalho, bem menor que
# isso; um arquivo de outro programa tende a ter bastante conteúdo mesmo
# sem nenhuma linha no formato esperado.
_MIN_SIZE_FOR_FORMAT_WARNING = 2000


@dataclass
class DailyPrintJob:
    job_id: str
    queued_time: datetime
    width_mm: float = 0.0
    height_mm: float = 0.0
    final_time: Optional[datetime] = None
    error_code: Optional[int] = None


@dataclass
class M1CheckResult:
    status: str
    detail: str = ""


def _date_from_filename(path: Path) -> Optional[datetime]:
    m = _RE_DATE_IN_NAME.search(path.stem)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def locate_daily_log_file(folder: str, day: datetime) -> Optional[Path]:
    """Encontra o Log[AAAA_MM_DD].txt do dia pedido dentro da pasta
    configurada — aceita tanto a pasta "Log" (do programa) quanto já a
    "Log/main" diretamente, e os dois formatos de nome vistos (com "_" ou
    "-" separando ano/mês/dia)."""
    if not folder:
        return None
    base = Path(folder)
    search_dirs = [base]
    if (base / "main").is_dir():
        search_dirs.insert(0, base / "main")

    names = [f"Log[{day:%Y_%m_%d}].txt", f"Log[{day:%Y-%m-%d}].txt"]
    for d in search_dirs:
        if not d.is_dir():
            continue
        for name in names:
            candidate = d / name
            if candidate.exists():
                return candidate
    return None


def parse_daily_log(path: Path) -> Tuple[List[DailyPrintJob], int]:
    """Lê o log diário (encoding gb18030) e devolve (jobs físicos
    encontrados, quantidade de linhas reconhecidas no formato esperado).

    A contagem de linhas reconhecidas serve pra distinguir "dia sem nenhum
    job" de "pasta/arquivo no formato errado" — ver `check_job`."""
    day = _date_from_filename(path)
    try:
        lines = path.read_text(encoding="gb18030", errors="ignore").splitlines()
    except Exception:
        return [], 0

    def _ts(hhmmss: str) -> Optional[datetime]:
        if not day:
            return None
        try:
            h, mi, s = (int(x) for x in hhmmss.split(":"))
            return day.replace(hour=h, minute=mi, second=s)
        except Exception:
            return None

    pending: Dict[str, DailyPrintJob] = {}
    awaiting_size: List[str] = []
    completed: List[DailyPrintJob] = []
    recognized = 0

    for line in lines:
        m = _RE_QUEUED.search(line)
        if m:
            recognized += 1
            ts = _ts(m.group(1))
            job_id = m.group(2)
            if ts:
                pending[job_id] = DailyPrintJob(job_id=job_id, queued_time=ts)
                awaiting_size.append(job_id)
            continue

        m = _RE_IMAGE_SIZE.search(line)
        if m:
            recognized += 1
            while awaiting_size and awaiting_size[0] not in pending:
                awaiting_size.pop(0)
            if awaiting_size:
                job_id = awaiting_size.pop(0)
                job = pending.get(job_id)
                if job is not None:
                    try:
                        job.width_mm = float(m.group(2))
                        job.height_mm = float(m.group(3))
                    except Exception:
                        pass
            continue

        m = _RE_FINAL.search(line)
        if m:
            recognized += 1
            ts = _ts(m.group(1))
            job_id = m.group(2)
            try:
                err = int(m.group(3))
            except Exception:
                err = None
            job = pending.pop(job_id, None)
            if job is None:
                job = DailyPrintJob(job_id=job_id, queued_time=ts or datetime.min)
            job.final_time = ts
            job.error_code = err
            completed.append(job)
            continue

    # Jobs sem linha final (log cortado no fim do dia, fila interrompida
    # etc.) também entram, sem erro definido — ficam "sem correspondência"
    # na comparação porque não têm error_code.
    completed.extend(pending.values())
    return completed, recognized


def find_physical_job(
    daily_jobs: List[DailyPrintJob], end_time: datetime
) -> Optional[DailyPrintJob]:
    """Lote físico (já com resultado final) que inclui o arquivo cujo
    processamento terminou em `end_time` — o primeiro lote, em ordem de
    fila, enviado à impressora depois desse horário."""
    finals = sorted(
        (j for j in daily_jobs if j.error_code is not None),
        key=lambda j: j.queued_time,
    )
    for j in finals:
        if j.queued_time >= end_time:
            return j
    return None


_cache: Dict[str, Tuple[List[DailyPrintJob], int]] = {}


def _daily_jobs_for(folder: str, day: datetime) -> Tuple[List[DailyPrintJob], int]:
    """Devolve (jobs, linhas reconhecidas). `linhas reconhecidas` vem -1
    quando o arquivo do dia nem foi encontrado (distinto de 0, que é
    arquivo encontrado mas sem nenhuma linha no formato esperado)."""
    path = locate_daily_log_file(folder, day)
    if not path:
        return [], -1
    key = str(path)
    if key not in _cache:
        _cache[key] = parse_daily_log(path)
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def check_job(*, folder: str, end_time: datetime) -> M1CheckResult:
    """Verifica um log por-arquivo da M1 (pelo horário em que o
    processamento terminou) contra o log diário configurado em
    Configurações/Impressoras. Não lança exceção — qualquer problema
    (pasta não configurada, arquivo do dia ausente, formato não
    reconhecido, sem lote físico correspondente) vira um status
    informativo."""
    if not folder:
        return M1CheckResult(STATUS_NOT_CONFIGURED)

    daily_jobs, recognized = _daily_jobs_for(folder, end_time)

    if recognized == 0:
        try:
            file_size = (locate_daily_log_file(folder, end_time) or Path("")).stat().st_size
        except Exception:
            file_size = 0
        if file_size >= _MIN_SIZE_FOR_FORMAT_WARNING:
            return M1CheckResult(
                STATUS_UNKNOWN_FORMAT,
                f"O log de {end_time:%d/%m/%Y} foi encontrado na pasta configurada, mas nenhuma linha "
                "bate com o formato esperado — confirme se essa pasta é a do log diário certo.",
            )

    match = find_physical_job(daily_jobs, end_time) if daily_jobs else None

    if match is None:
        # O lote pode ter sido fechado e enviado só depois da virada do dia.
        next_day_jobs, _next_recognized = _daily_jobs_for(folder, end_time + timedelta(days=1))
        match = find_physical_job(next_day_jobs, end_time) if next_day_jobs else None

    if match is None:
        if recognized < 0:
            return M1CheckResult(
                STATUS_NOT_FOUND,
                f"Log diário de {end_time:%d/%m/%Y} não encontrado na pasta configurada.",
            )
        return M1CheckResult(
            STATUS_NOT_FOUND,
            "Nenhum lote físico foi enviado à impressora depois deste arquivo "
            "(pode ainda estar na fila, ou o log do dia foi cortado antes do envio).",
        )

    if match.error_code == 0:
        return M1CheckResult(
            STATUS_OK, f"Lote físico {match.job_id}, erro 0, enviado às {match.queued_time:%H:%M:%S}."
        )

    return M1CheckResult(
        STATUS_ERROR,
        f"Lote físico {match.job_id}, código de erro {match.error_code}, "
        f"enviado às {match.queued_time:%H:%M:%S}.",
    )
