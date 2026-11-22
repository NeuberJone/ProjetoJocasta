"""Cálculo e organização da fila do Planejador, sem Tkinter.

Extraído de ``modules/planejador.py`` (eram closures dentro de ``build_ui``)
para poder ser testado diretamente, sem instanciar nenhum widget — item de
roadmap (Fase 3) "Extrair cálculo/organização de fila do Planejador... para
serviços menores, com regressão dos resultados conhecidos".

Cobre a parte que decide COMO os itens de um tecido se distribuem entre
rolos (first-fit decreasing, respeitando pedaços cortados e metragem padrão
de rolo cheio), em que ordem os tecidos aparecem na fila, e a montagem
completa da fila com os espaços (gaps) entre tecidos/fim de rolo/entre
arquivos já inseridos (``generate_queue_rows``). ``generate_queue`` em
``modules/planejador.py`` ainda existe, mas só lê o estado da tela
(variáveis Tk, config), monta um ``RollLimitConfig``/a ordem dos tecidos e
chama ``generate_queue_rows`` — depois repassa o resultado pra tela
(tabelas, nomes dos pedaços usados). Nenhuma lógica de decisão de fila
sobrou em ``build_ui``.

Os itens aceitos aqui (``items``/``base_list``) são objetos com atributos
``fabric: str``, ``length_m: float``, ``is_gap: bool`` e ``name: str`` — na
prática, instâncias de ``modules.planejador.Job`` — mas o módulo não
importa essa classe (evita um import circular: ``planejador.py`` importa
este módulo), então qualquer objeto com essa forma serve, inclusive um
stub de teste.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.fabric_scraps import FabricScrap, unused_scraps_for_fabric
from core.fabrics import DEFAULT_ROLL_LENGTH_M, fabric_roll_length
from modules.operacao.parser import pedido_from_document


@dataclass(frozen=True)
class RollLimitConfig:
    """Tudo que hoje vem de variáveis de UI/cadastro e influencia a
    metragem limite de um rolo de um tecido durante a geração da fila."""

    fabrics_map: Dict[str, Any]
    roll_other_m: float
    use_scraps: bool
    scraps: Sequence[FabricScrap]
    selected_scrap_keys: Optional[set]
    bleed_m: float


def roll_limit_for(fabric: str, cfg: RollLimitConfig) -> float:
    """Metragem de um rolo cheio desse tecido: a cadastrada no tecido, ou a
    metragem "Outro tecido" configurada na tela quando não há cadastro."""
    entry = cfg.fabrics_map.get(fabric)
    if isinstance(entry, dict) and entry.get("roll_length_m"):
        return fabric_roll_length(entry)
    return cfg.roll_other_m


def eligible_scraps_for_fabric(fabric: str, cfg: RollLimitConfig) -> List[FabricScrap]:
    """Pedaços não usados desse tecido que podem entrar no planejamento —
    todos, ou só os marcados em 'Selecionar pedaços a usar…' quando o
    usuário restringiu a seleção (ex.: tecido do mesmo nome vindo de
    fabricantes/lotes diferentes que não podem se misturar num rolo)."""
    items = unused_scraps_for_fabric(cfg.scraps, fabric)
    if cfg.selected_scrap_keys is not None:
        items = [s for s in items if s.key in cfg.selected_scrap_keys]
    return items


def scrap_effective_length(sc: FabricScrap, cfg: RollLimitConfig) -> float:
    """Metragem considerada no planejamento para esse pedaço — a cadastrada,
    ou com a sangria somada quando 'Usar sangria' está ativo."""
    return sc.length_m + cfg.bleed_m


def limit_for_roll(fabric: str, roll_index: int, cfg: RollLimitConfig) -> float:
    """roll_index começa em 0. Com 'priorizar pedaços', os primeiros rolos do
    tecido usam a metragem dos pedaços cortados (não usados e elegíveis,
    com sangria se ativa) antes de cair para a metragem padrão de rolo
    cheio do tecido."""
    if cfg.use_scraps:
        scrap_lens = [
            scrap_effective_length(s, cfg) for s in eligible_scraps_for_fabric(fabric, cfg)
        ]
        if roll_index < len(scrap_lens):
            return scrap_lens[roll_index]
    return roll_limit_for(fabric, cfg) or DEFAULT_ROLL_LENGTH_M


def scrap_match_for_roll(fabric: str, roll_index: int, cfg: RollLimitConfig) -> Optional[FabricScrap]:
    """Pedaço cortado usado nesse rolo (None se o rolo for um rolo cheio normal)."""
    if not cfg.use_scraps:
        return None
    matching = eligible_scraps_for_fabric(fabric, cfg)
    if roll_index < len(matching):
        return matching[roll_index]
    return None


def fabric_block_sort_key(j: Any, *, group_by_pedido: bool) -> Tuple[str, float]:
    """Ordem dos itens dentro de um bloco de tecido: por padrão só por
    tamanho (maior primeiro). Com 'Agrupar por pedido dentro do tecido'
    ligado, agrupa primeiro pelo nome do pedido (ordem alfabética) e,
    dentro do mesmo pedido, por tamanho (maior primeiro) — o tamanho vira
    critério secundário, não substitui o agrupamento."""
    pedido = pedido_from_document(j.name).lower() if group_by_pedido else ""
    return (pedido, -j.length_m)


def pack_fabric_items(
    fabric: str,
    items: List[Any],
    gap_endroll: float,
    gap_files: float,
    cfg: RollLimitConfig,
    *,
    group_by_pedido: bool,
) -> List[Tuple[int, List[Any]]]:
    """
    First-fit decreasing: maiores primeiro, mas cada item vai pro primeiro rolo
    (pedaço cortado ou rolo cheio) em que ele realmente CABE. Um item maior que
    um pedaço cortado não "ocupa" esse pedaço só por ser o primeiro da fila —
    ele passa para o próximo rolo, deixando o pedaço livre para um item menor
    que vier depois (mesmo que processado mais tarde nesta mesma função).

    gap_files é o espaço reservado ENTRE arquivos dentro do mesmo rolo (bloco
    do mesmo tecido) — conta na metragem do rolo, mas não é reservado antes do
    primeiro item nem depois do último item do bloco.

    Retorna [(índice_original_do_rolo, itens), ...] só com rolos não vazios —
    o índice original é preservado para identificar corretamente qual pedaço
    cortado (se algum) foi usado em cada rolo.
    """
    sorted_items = sorted(items, key=lambda j: fabric_block_sort_key(j, group_by_pedido=group_by_pedido))
    bins: List[List[Any]] = []
    bin_used: List[float] = []
    bin_limit: List[float] = []

    def open_new_bin() -> int:
        idx = len(bins)
        bins.append([])
        bin_used.append(0.0)
        bin_limit.append(limit_for_roll(fabric, idx, cfg))
        return idx

    for item in sorted_items:
        # Primeiro rolo já aberto em que o item CABE (considerando o que já
        # está nele). Só abre um rolo novo se não couber em nenhum dos já
        # abertos — nunca empilha num rolo "de sobra" junto com itens que
        # não cabem juntos (isso misturava itens de rolos diferentes
        # quando nenhum item cabia no limite configurado, ex.: gap de fim
        # de rolo maior que a própria metragem do rolo).
        idx = None
        for i in range(len(bins)):
            extra_gap = gap_files if bins[i] else 0.0
            if (bin_used[i] + extra_gap + item.length_m + gap_endroll) <= bin_limit[i]:
                idx = i
                break

        if idx is None:
            idx = open_new_bin()

        extra_gap = gap_files if bins[idx] else 0.0
        bins[idx].append(item)
        bin_used[idx] += extra_gap + item.length_m

    # remove rolos reservados que nenhum item acabou ocupando, preservando o índice original
    return [(i, b) for i, b in enumerate(bins) if b]


def fabric_totals(base_list: List[Any]) -> Dict[str, float]:
    tot: Dict[str, float] = {}
    for j in base_list:
        if j.is_gap:
            continue
        tot[j.fabric] = tot.get(j.fabric, 0.0) + j.length_m
    return tot


def ordered_fabrics(
    base_list: List[Any], *, auto_order: bool, manual_order: List[str]
) -> Tuple[List[str], List[str]]:
    """Devolve (ordem_dos_tecidos, ordem_manual_atualizada) — a ordem manual
    é devolvida mesmo quando ``auto_order`` está ativo, só ajustada pra
    remover tecidos que saíram da fila e incluir os que entraram, para que a
    escolha do usuário sobreviva caso ele desligue 'Ordenar automaticamente'
    depois."""
    fabrics = sorted({j.fabric for j in base_list if not j.is_gap})
    if not fabrics:
        return [], manual_order

    if auto_order:
        totals = fabric_totals(base_list)
        return sorted(fabrics, key=lambda f: totals.get(f, 0.0), reverse=True), manual_order

    updated = list(manual_order) if manual_order else list(fabrics)
    existing = set(fabrics)
    updated = [f for f in updated if f in existing]
    for f in fabrics:
        if f not in updated:
            updated.append(f)
    return list(updated), updated


def _resolve_gap(
    gap_m: float, hidden: bool, gap_seq: int, gap_overrides: Dict[int, float]
) -> Tuple[Optional[int], Optional[float], int]:
    """Decide o índice de sequência do espaço (None se oculto — nunca editável
    manualmente) e a metragem final (considerando um override manual salvo
    pra esse índice; None se a metragem final ficar zero ou negativa, caso em
    que o espaço não deve ser criado), e o próximo valor de ``gap_seq``."""
    gap_index: Optional[int] = None
    use_m = gap_m
    next_seq = gap_seq
    if not hidden:
        gap_index = gap_seq
        next_seq = gap_seq + 1
        if gap_index in gap_overrides:
            use_m = gap_overrides[gap_index]
    if use_m <= 0:
        return gap_index, None, next_seq
    return gap_index, use_m, next_seq


@dataclass
class GeneratedQueue:
    planned: List[Any]
    roll_scrap_matches: Dict[int, FabricScrap]


def generate_queue_rows(
    base_list: List[Any],
    *,
    job_cls: type,
    single_roll: bool,
    mode: str,
    gap_between: float,
    gap_endroll: float,
    gap_files: float,
    speed: float,
    cfg: RollLimitConfig,
    group_by_pedido: bool,
    gap_overrides: Dict[int, float],
    fabrics_order: Optional[List[str]] = None,
) -> GeneratedQueue:
    """Monta a fila completa — um único rolo contínuo quando ``single_roll``
    (editando um rolo já registrado: sem reagrupar/separar por tecido nem
    bin packing, itens na ordem em que já estão), ou dividida em rolos
    quando não (por ordem de importação, só quebrando rolo quando o tecido
    muda ou o rolo atual enche, se ``mode != "tecido"``; ou por tecido com
    bin packing first-fit decreasing dentro de cada tecido, se
    ``mode == "tecido"`` — nesse caso ``fabrics_order`` é obrigatório: a
    ordem dos tecidos já é decidida por ``ordered_fabrics``, uma decisão
    separada desta função).

    ``job_cls`` é a classe usada pra criar cada linha da fila (itens
    normais e espaços) — na prática, ``modules.planejador.Job`` — recebida
    por fora pra este módulo não precisar importá-la (evita um import
    circular, já que ``planejador.py`` importa este módulo).

    Não decide nada de tela: sem refresh de tabela, sem diálogo de erro de
    configuração, sem rótulo formatado do pedaço usado (devolve o
    ``FabricScrap`` em si por rolo, em ``roll_scrap_matches`` — formatar o
    rótulo pra exibição continua em ``modules/planejador.py``, que tem
    ``fmt_m``)."""
    if single_roll:
        planned = [
            job_cls(
                name=item.name, path=item.path, fabric=item.fabric,
                w_px=item.w_px, h_px=item.h_px, dpi_override=item.dpi_override,
                length_m=item.length_m, time_min=item.time_min,
                is_gap=False, roll_no=1,
            )
            for item in base_list
        ]
        return GeneratedQueue(planned=planned, roll_scrap_matches={})

    planned: List[Any] = []
    roll_scrap_matches: Dict[int, FabricScrap] = {}
    global_roll_no = 0
    gap_seq = 0

    def emit(item: Any, roll_no: int) -> None:
        planned.append(job_cls(
            name=item.name,
            path=item.path,
            fabric=item.fabric,
            w_px=item.w_px,
            h_px=item.h_px,
            dpi_override=item.dpi_override,
            length_m=item.length_m,
            time_min=item.time_min,
            is_gap=False,
            roll_no=roll_no,
        ))

    def add_gap(fabric: str, gap_m: float, hidden: bool = False) -> None:
        nonlocal gap_seq
        gap_index, use_m, gap_seq = _resolve_gap(gap_m, hidden, gap_seq, gap_overrides)
        if use_m is None:
            return
        g = job_cls(
            name="ESPAÇO",
            path=None,
            fabric=fabric,
            w_px=0,
            h_px=0,
            dpi_override=None,
            is_gap=True,
            roll_no=0,
            hidden=hidden,
            gap_index=gap_index,
        )
        g.length_m = float(use_m)
        g.time_min = float((g.length_m / speed) if speed > 0 else 0.0)  # gap não tem setup
        planned.append(g)

    def record_scrap_match(fabric: str, roll_index: int) -> None:
        # Só a primeira vez que esse rolo aparece — preservado do original:
        # um rolo já pode ter sido registrado antes de qualquer item seu ser
        # emitido (não se aplica aqui, mas mantém a mesma guarda por clareza
        # e porque chamar scrap_match_for_roll de novo não teria efeito
        # diferente, só seria redundante).
        if global_roll_no in roll_scrap_matches:
            return
        sc_match = scrap_match_for_roll(fabric, roll_index, cfg)
        if sc_match:
            roll_scrap_matches[global_roll_no] = sc_match

    if mode != "tecido":
        # Mantém a ordem de importação; só quebra rolo quando o tecido muda
        # ou quando o rolo atual enche (sem bin packing entre tecidos).
        current_fabric: Optional[str] = None
        fabric_roll_index = 0
        used_in_roll = 0.0

        for j in base_list:
            fabric = j.fabric or "Outro"

            if current_fabric is None:
                current_fabric = fabric
                global_roll_no = 1
                fabric_roll_index = 0
                used_in_roll = 0.0
            elif fabric != current_fabric:
                add_gap(current_fabric, gap_between)
                current_fabric = fabric
                global_roll_no += 1
                fabric_roll_index = 0
                used_in_roll = 0.0

            limit = limit_for_roll(fabric, fabric_roll_index, cfg)
            guard = 0

            # nunca encostar no limite (reserva gap_endroll e, se já houver item
            # no bloco atual, gap_files). Só insere o espaço de fim de rolo se o
            # rolo atual já tiver algo nele — um rolo vazio (ex.: pedaço cortado
            # menor que o próprio item) é pulado sem gerar espaço extra.
            while True:
                file_gap = gap_files if used_in_roll > 0 else 0.0
                if (used_in_roll + file_gap + j.length_m + gap_endroll) <= limit or guard >= 50:
                    break
                guard += 1
                if used_in_roll > 0:
                    add_gap(current_fabric, gap_endroll)
                global_roll_no += 1
                fabric_roll_index += 1
                used_in_roll = 0.0
                limit = limit_for_roll(fabric, fabric_roll_index, cfg)

            record_scrap_match(fabric, fabric_roll_index)

            # gap entre arquivos: nunca antes do primeiro item do bloco.
            # Não aparece na lista — só soma na metragem do rolo/tecido.
            file_gap = gap_files if used_in_roll > 0 else 0.0
            if file_gap > 0:
                add_gap(current_fabric, file_gap, hidden=True)

            emit(j, global_roll_no)
            used_in_roll += file_gap + j.length_m

        if current_fabric is not None and gap_endroll > 0:
            add_gap(current_fabric, gap_endroll)

    else:
        # Modo tecido: agrupa por tecido (ordem já decidida em
        # fabrics_order) e faz bin packing (first-fit decreasing) dentro de
        # cada tecido, para que pedaços cortados pequenos sejam preenchidos
        # por itens menores em vez de pulados por serem menores que o maior
        # item da fila.
        fabrics = fabrics_order or []

        by_fab: Dict[str, List[Any]] = {f: [] for f in fabrics}
        for j in base_list:
            if j.is_gap:
                continue
            by_fab.setdefault(j.fabric, []).append(j)

        last_fabric_with_items: Optional[str] = None

        for f in fabrics:
            items = by_fab.get(f, [])
            if not items:
                continue

            if last_fabric_with_items is not None:
                add_gap(last_fabric_with_items, gap_between)

            bins = pack_fabric_items(f, items, gap_endroll, gap_files, cfg, group_by_pedido=group_by_pedido)

            for seq_pos, (bin_index, bin_items) in enumerate(bins):
                global_roll_no += 1

                record_scrap_match(f, bin_index)

                # gap entre arquivos: nunca antes do primeiro nem depois do
                # último item do bloco (rolo) — só entre itens consecutivos.
                # Não aparece na lista — só soma na metragem do rolo/tecido.
                sort_key = lambda jb: fabric_block_sort_key(jb, group_by_pedido=group_by_pedido)
                for pos, item in enumerate(sorted(bin_items, key=sort_key)):
                    if pos > 0 and gap_files > 0:
                        add_gap(f, gap_files, hidden=True)
                    emit(item, global_roll_no)

                if seq_pos < len(bins) - 1:
                    add_gap(f, gap_endroll)

            last_fabric_with_items = f

        if last_fabric_with_items is not None and gap_endroll > 0:
            add_gap(last_fabric_with_items, gap_endroll)

    return GeneratedQueue(planned=planned, roll_scrap_matches=roll_scrap_matches)
