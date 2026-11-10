"""Logging técnico local, independente dos arquivos originais das impressoras."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import traceback


class _SafeFormatter(logging.Formatter):
    def formatException(self, exc_info) -> str:
        # Não inclui locais, mensagens de exceção (que podem conter dados de
        # produção/senhas), nem linhas de código potencialmente contendo segredos.
        lines = ["Traceback (most recent call last):"]
        current = exc_info[1]
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            for frame in traceback.extract_tb(current.__traceback__):
                lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
            metadata = []
            for key in ("errno", "sqlite_errorcode"):
                value = getattr(current, key, None)
                if isinstance(value, int):
                    metadata.append(f"{key}={value}")
            lines.append(type(current).__name__ + (" (" + ", ".join(metadata) + ")" if metadata else ""))
            current = current.__cause__
            if current is not None:
                lines.append("Caused by:")
        return "\n".join(lines)


def default_log_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                    or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "Nexor" / "logs"


def get_logger(name: str) -> logging.Logger:
    base = logging.getLogger("nexor")
    base.propagate = False
    # Imports e bibliotecas também podem usar o serviço antes da inicialização.
    # Nunca envia traceback sem sanitização ao lastResort/root logger.
    if not base.handlers:
        base.addHandler(logging.NullHandler())
    return logging.getLogger(name if name == "nexor" or name.startswith("nexor.") else f"nexor.{name}")


def configure_logging(log_dir: str | Path | None = None, *, level: int = logging.INFO) -> Path:
    directory = Path(log_dir) if log_dir is not None else default_log_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "nexor.log"
    handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(_SafeFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    base = logging.getLogger("nexor")
    base.propagate = False
    for previous in base.handlers[:]:
        base.removeHandler(previous)
        previous.close()
    base.addHandler(handler)
    base.setLevel(level)
    return path


def log_exception(logger: logging.Logger, message: str, exc: BaseException) -> None:
    """Use mensagens fixas, sem parâmetros SQL, senhas, hashes ou documentos."""
    # Um logger pode ter sido guardado antes de fechar/reconfigurar handlers.
    # Reestabelece a barreira contra o lastResort também nesse caminho.
    get_logger(logger.name)
    logger.error(message, exc_info=(type(exc), exc, exc.__traceback__))
