"""Verificação de impressão física incompleta, direto do log por-arquivo
(.txt) de qualquer máquina (M1, M2, M3) — sem depender de nenhum log
adicional/secundário (ver m1_check.py, que só existe pra M1 e só prova
que um lote foi ENVIADO, nunca que saiu inteiro).

Achado real (pedido do usuário, logs reais de comparação da M3 com casos
conhecidos de impressão interrompida, em `Referencia/LogsComparação`): a
seção [1] do log (`HeightMM`/`VPositionMM`) é só o que foi MANDADO pra
impressora (altura do arquivo + avanço/gap antes dele) — nunca muda,
mesmo quando a impressão física é cortada no meio. A seção [Costs] tem
`PrintHeightMM`, que é o total FISICAMENTE processado pela RIP (avanço +
imagem). Numa impressão completa, os dois batem (diferença de até 0,1mm,
só arredondamento); numa impressão cortada, `PrintHeightMM` fica menor
pela quantidade que faltou.

Confirmado nos pares original/reimpressão fornecidos pelo usuário —
ex.: "24-11 - DRYFIT - ADEGA BRADOCK (3)": esperado 7975,9mm, só saiu
5171,9mm na 1ª vez (faltaram 2804mm); a reimpressão bateu certinho
(4996,1mm pedido, 4996,1mm saído). Mesmo padrão em "RESENHA FUTEBOL"
(esperado 3908,2mm, só saiu 138,8mm), "Felipe Coimbra 10 (11)" (esperado
9916,2mm, só saiu 5117,0mm) e "RDV 3 (3)" (esperado 9979,7mm, só saiu
72,0mm) — todas com reimpressão batendo em seguida.

Reconfirmado de forma independente nos 277 logs reais de M1/M2/M3 já
usados pra validar `m1_check.py` (fora da pasta de comparação, nunca
marcados pelo usuário como "incompletos"): só 2 em 277 deram essa
diferença (>3mm) — "BAETA VERDE (1)" (M2: esperado 7127,4mm, só saiu
2470,0mm) e "16-10 - Ribana - Salum 14" (computador não cadastrado em
`printers.json`: esperado 1505,9mm, só saiu 1111,4mm) — os outros 275
bateram com diferença máxima de 0,1mm. Ou seja, o sinal é raro no dia a
dia normal (impressão completa) e exatamente onde o usuário já sabia que
havia um caso real.

Só funciona com `FileCount == 1` (nunca visto diferente de 1 nos 277
logs reais conferidos) — com mais de um arquivo no mesmo job, caberia
uma lógica por item que não foi validada contra nenhum caso real, então
o resultado fica "" (não disponível) em vez de arriscar um cálculo não
testado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATUS_OK = "completa"
STATUS_INCOMPLETE = "incompleta"
STATUS_NOT_AVAILABLE = ""

STATUS_LABELS = {
    STATUS_OK: "✓ Impressão completa",
    STATUS_INCOMPLETE: "⚠ Impressão incompleta",
    STATUS_NOT_AVAILABLE: "",
}

# Tolerância pra diferença de arredondamento entre RIPs diferentes — nos
# 277 logs reais conferidos (M1/M2/M3), uma impressão completa nunca
# diferiu mais que 0,1mm; os 2 casos reais de impressão cortada já
# encontrados ficaram em centenas/milhares de mm. 10mm dá uma folga
# grande sem risco de confundir ruído com impressão cortada.
TOLERANCE_MM = 10.0


@dataclass
class PrintCompletenessResult:
    status: str
    detail: str = ""
    print_height_mm: float = 0.0
    shortfall_mm: float = 0.0


def check_completeness(
    *,
    height_mm: float,
    vpos_mm: float,
    print_height_mm: Optional[float],
    file_count: int,
) -> PrintCompletenessResult:
    """`print_height_mm` é `None` quando o campo `[Costs].PrintHeightMM`
    não existia no log (formato antigo/inesperado) — nesse caso, igual a
    `file_count != 1`, o resultado é "não disponível", nunca um palpite."""
    if print_height_mm is None or file_count != 1:
        return PrintCompletenessResult(status=STATUS_NOT_AVAILABLE)

    expected = height_mm + vpos_mm
    shortfall = expected - print_height_mm

    if shortfall <= TOLERANCE_MM:
        return PrintCompletenessResult(status=STATUS_OK, print_height_mm=print_height_mm)

    detail = (
        f"Impresso {print_height_mm / 1000:.2f} m de {expected / 1000:.2f} m esperados "
        f"(faltaram {shortfall / 1000:.2f} m)."
    )
    return PrintCompletenessResult(
        status=STATUS_INCOMPLETE,
        detail=detail,
        print_height_mm=print_height_mm,
        shortfall_mm=shortfall,
    )


def observacao_with_warning(observacao: str, status: str, detail: str) -> str:
    """Observação exibida nos comprovantes (Clássico e Prisma), prefixada
    com o aviso de impressão incompleta quando aplicável — nunca descarta
    a observação manual do operador, só antepõe o aviso a ela.

    Usa "ATENÇÃO" em vez do símbolo "⚠" (usado na tela, onde o Tk resolve
    com a fonte do sistema): confirmado que as fontes base do reportlab
    (Helvetica/Helvetica-Oblique, WinAnsiEncoding) não têm esse glyph —
    ele saía como um caractere errado no PDF gerado (testado direto:
    '⚠' virava 'I'), o que apagaria o próprio aviso no comprovante."""
    observacao = (observacao or "").strip()
    if status != STATUS_INCOMPLETE:
        return observacao
    warn = f"ATENÇÃO — IMPRESSÃO INCOMPLETA: {detail}".strip()
    return f"{warn} {observacao}".strip() if observacao else warn
