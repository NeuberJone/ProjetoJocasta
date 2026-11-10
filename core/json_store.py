"""Validated JSON configuration with atomic replacement and explicit recovery.

Only a missing file selects defaults. Existing invalid or unreadable files are
never replaced implicitly; callers must deliberately opt into recovery.
"""
from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from core.logging_config import get_logger, log_exception

Validator = Callable[[Any, Path], None]
_logger = get_logger(__name__)


class ConfigurationError(Exception):
    category = "configuração"

    def __init__(self, path: Path, detail: str, *, field: str | None = None):
        self.path = Path(path)
        self.field = field
        self.detail = detail
        location = f" (campo {field})" if field else ""
        super().__init__(
            f"Falha de {self.category}{location}: {self.path}\n{detail}\n"
            "O arquivo existente foi preservado. Verifique acesso/permissões; "
            "para conteúdo inválido, restaure uma cópia válida ou use a recuperação explícita."
        )


class ConfigurationReadError(ConfigurationError):
    category = "leitura da configuração"


class ConfigurationValidationError(ConfigurationError):
    category = "validação da configuração"


class ConfigurationWriteError(ConfigurationError):
    category = "gravação da configuração"


ConfigError = ConfigurationError


def require(condition: bool, path: Path, field: str, detail: str) -> None:
    if not condition:
        raise ConfigurationValidationError(path, detail, field=field)


def validate_object(value: Any, path: Path) -> None:
    require(isinstance(value, dict), path, "$", "Esperado um objeto JSON.")


def validate_known_fields(value: dict, defaults: dict, path: Path) -> None:
    """Validate scalar/container types without rejecting extension keys."""
    validate_object(value, path)
    for key, default in defaults.items():
        if key not in value:
            continue
        item = value[key]
        if isinstance(default, bool):
            valid = isinstance(item, bool)
        elif isinstance(default, (int, float)):
            valid = isinstance(item, (int, float)) and finite_number(item)
        else:
            valid = isinstance(item, type(default))
        require(valid, path, key, "Tipo de valor incompatível com a configuração.")


def finite_number(value: Any) -> bool:
    # Some legacy files contain numeric strings; keep accepting those.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("nonfinite JSON number")


def _parse_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def read_json_config(path: Path, defaults: Any, *, validator: Validator | None = None) -> Any:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        value = copy.deepcopy(defaults)
        if validator:
            validator(value, path)
        return value
    except UnicodeError as exc:
        log_exception(_logger, "Configuration encoding validation failed", exc)
        raise ConfigurationValidationError(path, "O arquivo não contém texto UTF-8 válido.") from exc
    except OSError as exc:
        log_exception(_logger, "Configuration read failed", exc)
        raise ConfigurationReadError(path, "Não foi possível ler o arquivo. Verifique permissões e disponibilidade da pasta.") from exc
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant, parse_float=_parse_float)
    except (ValueError, RecursionError) as exc:
        log_exception(_logger, "Configuration JSON validation failed", exc)
        detail = "JSON vazio ou inválido; chaves repetidas e números não finitos não são aceitos."
        if isinstance(exc, json.JSONDecodeError):
            detail += f" Linha {exc.lineno}, coluna {exc.colno}."
        raise ConfigurationValidationError(path, detail) from exc
    if validator:
        validator(value, path)
    return value


def _encode(path: Path, value: Any, validator: Validator | None) -> str:
    if validator:
        validator(value, path)
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        log_exception(_logger, "Configuration serialization validation failed", exc)
        raise ConfigurationValidationError(path, "Os valores não podem ser representados como JSON válido.") from exc


def _atomic_write(path: Path, text: str) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except (OSError, UnicodeError) as exc:
        log_exception(_logger, "Atomic configuration write failed", exc)
        raise ConfigurationWriteError(path, "Não foi possível concluir a gravação atômica. Verifique permissões e espaço livre.") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                log_exception(_logger, "Configuration temporary cleanup failed", exc)


def write_json_config(path: Path, value: Any, *, validator: Validator | None = None) -> None:
    path = Path(path)
    text = _encode(path, value, validator)
    # Prevent a later save from silently destroying an invalid existing file.
    read_json_config(path, value, validator=validator)
    _atomic_write(path, text)


def recover_json_config(path: Path, defaults: Any, *, validator: Validator | None = None) -> Path | None:
    """Explicit reset: preserve source bytes in a unique sibling before replacing.

    Returns the preserved file path, or None when the source did not exist.
    No caller invokes this automatically on a read or write failure.
    """
    path = Path(path)
    text = _encode(path, defaults, validator)
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        _atomic_write(path, text)
        return None
    except OSError as exc:
        log_exception(_logger, "Configuration recovery read failed", exc)
        raise ConfigurationReadError(path, "Não foi possível preservar o arquivo para recuperação.") from exc
    backup = path.with_name(f"{path.name}.recovery-{uuid.uuid4().hex}.bak")
    try:
        with backup.open("xb") as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        log_exception(_logger, "Configuration recovery preservation failed", exc)
        raise ConfigurationWriteError(path, "A cópia de recuperação não pôde ser concluída; o original não foi substituído.") from exc
    _atomic_write(path, text)
    return backup


def preserve_entry_fields(previous: list[dict], updated: list[dict], *, key: str = "key") -> list[dict]:
    """Keep extension metadata for retained identities, while allowing removal."""
    old = {item.get(key): item for item in previous if item.get(key)}
    return [{**old.get(item.get(key), {}), **item} for item in updated]
