"""Identificador deste computador — usado pra diferenciar nomes de rolo
gerados em computadores diferentes quando o Nexor roda em rede, com mais de
um PC apontando pro mesmo banco de dados compartilhado (ver "Diretório de
trabalho" em Configurações). O número sequencial do rolo já é atômico
(core.printlogs_db.next_roll_sequence), mas fica salvo só neste computador
(%APPDATA%, não na pasta de rede) — cada PC tem o seu, igual às outras
configurações locais do app.

O nome do operador deste computador é salvo junto, mas é outra coisa: quem
fecha/atualiza um rolo NESTE computador, pra aparecer no comprovante
(PDF/JPG) como "Operador de fechamento". Diferente do operador identificado
pelas iniciais no nome do arquivo de reposição (ver core.operators) — esse é
por job individual (ex.: "N1" -> "Neuber"); este aqui é fixo por computador,
pra quando quem fecha o rolo não é necessariamente quem imprimiu cada item."""
from __future__ import annotations

import re

from core.config import read_module_cfg, write_module_cfg

STATION_MODULE = "Estacao"
_RE_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_LEN = 16
_MAX_OPERATOR_LEN = 60

_DEFAULTS = {"station_id": "", "operator_name": ""}


def _sanitize(raw: str) -> str:
    return _RE_UNSAFE.sub("", (raw or "").strip())[:_MAX_LEN]


def load_station_id() -> str:
    cfg = read_module_cfg(STATION_MODULE, _DEFAULTS)
    return _sanitize(str(cfg.get("station_id") or ""))


def save_station_id(station_id: str) -> None:
    # Lê e regrava o config inteiro (em vez de só {"station_id": ...}) pra
    # não apagar o operator_name salvo junto — write_module_cfg substitui o
    # arquivo por completo, não faz merge.
    cfg = read_module_cfg(STATION_MODULE, _DEFAULTS)
    cfg["station_id"] = _sanitize(station_id)
    write_module_cfg(STATION_MODULE, cfg)


def load_station_operator() -> str:
    cfg = read_module_cfg(STATION_MODULE, _DEFAULTS)
    return str(cfg.get("operator_name") or "").strip()[:_MAX_OPERATOR_LEN]


def save_station_operator(operator_name: str) -> None:
    cfg = read_module_cfg(STATION_MODULE, _DEFAULTS)
    cfg["operator_name"] = (operator_name or "").strip()[:_MAX_OPERATOR_LEN]
    write_module_cfg(STATION_MODULE, cfg)
