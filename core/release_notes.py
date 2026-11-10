"""Notas da versão instalada, extraídas do changelog incluído no app."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class ReleaseNotes:
    date: str
    sections: dict[str, list[str]]


def parse_release_notes(changelog: str, version: str) -> ReleaseNotes | None:
    """Seleciona apenas a versão pedida, sem incluir itens não lançados."""
    categories = {
        "Added": "Implementado",
        "Changed": "Alterado",
        "Removed": "Removido",
        "Fixed": "Corrigido",
    }
    notes = None
    category = None
    for raw_line in changelog.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if notes is not None:
                break
            header = re.fullmatch(r"## \[([^\]]+)\](?:\s*-\s*(.+))?", line)
            if header and header[1] == version:
                notes = ReleaseNotes(
                    date=header[2] or "",
                    sections={title: [] for title in categories.values()},
                )
        elif notes is not None:
            if line.startswith("### "):
                category = categories.get(line[4:])
            elif category and line.startswith("- "):
                notes.sections[category].append(line[2:])
            elif category and line and notes.sections[category]:
                notes.sections[category][-1] += " " + line
    return notes


def load_release_notes(version: str) -> ReleaseNotes | None:
    # O PyInstaller preserva o caminho relativo de core/__file__ no bundle;
    # o changelog fica na raiz tanto no projeto quanto no executável.
    path = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    return parse_release_notes(path.read_text(encoding="utf-8-sig"), version)
