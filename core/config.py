from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from core.json_store import (
    ConfigError,
    ConfigurationError,
    ConfigurationWriteError,
    read_json_config,
    require,
    validate_known_fields,
    validate_object,
    write_json_config,
)
from core.passwords import hash_password, is_legacy_hash, verify_password
from core.logging_config import get_logger, log_exception

APP_NAME = "PXCore"
_logger = get_logger(__name__)


@dataclass
class PXCoreConfig:
    base_dir: str = r"C:\PXCore" if os.name == "nt" else str(Path.home() / "PXCore")
    dev_mode_enabled: bool = False

    # Hash versionado PBKDF2; SHA1 legado só migra após autenticação correta.
    dev_password_hash: str = ""

    # Tema visual do Nexor (ver core/theme.py) — persiste entre execuções.
    theme_name: str = "dark"

    # Identificador curto e opaco desta instalação/banco do Nexor (gerado uma vez, nunca
    # regenerado) — só para desambiguar, na exportação do contexto de produção pro PX Tool
    # Box (ver modules/registros/px_export.py), rollId/jobHash vindos de bases diferentes
    # (esses dois só são únicos DENTRO de uma mesma base printlogs.db, nunca entre
    # instalações diferentes — confirmado lendo core/printlogs_db.py: nenhum dos dois
    # carrega nenhuma informação da origem). NUNCA um identificador de pedido comercial,
    # NUNCA enviado a lugar nenhum além desse arquivo de exportação explícito.
    installation_id: str = ""


def _config_path() -> Path:
    """
    Caminho gravável do config do PXCore:
      - Windows: %APPDATA%\\PXCore\\config.json
      - Linux: ~/.config/PXCore/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.json"
    return Path.home() / ".config" / APP_NAME / "config.json"


def _ensure_dirs(cfg: PXCoreConfig) -> None:
    base = Path(cfg.base_dir)

    # Estrutura padrão. Falhas aqui (ex.: base_dir numa pasta de rede
    # momentaneamente fora do ar) não devem derrubar load_config() — isso
    # faria o caller tratar como "config corrompido" e resetar base_dir pro
    # padrão, apagando a configuração do usuário.
    first_error = None
    for sub in ("lists", "json", "logs", "exports", "temp", "data"):
        try:
            (base / sub).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        log_exception(_logger, "Working directory initialization failed; configured path retained", first_error)



def save_config(cfg: PXCoreConfig) -> None:
    path = _config_path()
    previous = read_json_config(path, {}, validator=_validate_config)
    expected_hash = getattr(cfg, "_migration_expected_hash", None)
    if expected_hash is not None and path.exists() and previous.get("dev_password_hash", "") != expected_hash:
        raise ConfigurationError(path, "A senha salva mudou durante a autenticação. Carregue a configuração novamente antes de tentar outra vez.")
    if getattr(cfg, "_password_update", False):
        # Password changes (especially legacy migrations from a stale in-memory
        # object) update only the credential. Current paths, preferences, IDs,
        # and extension fields on disk remain authoritative.
        data = {
            **asdict(cfg),
            **getattr(cfg, "_raw_config", {}),
            **previous,
            "dev_password_hash": cfg.dev_password_hash,
        }
    else:
        data = {**getattr(cfg, "_raw_config", {}), **previous, **asdict(cfg)}
    # Ordinary theme/path saves must never erase credentials or revert a newer
    # password migration made after this object was loaded.
    if previous.get("dev_password_hash") and not getattr(cfg, "_password_update", False):
        data["dev_password_hash"] = previous["dev_password_hash"]
    if previous.get("installation_id"):
        data["installation_id"] = previous["installation_id"]
    write_json_config(path, data, validator=_validate_config)
    cfg._raw_config = data
    cfg.dev_password_hash = data["dev_password_hash"]
    cfg.installation_id = data["installation_id"]


def _validate_config(raw: Any, path: Path) -> None:
    validate_known_fields(raw, asdict(PXCoreConfig()), path)
    if "base_dir" in raw:
        require(bool(raw["base_dir"].strip()), path, "base_dir", "Informe um diretório de trabalho válido.")


def _merge(cfg: PXCoreConfig, raw: dict[str, Any]) -> PXCoreConfig:
    # Atualiza campos conhecidos sem explodir em chaves desconhecidas
    if isinstance(raw, dict):
        if "base_dir" in raw and raw["base_dir"]:
            cfg.base_dir = str(raw["base_dir"])

        if "dev_mode_enabled" in raw:
            cfg.dev_mode_enabled = bool(raw["dev_mode_enabled"])

        if "dev_password_hash" in raw and raw["dev_password_hash"]:
            cfg.dev_password_hash = str(raw["dev_password_hash"])

        if "theme_name" in raw and raw["theme_name"]:
            cfg.theme_name = str(raw["theme_name"])

        if "installation_id" in raw and raw["installation_id"]:
            cfg.installation_id = str(raw["installation_id"])

    return cfg


def load_config() -> PXCoreConfig:
    """
    Retorna configuração validada. Somente um arquivo ausente usa os padrões.
    Arquivos inválidos/ilegíveis geram ConfigurationError e permanecem intactos.
    """
    path = _config_path()
    raw = read_json_config(path, asdict(PXCoreConfig()), validator=_validate_config)
    cfg = _merge(PXCoreConfig(), raw)
    cfg._raw_config = raw
    if not path.exists():
        save_config(cfg)
    _ensure_dirs(cfg)
    return cfg


def get_installation_id() -> str:
    """Id curto e opaco desta instalação (ver PXCoreConfig.installation_id) — gera e persiste
    na primeira chamada que encontrar o config sem um ainda (nunca regenerado depois:
    instalações já existentes recebem um id estável na primeira exportação de contexto de
    produção, sem precisar de nenhuma ação manual)."""
    cfg = load_config()
    if not cfg.installation_id:
        cfg.installation_id = uuid.uuid4().hex[:12]
        save_config(cfg)
    return cfg.installation_id

# =========================
# 🔐 Dev password helpers
# =========================
def verify_dev_password(cfg: PXCoreConfig, password: str) -> bool:
    # Existing files are authoritative, even when their password was explicitly
    # cleared. A standalone cfg remains usable when no file exists yet.
    persisted = read_json_config(_config_path(), {"dev_password_hash": cfg.dev_password_hash}, validator=_validate_config)
    current_hash = persisted.get("dev_password_hash", "")
    if not verify_password(current_hash, password):
        return False
    if is_legacy_hash(current_hash):
        previous_expected = getattr(cfg, "_migration_expected_hash", None)
        cfg._migration_expected_hash = current_hash
        try:
            set_dev_password(cfg, password)
        finally:
            cfg._migration_expected_hash = previous_expected
    else:
        cfg.dev_password_hash = current_hash
    return True


def set_dev_password(cfg: PXCoreConfig, new_password: str) -> None:
    previous = cfg.dev_password_hash
    previous_authorization = getattr(cfg, "_password_update", False)
    cfg.dev_password_hash = hash_password(new_password)
    cfg._password_update = True
    try:
        save_config(cfg)
    except Exception:
        cfg.dev_password_hash = previous
        raise
    finally:
        cfg._password_update = previous_authorization

# adicione no core/config.py

def module_config_path(module_name: str) -> Path:
    """
    Caminho gravável de config por módulo:
      - Windows: %APPDATA%\\PXCore\\modules\\<module_name>.json
      - Linux: ~/.config/PXCore/modules/<module_name>.json
    """
    base_dir = _config_path().parent  # .../PXCore
    mod_dir = base_dir / "modules"
    try:
        mod_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_exception(_logger, "Module configuration directory creation failed", exc)
        raise ConfigurationWriteError(mod_dir / f"{module_name}.json", "Não foi possível acessar a pasta das configurações do módulo.") from exc
    return mod_dir / f"{module_name}.json"


def read_module_cfg(module_name: str, defaults: dict) -> dict:
    """
    Lê config do módulo; erros existentes são explícitos e nunca recriam dados.
    """
    path = module_config_path(module_name)
    def validate(raw: Any, source: Path) -> None:
        validate_known_fields(raw, defaults, source)
    raw = read_json_config(path, defaults, validator=validate)
    return {**defaults, **raw}


def write_module_cfg(module_name: str, cfg: dict) -> None:
    path = module_config_path(module_name)
    validate_object(cfg, path)
    def validate(raw: Any, source: Path) -> None:
        validate_known_fields(raw, cfg, source)
    previous = read_json_config(path, {}, validator=validate)
    write_json_config(path, {**previous, **cfg}, validator=validate)
