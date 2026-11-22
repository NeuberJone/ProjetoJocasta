"""Coordenação da exportação do Planejador, sem Tkinter e sem tocar disco
ou banco — item de roadmap (Fase 3) "extrair cálculo/organização de fila
do Planejador e COORDENAÇÃO DOS RELATÓRIOS para serviços menores, com
regressão dos resultados conhecidos" (a parte de bin packing/montagem da
fila já saiu em modules/planejador_queue.py).

Cobre só as DECISÕES de ``modules/planejador.py:build_ui.on_export`` que
são seguras de isolar sem reescrever a geração de arquivo/gravação no banco
em si (ainda em ``on_export``, que continua chamando as funções de I/O de
sempre — ``export_queue_pdf``/``mirror_and_normal_to_jpg_scaled``/etc.):

- ``plan_export_steps``: quais arquivos (PDF normal, PDF espelhado, JPG,
  limpeza de temporários) gerar e em que ordem, pra cada combinação de
  ``which`` ("normal"/"mirror"/"both") e pasta fixa de impressora
  configurada. Devolve uma lista de passos simbólicos (papel do caminho de
  origem/destino, não o caminho de arquivo real) — ``on_export`` resolve
  cada papel pro caminho de verdade e executa.
- ``main_fabric_of``: tecido mais frequente num rolo, usado no rótulo
  salvo no banco.
- ``decide_scrap_revert``: ao atualizar um rolo editado que usava um
  pedaço cortado, decide se o pedaço deixou de caber (precisa voltar a
  "não usado") — sem chamar ``set_scrap_used``/``save_scraps`` (I/O) aqui.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from core.fabric_scraps import FabricScrap
from modules.planejador_queue import RollLimitConfig, scrap_effective_length

# Papéis simbólicos de caminho usados pelos passos — nunca um caminho de
# arquivo real; on_export resolve cada papel pro caminho de verdade
# (normal_path/mirror_path/tmp_mirror_pdf/tmp_normal_pdf) antes de executar.
ROLE_NORMAL = "normal_path"
ROLE_MIRROR = "mirror_path"
ROLE_TMP_MIRROR_PDF = "tmp_mirror_pdf"
ROLE_TMP_NORMAL_PDF = "tmp_normal_pdf"


@dataclass(frozen=True)
class ExportStep:
    kind: str  # "pdf" | "jpg" | "cleanup"
    dest: str = ""
    mirrored: bool = False  # só usado quando kind == "pdf"
    sources: Tuple[str, ...] = field(default_factory=tuple)  # só usado quando kind == "jpg"


def plan_export_steps(which: str, *, use_printer_folder: bool) -> List[ExportStep]:
    """Decide quais arquivos gerar e em que ordem pra cada modo de
    exportação. ``use_printer_folder`` é a pasta/nome fixo configurado no
    cadastro da impressora (Impressoras) — quando ativo, é o único arquivo
    que ela recebe, então o JPG final tem que trazer o espelhado seguido
    do normal (dois PDFs de origem), não só o espelhado (um PDF de
    origem).

    No modo "mirror" (só JPG, sem PDF normal como entrega), o PDF normal
    usado pra compor esse JPG é só um arquivo TEMPORÁRIO — por isso entra
    como ``ROLE_TMP_NORMAL_PDF`` (apagado depois), diferente do modo
    "both", em que o PDF normal já É uma entrega de verdade
    (``ROLE_NORMAL``) e serve de origem pro JPG sem precisar de uma cópia
    temporária extra.

    ``which`` desconhecido devolve uma lista vazia (mesmo comportamento do
    ``else: return`` original — nenhum arquivo é gerado)."""
    if which == "normal":
        return [ExportStep(kind="pdf", mirrored=False, dest=ROLE_NORMAL)]

    if which == "mirror":
        steps = [ExportStep(kind="pdf", mirrored=True, dest=ROLE_TMP_MIRROR_PDF)]
        if use_printer_folder:
            steps.append(ExportStep(kind="pdf", mirrored=False, dest=ROLE_TMP_NORMAL_PDF))
            steps.append(ExportStep(
                kind="jpg", dest=ROLE_MIRROR, sources=(ROLE_TMP_NORMAL_PDF, ROLE_TMP_MIRROR_PDF)
            ))
            steps.append(ExportStep(kind="cleanup", dest=ROLE_TMP_NORMAL_PDF))
        else:
            steps.append(ExportStep(kind="jpg", dest=ROLE_MIRROR, sources=(ROLE_TMP_MIRROR_PDF,)))
        steps.append(ExportStep(kind="cleanup", dest=ROLE_TMP_MIRROR_PDF))
        return steps

    if which == "both":
        steps = [
            ExportStep(kind="pdf", mirrored=False, dest=ROLE_NORMAL),
            ExportStep(kind="pdf", mirrored=True, dest=ROLE_TMP_MIRROR_PDF),
        ]
        if use_printer_folder:
            steps.append(ExportStep(
                kind="jpg", dest=ROLE_MIRROR, sources=(ROLE_NORMAL, ROLE_TMP_MIRROR_PDF)
            ))
        else:
            steps.append(ExportStep(kind="jpg", dest=ROLE_MIRROR, sources=(ROLE_TMP_MIRROR_PDF,)))
        steps.append(ExportStep(kind="cleanup", dest=ROLE_TMP_MIRROR_PDF))
        return steps

    return []


def main_fabric_of(jobs_only: Sequence[Any]) -> str:
    """Tecido mais frequente entre os itens de um rolo — usado no rótulo do
    rolo salvo no banco (ex.: "Lote 1 - Rolo 2 - Dryfit"). Em caso de
    empate, vale o tecido que apareceu primeiro na lista (iteração de
    dict em Python preserva ordem de inserção)."""
    fab_count: Dict[str, int] = {}
    for x in jobs_only:
        fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
    return max(fab_count.items(), key=lambda kv: kv[1])[0]


def decide_scrap_revert(
    old_scrap_key: str, scraps: Sequence[FabricScrap], total_m: float, cfg: RollLimitConfig
) -> Tuple[str, bool]:
    """Ao atualizar um rolo editado que já usava um pedaço cortado: se o
    conteúdo atualizado passou a exceder a metragem do pedaço (cadastrada
    + sangria, se ativa), esse pedaço deixa de valer pra esse rolo —
    devolve ("", True) pra marcar como NÃO USADO de novo (o rolo passa a
    não ter pedaço nenhum associado). Sem pedaço anterior, ou se ainda
    cabe, devolve (old_scrap_key, False) sem mudar nada. Não chama
    ``set_scrap_used``/``save_scraps`` — só decide; quem chama grava."""
    if not old_scrap_key:
        return old_scrap_key, False
    sc = next((s for s in scraps if s.key == old_scrap_key), None)
    if sc and total_m > scrap_effective_length(sc, cfg):
        return "", True
    return old_scrap_key, False
