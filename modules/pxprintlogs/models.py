from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List


@dataclass
class Job:
    end_time: datetime
    document: str
    fabric: str
    height_mm: float
    vpos_mm: float
    real_mm: float
    src_file: str

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