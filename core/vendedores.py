from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core.json_store import (
    ConfigurationWriteError, preserve_entry_fields, read_json_config, require, write_json_config,
)
from core.logging_config import get_logger, log_exception

_logger = get_logger(__name__)


def _store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_exception(_logger, "Vendor configuration directory unavailable", exc)
        raise ConfigurationWriteError(base / "vendedores.json", "Não foi possível acessar a pasta de vendedores.") from exc
    return base / "vendedores.json"


@dataclass
class VendorFolder:
    path: str
    last_checked_at: str = ""
    last_check_ok: Optional[bool] = None
    last_check_detail: str = ""


@dataclass
class Vendedor:
    key: str
    name: str
    active: bool = True
    priority: int = 100
    notes: str = ""
    folders: List[VendorFolder] = field(default_factory=list)


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "vendedor"


def _coerce_folder(d: dict) -> VendorFolder:
    ok = d.get("last_check_ok", None)
    return VendorFolder(
        path=str(d.get("path", "") or ""),
        last_checked_at=str(d.get("last_checked_at", "") or ""),
        last_check_ok=bool(ok) if isinstance(ok, bool) else None,
        last_check_detail=str(d.get("last_check_detail", "") or ""),
    )


def _coerce(d: dict) -> Vendedor:
    return Vendedor(
        key=str(d.get("key", "")) or _slugify(str(d.get("name", ""))),
        name=str(d.get("name", "")),
        active=bool(d.get("active", True)),
        priority=_coerce_priority(d.get("priority", 100)),
        notes=str(d.get("notes", "") or ""),
        folders=[_coerce_folder(f) for f in (d.get("folders") or []) if isinstance(f, dict)],
    )


def _coerce_priority(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 100


def _save_raw(data: List[dict]) -> None:
    path = _store_path()
    previous = read_json_config(path, [], validator=_validate_vendedores)
    previous = [{**item, "key": _coerce(item).key} for item in previous]
    data = preserve_entry_fields(previous, data)
    write_json_config(path, data, validator=_validate_vendedores)


def _validate_vendedores(raw: object, path: Path) -> None:
    require(isinstance(raw, list), path, "$", "Esperada uma lista de vendedores.")
    seen = set()
    for index, item in enumerate(raw):
        field_name = f"[{index}]"
        require(isinstance(item, dict), path, field_name, "Esperado um objeto de vendedor.")
        for name in ("key", "name", "notes"):
            if name in item:
                require(isinstance(item[name], str), path, f"{field_name}.{name}", "Esperado texto.")
        if "active" in item:
            require(isinstance(item["active"], bool), path, f"{field_name}.active", "Esperado verdadeiro ou falso.")
        if "priority" in item:
            require(isinstance(item["priority"], (int, float)) and not isinstance(item["priority"], bool),
                     path, f"{field_name}.priority", "Esperado número inteiro.")
        if "folders" in item:
            require(isinstance(item["folders"], list), path, f"{field_name}.folders", "Esperada uma lista de pastas.")
            for fi, folder in enumerate(item["folders"]):
                ffield = f"{field_name}.folders[{fi}]"
                require(isinstance(folder, dict), path, ffield, "Esperado um objeto de pasta.")
                if "path" in folder:
                    require(isinstance(folder["path"], str), path, f"{ffield}.path", "Esperado texto.")
        identity = _coerce(item).key
        require(identity not in seen, path, f"{field_name}.key", "Identificador de vendedor repetido.")
        seen.add(identity)


def load_vendedores() -> List[Vendedor]:
    p = _store_path()
    raw = read_json_config(p, [], validator=_validate_vendedores)
    return [_coerce(d) for d in raw]


def save_vendedores(vendedores: List[Vendedor]) -> None:
    _save_raw([asdict(v) for v in vendedores])


def find_vendedor_by_key(key: str, vendedores: Optional[List[Vendedor]] = None) -> Optional[Vendedor]:
    vendedores = vendedores if vendedores is not None else load_vendedores()
    return next((v for v in vendedores if v.key == key), None)


def add_or_update_vendedor(
    vendedores: List[Vendedor],
    *,
    key: Optional[str] = None,
    name: str,
    active: bool = True,
    priority: int = 100,
    notes: str = "",
) -> List[Vendedor]:
    """
    Retorna uma NOVA lista com o vendedor adicionado (key vazio/None) ou
    atualizado (key existente). Nunca altera `folders` — isso é feito só por
    add_vendedor_folder/remove_vendedor_folder. Não grava em disco — use
    save_vendedores().
    """
    name = name.strip()
    notes = notes or ""
    if not name:
        raise ValueError("Informe o nome do vendedor.")
    priority = _coerce_priority(priority)

    out = list(vendedores)

    if key:
        for i, v in enumerate(out):
            if v.key == key:
                out[i] = Vendedor(
                    key=v.key, name=name, active=active, priority=priority, notes=notes, folders=v.folders,
                )
                _check_unique_name(out)
                return out
        raise ValueError("Vendedor não encontrado para atualizar.")

    new_key = _slugify(name)
    if any(v.key == new_key for v in out):
        suffix = 2
        while any(v.key == f"{new_key}_{suffix}" for v in out):
            suffix += 1
        new_key = f"{new_key}_{suffix}"

    out.append(Vendedor(key=new_key, name=name, active=active, priority=priority, notes=notes, folders=[]))
    _check_unique_name(out)
    return out


def _check_unique_name(vendedores: List[Vendedor]) -> None:
    seen = {}
    for v in vendedores:
        low = v.name.strip().lower()
        if low in seen and seen[low] != v.key:
            raise ValueError(f"Já existe um vendedor com o nome '{v.name}'.")
        seen[low] = v.key


def remove_vendedor(vendedores: List[Vendedor], key: str) -> List[Vendedor]:
    return [v for v in vendedores if v.key != key]


def add_vendedor_folder(vendedores: List[Vendedor], key: str, path: str) -> List[Vendedor]:
    path = (path or "").strip()
    if not path:
        raise ValueError("Informe o caminho da pasta.")
    out = list(vendedores)
    for i, v in enumerate(out):
        if v.key == key:
            if any(f.path.strip().lower() == path.lower() for f in v.folders):
                raise ValueError("Esta pasta já está cadastrada para este vendedor.")
            new_folders = list(v.folders) + [VendorFolder(path=path)]
            out[i] = Vendedor(key=v.key, name=v.name, active=v.active, priority=v.priority, notes=v.notes, folders=new_folders)
            return out
    raise ValueError("Vendedor não encontrado.")


def remove_vendedor_folder(vendedores: List[Vendedor], key: str, path: str) -> List[Vendedor]:
    target = path.strip().lower()
    out = list(vendedores)
    for i, v in enumerate(out):
        if v.key == key:
            new_folders = [f for f in v.folders if f.path.strip().lower() != target]
            out[i] = Vendedor(key=v.key, name=v.name, active=v.active, priority=v.priority, notes=v.notes, folders=new_folders)
            return out
    raise ValueError("Vendedor não encontrado.")


def set_vendedor_folder_access_result(
    vendedores: List[Vendedor], key: str, path: str, *, ok: bool, detail: str = "", checked_at: str = "",
) -> List[Vendedor]:
    target = path.strip().lower()
    out = list(vendedores)
    for i, v in enumerate(out):
        if v.key == key:
            new_folders = list(v.folders)
            for fi, f in enumerate(new_folders):
                if f.path.strip().lower() == target:
                    new_folders[fi] = VendorFolder(
                        path=f.path, last_checked_at=checked_at, last_check_ok=ok, last_check_detail=detail,
                    )
                    out[i] = Vendedor(key=v.key, name=v.name, active=v.active, priority=v.priority, notes=v.notes, folders=new_folders)
                    return out
            raise ValueError("Pasta não encontrada para este vendedor.")
    raise ValueError("Vendedor não encontrado.")


def test_folder_access(path: str) -> Tuple[bool, str]:
    """Testa, de forma síncrona e única (sem retry/cache/thread — ver plano de
    implementação), se a pasta está acessível e listável AGORA. Nunca levanta
    exceção: qualquer falha (pasta inexistente, sem permissão, caminho de rede
    fora do ar) vira (False, motivo). Pode bloquear a UI pelo tempo de timeout
    do SMB num caminho de rede morto — risco aceito, documentado no manual."""
    path = (path or "").strip()
    if not path:
        return False, "Caminho vazio."
    try:
        p = Path(path)
        if not p.exists():
            return False, "Caminho não encontrado."
        if not p.is_dir():
            return False, "O caminho não é uma pasta."
        os.listdir(p)
        return True, "Acesso confirmado."
    except PermissionError:
        return False, "Sem permissão de acesso."
    except OSError as exc:
        return False, f"Falha ao acessar: {exc.strerror or exc}"
