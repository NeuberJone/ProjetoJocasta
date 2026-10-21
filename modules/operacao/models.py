from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Job:
    end_time: datetime
    document: str
    fabric: str
    pedido: str
    height_mm: float
    vpos_mm: float
    real_mm: float
    src_file: str
    is_gap: bool = False
    tipo: str = ""
    # Usados só na verificação M1 (cruzamento com o log diário do programa
    # de impressão física) — largura real do item e horário de início do
    # processamento, lidos do mesmo log .txt mas não usados em mais nada.
    width_mm: float = 0.0
    start_time: Optional[datetime] = None
    # Resultado da verificação M1 (ver modules/operacao/m1_check.py):
    # "" quando não aplicável/não verificado, ou um status + detalhe legível.
    m1_status: str = ""
    m1_detail: str = ""
    # Anotação livre do operador sobre esse item (ex.: "o papel manchou
    # aqui") — editável na tela e salva junto do rolo no banco.
    observacao: str = ""
    # True quando o tipo foi definido manualmente ("Editar tipo") — impede
    # que o botão "Salvar" das regras de detecção reclassifique por engano
    # um item que o usuário já corrigiu na mão.
    tipo_manual: bool = False
    # Nome do operador (cadastrado em Configurações), identificado pelas
    # iniciais no nome do arquivo de reposição (ex.: "N1" -> "N" -> "Neuber").
    # Vazio quando o documento não segue esse formato (ex.: Pedido) ou quando
    # o identificador não está cadastrado.
    operador: str = ""
    # True quando o tecido foi renomeado manualmente ("Editar tecido") —
    # impede que a reclassificação pelo cadastro de tecidos sobrescreva um
    # nome que o usuário já corrigiu na mão.
    fabric_manual: bool = False
    # True quando o pedido foi renomeado manualmente ("Editar pedido") —
    # impede que a reclassificação (nome fixo por tipo, ou nome detectado
    # pelo arquivo) sobrescreva um nome que o usuário já corrigiu na mão.
    pedido_manual: bool = False

    @property
    def real_m(self) -> float:
        return self.real_mm / 1000.0


@dataclass
class Block:
    fabric: str
    machine: str
    Jobs: List[Job]

    @property
    def total_m(self) -> float:
        return sum(j.real_m for j in self.Jobs)

    @property
    def job_count(self) -> int:
        return len(self.Jobs)

    @property
    def newest_end(self) -> datetime:
        return max(j.end_time for j in self.Jobs)

    @property
    def oldest_end(self) -> datetime:
        return min(j.end_time for j in self.Jobs)


@dataclass
class PedidoSummary:
    pedido: str
    total_m: float
    job_count: int
    newest_end: datetime
    tipo: str = ""