"""Nome padrão do rolo/lote (Operação e Planejador) — máquina + data +
número sequencial (core.printlogs_db.next_roll_sequence), com o
identificador deste computador (core.station) logo depois da máquina
quando configurado, pra diferenciar rolos gerados em computadores
diferentes caso o número sequencial venha a coincidir (ex.: pasta de rede
fora do ar num dos PCs no momento de gerar o número)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.station import load_station_id


def build_roll_name(machine: str, seq: int, *, when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    machine_part = machine or "M?"
    station = load_station_id()
    prefix = f"{machine_part}_{station}" if station else machine_part
    return f"{prefix}_{when.strftime('%d-%m-%Y')}_{seq:04d}"
