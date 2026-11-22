"""Etapa D — PDFs: descoberta dos PDFs dentro da pasta de um pedido já
localizada (ver core/order_files.py — Etapa B — e core/order_vendor_resolution.py
— Etapa C), geração de miniaturas com cache, e vínculo do PDF escolhido como
arquivo impresso do pedido (core.printlogs_db.upsert_pdf_link/clear_pdf_link).

Escopo (ver especificação original, seções 9 — "Localização dos PDFs
originais" — e 10 — "Miniaturas e visualização dos PDFs"): o serviço,
independente de interface — abrir o PDF/pasta no Explorador reaproveita as
funções já existentes de core.paths (open_file/open_in_explorer/
reveal_file_in_explorer), não reescreve nada. A integração com os botões de
Operação/Registros é a Etapa E.

Os PDFs aqui pesquisados vivem exclusivamente dentro da pasta de rede do
vendedor (ver estrutura real, seção 4) — nunca dentro da pasta de
comprovantes do próprio Nexor (core.paths.pdf_rolls_dir), que é um diretório
completamente separado, gerado só pelos exportadores do Nexor. Por isso não
há necessidade de filtrar por nome pra "não confundir PDF original com
comprovante" (seção 9): são espaços de arquivos disjuntos por construção.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from core.logging_config import get_logger, log_exception
from core.paths import open_file, open_in_explorer, reveal_file_in_explorer
from core.printlogs_db import (
    PDF_LINK_ORIGIN_AUTO,
    PDF_LINK_ORIGIN_MANUAL,
    PDF_LINK_STATUS_ACTIVE,
    clear_pdf_link,
    get_pdf_link,
    upsert_pdf_link,
)

_logger = get_logger(__name__)

try:
    import fitz  # PyMuPDF
    _HAS_PYMUPDF = True
except Exception:
    fitz = None
    _HAS_PYMUPDF = False

DEFAULT_THUMBNAIL_MAX_SIZE = (220, 220)


# =========================
# Descoberta (seção 9)
# =========================

@dataclass
class OrderPdfFile:
    path: str
    name: str
    size_bytes: int
    modified_at: str
    page_count: Optional[int] = None
    is_valid: bool = True
    error: str = ""


def _pdf_page_count(path: Path) -> Tuple[Optional[int], bool, str]:
    """Abre o PDF só pra contar páginas/validar — nunca levanta: um PDF
    inválido ou protegido (seção 10 — "Tratar arquivos inválidos e PDFs
    protegidos") volta com is_valid=False e o motivo, sem travar a
    descoberta dos outros arquivos da mesma pasta. Quando PyMuPDF não está
    instalado, a descoberta ainda funciona (sem contagem de páginas) — só a
    miniatura exige a biblioteca."""
    if not _HAS_PYMUPDF or fitz is None:
        return None, True, ""
    try:
        doc = fitz.open(str(path))
        try:
            if doc.needs_pass:
                return None, False, "PDF protegido por senha."
            return doc.page_count, True, ""
        finally:
            doc.close()
    except Exception as exc:
        return None, False, f"PDF inválido: {exc}"


def discover_order_pdfs(folder: str, *, recursive: bool = True) -> List[OrderPdfFile]:
    """Lista os PDFs dentro da pasta de um pedido já localizado (seção 9).
    Pesquisa nas subpastas quando `recursive=True` (padrão) — a
    especificação permite isso "quando necessário", e a estrutura real às
    vezes guarda os PDFs num nível abaixo dentro da própria pasta do
    pedido. Uma pasta inacessível/inexistente retorna lista vazia (nunca
    levanta) — mesmo tratamento de core.order_files._walk_vendor_root."""
    root = Path(folder)
    found: List[OrderPdfFile] = []
    try:
        paths = root.rglob("*.pdf") if recursive else root.glob("*.pdf")
        pdf_paths = sorted((p for p in paths if p.is_file()), key=lambda p: str(p).lower())
    except OSError as exc:
        log_exception(_logger, "Could not list order folder for PDFs", exc)
        return found

    for p in pdf_paths:
        try:
            stat = p.stat()
        except OSError as exc:
            found.append(OrderPdfFile(
                path=str(p), name=p.name, size_bytes=0, modified_at="",
                is_valid=False, error=f"Não foi possível ler o arquivo: {exc.strerror or exc}",
            ))
            continue
        page_count, is_valid, error = _pdf_page_count(p)
        found.append(OrderPdfFile(
            path=str(p),
            name=p.name,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            page_count=page_count,
            is_valid=is_valid,
            error=error,
        ))
    return found


# =========================
# Seleção automática/manual (seção 9 — "Se houver vários PDFs...")
# =========================

PDF_RESOLUTION_AUTO = "auto_identified"
PDF_RESOLUTION_MANUAL = "confirmed_manual"
PDF_RESOLUTION_NOT_FOUND = "not_identified"
PDF_RESOLUTION_AMBIGUOUS = "ambiguous"


@dataclass
class OrderPdfResolution:
    state: str
    pdf_path: str = ""
    candidates: List[OrderPdfFile] = field(default_factory=list)
    link: Optional[dict] = None


def resolve_order_pdf(
    order_id: int, folder: str, *, pdfs: Optional[List[OrderPdfFile]] = None,
) -> OrderPdfResolution:
    """Identifica (ou confirma) qual PDF da pasta do pedido é o arquivo
    impresso (seção 9). Um vínculo manual anterior tem precedência absoluta
    sobre qualquer resolução automática. Com exatamente um PDF válido na
    pasta, atribui automaticamente (origem "auto"); com mais de um, NUNCA
    escolhe por conta própria — nem pelo mais recente (seção 9: "Não
    presumir que o arquivo mais recente seja necessariamente o correto") —
    fica "ambíguo", à espera de escolha manual (`link_order_pdf`)."""
    existing = get_pdf_link(order_id)
    if existing and existing["origin"] == PDF_LINK_ORIGIN_MANUAL and existing["status"] == PDF_LINK_STATUS_ACTIVE:
        return OrderPdfResolution(state=PDF_RESOLUTION_MANUAL, pdf_path=existing["pdf_path"], link=existing)

    candidates = pdfs if pdfs is not None else discover_order_pdfs(folder)
    valid = [c for c in candidates if c.is_valid]

    if len(valid) == 1:
        chosen = valid[0]
        already_linked = (
            existing
            and existing["status"] == PDF_LINK_STATUS_ACTIVE
            and existing["origin"] == PDF_LINK_ORIGIN_AUTO
            and existing["pdf_path"] == chosen.path
        )
        link = existing if already_linked else upsert_pdf_link(order_id, pdf_path=chosen.path, origin=PDF_LINK_ORIGIN_AUTO)
        return OrderPdfResolution(state=PDF_RESOLUTION_AUTO, pdf_path=chosen.path, candidates=valid, link=link)

    if len(valid) > 1:
        return OrderPdfResolution(state=PDF_RESOLUTION_AMBIGUOUS, candidates=valid, link=existing)

    return OrderPdfResolution(state=PDF_RESOLUTION_NOT_FOUND, candidates=candidates, link=existing)


@dataclass
class PdfPreview:
    """Pré-visualização SOMENTE LEITURA do PDF de um pedido, sem `order_id`
    — usada no painel de Operação (Parte 1 da conclusão do recurso), antes
    do rolo (e portanto o pedido) existir no banco. Nunca lê/grava nenhum
    vínculo — mesma lógica de escolha de `resolve_order_pdf` (um PDF válido
    = auto; mais de um = ambíguo, nunca escolhe por conta própria; nenhum =
    não encontrado), só que sem o efeito colateral de persistência."""
    state: str
    pdf_path: str = ""
    candidates: List[OrderPdfFile] = field(default_factory=list)


def preview_order_pdf(folder: str) -> PdfPreview:
    candidates = discover_order_pdfs(folder)
    valid = [c for c in candidates if c.is_valid]
    if len(valid) == 1:
        return PdfPreview(state=PDF_RESOLUTION_AUTO, pdf_path=valid[0].path, candidates=valid)
    if len(valid) > 1:
        return PdfPreview(state=PDF_RESOLUTION_AMBIGUOUS, candidates=valid)
    return PdfPreview(state=PDF_RESOLUTION_NOT_FOUND, candidates=candidates)


def link_order_pdf(order_id: int, pdf_path: str, *, note: str = "") -> dict:
    """Vincula manualmente o PDF escolhido como arquivo impresso do pedido
    (seção 9 — "Vincular PDF ao registro" / "Escolher outro PDF") — sempre
    origem manual, porque é sempre uma escolha explícita do operador; passa
    a ter precedência sobre qualquer resolução automática futura."""
    return upsert_pdf_link(order_id, pdf_path=pdf_path, origin=PDF_LINK_ORIGIN_MANUAL, note=note)


def unlink_order_pdf(order_id: int, *, note: str = "") -> bool:
    """Desvincula o PDF atual do pedido (seção 9 — "Desvincular PDF"), sem
    apagar o histórico — a próxima resolução volta a poder escolher
    automaticamente, se só houver um PDF válido na pasta."""
    return clear_pdf_link(order_id, note=note)


def get_linked_order_pdf(order_id: int) -> Optional[dict]:
    return get_pdf_link(order_id)


# =========================
# Abertura (seção 9 — reaproveita core.paths)
# =========================

def open_order_pdf(pdf_path: str) -> None:
    """Abre o PDF no leitor padrão do Windows (seção 9 — "Abrir PDF")."""
    open_file(Path(pdf_path))


def open_order_folder(folder: str) -> None:
    """Abre a pasta do pedido no Explorador (seção 9 — "Abrir pasta")."""
    open_in_explorer(Path(folder))


def reveal_order_pdf(pdf_path: str) -> None:
    """Abre o Explorador já com o PDF selecionado (seção 9 — "Mostrar PDF
    no Explorador")."""
    reveal_file_in_explorer(Path(pdf_path))


# =========================
# Miniaturas (seção 10)
# =========================

def _thumbnail_cache_dir() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor" / "thumbnail_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _thumbnail_cache_key(pdf_path: str, *, page: int, max_size: Tuple[int, int], mtime: float, size_bytes: int) -> str:
    raw = f"{pdf_path}|{page}|{max_size[0]}x{max_size[1]}|{mtime}|{size_bytes}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class ThumbnailResult:
    png_bytes: Optional[bytes] = None
    page_count: int = 0
    error: str = ""


def get_order_pdf_thumbnail(
    pdf_path: str,
    *,
    page: int = 0,
    max_size: Tuple[int, int] = DEFAULT_THUMBNAIL_MAX_SIZE,
    use_cache: bool = True,
) -> ThumbnailResult:
    """Miniatura da página `page` do PDF, preservando proporção (zoom
    uniforme nos dois eixos — nunca distorce — seção 10). Síncrona — quem
    chamar isto fora de um teste/console deve rodar numa thread própria
    (mesmo trade-off documentado em core/vendedores.py:test_folder_access;
    não travar o Tkinter de fato é Etapa E).

    Cache em disco por (caminho, página, tamanho máximo, mtime, tamanho em
    bytes do arquivo) — qualquer mudança no PDF original (mtime OU tamanho)
    muda a chave e nunca retorna uma miniatura obsoleta (seção 10:
    "Invalidar o cache quando o arquivo mudar"), sem precisar rastrear
    invalidação explícita. Nunca altera o PDF original (só leitura)."""
    if not _HAS_PYMUPDF or fitz is None:
        return ThumbnailResult(error="PyMuPDF não instalado.")

    path = Path(pdf_path)
    try:
        stat = path.stat()
    except OSError as exc:
        return ThumbnailResult(error=f"Não foi possível acessar o arquivo: {exc.strerror or exc}")

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        return ThumbnailResult(error=f"PDF inválido: {exc}")

    try:
        if doc.needs_pass:
            return ThumbnailResult(error="PDF protegido por senha.", page_count=doc.page_count)

        page_count = doc.page_count
        if page < 0 or page >= page_count:
            return ThumbnailResult(
                error=f"Página {page} não existe neste PDF ({page_count} página(s)).", page_count=page_count,
            )

        cache_path = None
        if use_cache:
            key = _thumbnail_cache_key(str(path), page=page, max_size=max_size, mtime=stat.st_mtime, size_bytes=stat.st_size)
            cache_path = _thumbnail_cache_dir() / f"{key}.png"
            if cache_path.exists():
                try:
                    return ThumbnailResult(png_bytes=cache_path.read_bytes(), page_count=page_count)
                except OSError:
                    pass  # cache removido/corrompido entre o exists() e o read_bytes() — gera de novo abaixo

        pdf_page = doc.load_page(page)
        rect = pdf_page.rect
        if rect.width <= 0 or rect.height <= 0:
            return ThumbnailResult(error="Página inválida para gerar miniatura.", page_count=page_count)

        max_w, max_h = max_size
        zoom = max(min(max_w / rect.width, max_h / rect.height), 0.01)
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png_bytes = pix.tobytes("png")

        if cache_path is not None:
            try:
                cache_path.write_bytes(png_bytes)
            except OSError as exc:
                log_exception(_logger, "Could not write thumbnail cache", exc)

        return ThumbnailResult(png_bytes=png_bytes, page_count=page_count)
    finally:
        doc.close()
