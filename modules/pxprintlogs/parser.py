from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Job, Block, PedidoSummary

_RE_KV = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$")
_RE_SECTION = re.compile(r"^\s*\[(.+?)\]\s*$")
_RE_TRAILING_EXT = re.compile(r"\.[A-Za-z0-9]{2,5}$")
# Parênteses no fim do nome são controle de separação (ex.: "(Argentina)", "(Brasil)", "(13)"),
# não fazem parte da identidade do pedido — "Salum 12 (Argentina)" e "Salum 12 (Brasil)" são o mesmo pedido.
_RE_TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_RE_TRAILING_NUM = re.compile(r"\s+\d+\s*$")


def parse_datetime(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def fabric_from_document(doc: str) -> str:
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if len(parts) >= 2 and parts[1].strip():
        return parts[1].strip().upper()
    return "DESCONHECIDO"


def pedido_from_document(doc: str) -> str:
    parts = [p.strip() for p in (doc or "").split(" - ")]
    if len(parts) < 3:
        return "DESCONHECIDO"

    raw = " - ".join(parts[2:]).strip()
    raw = _RE_TRAILING_EXT.sub("", raw)

    # Parênteses no fim já marcam onde o "ruído" termina (ex.: "Salum 12 (Argentina)"
    # e "Salum 12 (Brasil)" são o mesmo pedido "Salum 12" — o "12" faz parte do nome).
    # Sem parênteses, um número solto no fim (ex.: "Escolinha Reis 21") é tratado
    # como contador de peça e é removido.
    had_paren = False
    while True:
        stripped = _RE_TRAILING_PAREN.sub("", raw).strip()
        if stripped == raw:
            break
        raw = stripped
        had_paren = True

    if not had_paren:
        raw = _RE_TRAILING_NUM.sub("", raw)

    raw = raw.strip()

    return raw if raw else "DESCONHECIDO"


def _normalize_doc_name(name: str) -> str:
    name = (name or "").strip()
    name = _RE_TRAILING_EXT.sub("", name)
    return name.casefold()


def is_space_document(document: str, space_filenames: Optional[Iterable[str]]) -> bool:
    """True se `document` (nome do arquivo/job registrado no log) corresponde
    a um dos arquivos de espaço cadastrados — usado por máquinas que não têm
    gap automático entre tecidos e imprimem um arquivo dedicado como espaço."""
    if not space_filenames:
        return False
    norm_doc = _normalize_doc_name(document)
    if not norm_doc:
        return False
    return any(_normalize_doc_name(sf) == norm_doc for sf in space_filenames if sf)


def parse_log_txt(path: str, space_filenames: Optional[Iterable[str]] = None) -> Optional[Job]:
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None

    section = None
    general = {}
    item1 = {}

    for line in txt:
        msec = _RE_SECTION.match(line)
        if msec:
            section = msec.group(1).strip()
            continue

        mkv = _RE_KV.match(line)
        if not mkv:
            continue

        k, v = mkv.group(1).strip(), mkv.group(2).strip()
        if section == "General":
            general[k] = v
        elif section == "1":
            item1[k] = v

    end_dt = parse_datetime(general.get("EndTime", ""))
    if not end_dt:
        return None

    document = general.get("Document") or item1.get("Name") or Path(path).stem

    def _f(x: str) -> float:
        x = (x or "").strip().replace(",", ".")
        try:
            return float(x)
        except Exception:
            return 0.0

    height_mm = _f(item1.get("HeightMM", "0"))
    vpos_mm = _f(item1.get("VPositionMM", "0"))
    real_mm = height_mm

    is_gap = is_space_document(document, space_filenames)
    if is_gap:
        fabric = "ESPAÇO"
        pedido = "ESPAÇO"
    else:
        fabric = fabric_from_document(document)
        pedido = pedido_from_document(document)

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
        )
        for pedido, jlist in groups.items()
    ]

    summaries.sort(key=lambda s: s.newest_end, reverse=True)
    return summaries