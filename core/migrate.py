from __future__ import annotations

import shutil
from pathlib import Path


def migrate_legacy_path(old: Path, new: Path) -> None:
    """
    Migração única de uma pasta/arquivo de configuração antigo (nome de
    módulo/produto anterior) para o caminho novo — usada no rebrand pra
    Nexor, pra não perder tecidos, pedaços cortados, impressoras e
    preferências já cadastrados.

    Se `new` já existe, ou `old` não existe, não faz nada. Nunca lança
    exceção (é best-effort: uma falha aqui não pode impedir o app de abrir).
    """
    try:
        if new.exists() or not old.exists():
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            shutil.copytree(old, new)
        else:
            shutil.copy2(old, new)
    except Exception:
        pass
