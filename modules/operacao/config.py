from __future__ import annotations

import os
from pathlib import Path

from core.migrate import migrate_legacy_path
from core.print_types import DEFAULT_RULES, DEFAULT_SUBTYPES
from core.json_store import (
    ConfigurationWriteError, read_json_config, require, validate_known_fields, write_json_config,
)
from core.logging_config import get_logger, log_exception

_logger = get_logger(__name__)

MODULE_NAME = "Operacao"

_APPDATA = Path(os.environ.get("APPDATA") or str(Path.home()))
APP_DIR = _APPDATA / "Nexor" / MODULE_NAME
migrate_legacy_path(_APPDATA / "ProjetoJocasta" / "PXPrintLogs", APP_DIR)
try:
    APP_DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    log_exception(_logger, "Operation configuration directory unavailable", exc)
    raise ConfigurationWriteError(APP_DIR / "config.json", "Não foi possível acessar a pasta das configurações de Operação.") from exc

CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "space_filenames": [],
    "group_consecutive_spaces": False,
    "print_type_rules": [dict(r) for r in DEFAULT_RULES],
    "print_type_subtypes": list(DEFAULT_SUBTYPES),
    "operators": [],
    # Pasta usada pro diálogo de "Importar logs" quando a impressora do
    # lote ainda não é conhecida (primeira importação da sessão), ou
    # quando a impressora já conhecida não tem uma pasta própria cadastrada
    # (ver core.printers.Printer.log_import_dir) — fallback geral, não por
    # máquina.
    "general_log_dir": "",
}


def load_cfg() -> dict:
    raw = read_json_config(CFG_PATH, DEFAULT_CFG, validator=_validate_cfg)
    return {**DEFAULT_CFG, **raw}


def save_cfg(cfg: dict) -> None:
    _validate_cfg(cfg, CFG_PATH)
    previous = read_json_config(CFG_PATH, {}, validator=_validate_cfg)
    merged = {**previous, **cfg}
    for name, key in (("operators", "identifier"), ("print_type_rules", "id")):
        if name not in cfg:
            continue
        old_items = previous.get(name, [])
        old_by_id = {str(item.get(key, "")).casefold(): item for item in old_items if item.get(key)}
        old_by_name = {item.get("name"): item for item in old_items}
        entries = []
        for item in cfg[name]:
            old = old_by_id.get(str(item.get(key, "")).casefold(), old_by_name.get(item.get("name"), {}))
            entries.append({**old, **item})
        merged[name] = entries
    write_json_config(CFG_PATH, merged, validator=_validate_cfg)


def _validate_cfg(raw: object, path: Path) -> None:
    validate_known_fields(raw, DEFAULT_CFG, path)
    for name in ("print_type_subtypes",):
        if name in raw:
            require(all(isinstance(item, str) for item in raw[name]), path, name, "Esperada uma lista de textos.")
    for name in ("operators", "print_type_rules"):
        for index, item in enumerate(raw.get(name, [])):
            field = f"{name}[{index}]"
            require(isinstance(item, dict), path, field, "Esperado um objeto de configuração.")
            required = ("identifier", "name") if name == "operators" else ("name", "pattern")
            for key in required:
                require(isinstance(item.get(key), str) and bool(item[key].strip()), path, f"{field}.{key}", "Esperado texto não vazio.")
            if name == "operators":
                require(item["identifier"].isascii() and item["identifier"].isalpha(), path, f"{field}.identifier", "O identificador deve conter somente letras.")
            else:
                for key in ("id", "match_mode", "pedido_mode", "pedido_fixed"):
                    if key in item:
                        require(isinstance(item[key], str), path, f"{field}.{key}", "Esperado texto.")
                for key in ("active", "custom_regex", "warn_duplicate"):
                    if key in item:
                        require(isinstance(item[key], bool), path, f"{field}.{key}", "Esperado verdadeiro ou falso.")
                if "examples" in item:
                    require(isinstance(item["examples"], list) and all(isinstance(value, str) for value in item["examples"]), path, f"{field}.examples", "Esperada uma lista de textos.")
                if item.get("components") is not None:
                    require(isinstance(item["components"], list) and all(isinstance(value, dict) for value in item["components"]), path, f"{field}.components", "Esperada uma lista de componentes.")
