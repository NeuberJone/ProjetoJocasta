"""Etapa B — localização de pedidos: índice local dos diretórios dos
vendedores cadastrados (ver core/vendedores.py) + motor de correspondência
entre o nome de pedido extraído do log e as pastas indexadas.

Escopo desta etapa (ver plano original, seção 19 — "Ordem recomendada de
implementação"): só o índice e o motor de busca, como funções puras e
independentes de interface. Nada aqui decide ou grava automaticamente um
vínculo pedido<->vendedor (isso é a Etapa C, em cima de
core.printlogs_db.upsert_vendor_link) nem abre/lista PDFs dentro da pasta do
pedido (Etapa D), nem é chamado ainda pela UI (Etapa E) — propositalmente,
pra manter esta etapa pequena e revisável.

Estrutura real assumida (ver especificação original, seção 4): cada pasta
raiz cadastrada para um vendedor contém, no primeiro nível, pastas de
cliente/projeto; dentro de cada uma delas, uma ou mais pastas de PEDIDO
INDIVIDUAL (ex.: "ESCOLINHA DOUGLAS AMÉRICA" e "ESCOLINHA DOUGLAS AMÉRICA 2"
são dois pedidos diferentes do mesmo cliente, não duas versões do mesmo
pedido). Esta é a única estrutura reconhecida por ora — outras estruturas
reais que apareçam ficam para uma revisão futura, não assumida aqui.
"""
from __future__ import annotations

import difflib
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.json_store import ConfigurationWriteError, read_json_config, require, write_json_config
from core.logging_config import get_logger, log_exception
from core.vendedores import Vendedor, load_vendedores

_logger = get_logger(__name__)

MATCH_EXACT = "exact"
MATCH_FUZZY = "fuzzy"

# Abaixo disso, uma aproximação não é útil como sugestão — é só ruído.
DEFAULT_FUZZY_THRESHOLD = 0.82
DEFAULT_MAX_FUZZY_CANDIDATES = 5


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_order_name(name: str) -> str:
    """Normalização segura pra comparar nome de pedido (ver especificação,
    seção 6): remove acento, ignora caixa, funde pontuação/espaços — mas
    NUNCA remove números, porque eles são o que diferencia pedidos distintos
    do mesmo cliente (ex.: "ESCOLINHA DOUGLAS AMÉRICA" vs "...AMÉRICA 2")."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class IndexedOrderFolder:
    vendor_key: str
    vendor_name_snapshot: str
    root_path: str          # pasta raiz cadastrada (VendorFolder.path) que originou esta entrada
    path: str                # pasta do PEDIDO individual (nível 3)
    display_name: str        # nome real da pasta do pedido
    normalized_name: str
    client_folder: str       # nome da pasta de cliente/projeto (nível 2) — só pra exibição/contexto
    indexed_at: str


@dataclass
class VendorIndexState:
    generated_at: str = ""
    folders: List[IndexedOrderFolder] = field(default_factory=list)
    # Erros de acesso por pasta raiz nesta rodada (não impedem o restante do
    # índice de ser usado — ver refresh_order_index).
    errors: List[str] = field(default_factory=list)


@dataclass
class _WalkResult:
    found: List[IndexedOrderFolder]
    errors: List[str]
    # True quando a pasta RAIZ em si não respondeu (nem chegou a listar as
    # pastas de cliente) — refresh_order_index preserva tudo que já era
    # conhecido dela nesse caso. False quando a raiz respondeu normalmente e
    # só uma ou mais pastas de CLIENTE específicas falharam — aí `found` já
    # inclui tudo que foi encontrado de verdade nas pastas que responderam,
    # nunca deve ser descartado, e `failed_client_names` diz quais pastas de
    # cliente (pelo nome) precisam cair de volta pro que já era conhecido
    # delas, nunca a raiz inteira.
    root_unavailable: bool
    failed_client_names: set


def _walk_vendor_root(vendor: Vendedor, root: str) -> _WalkResult:
    found: List[IndexedOrderFolder] = []
    errors: List[str] = []
    failed_client_names: set = set()
    root_path = Path(root)
    try:
        client_dirs = [d for d in root_path.iterdir() if d.is_dir()]
    except OSError as exc:
        errors.append(f"{root}: {exc.strerror or exc}")
        return _WalkResult(found, errors, root_unavailable=True, failed_client_names=failed_client_names)

    now = _now_iso()
    for client_dir in client_dirs:
        try:
            order_dirs = [d for d in client_dir.iterdir() if d.is_dir()]
        except OSError as exc:
            errors.append(f"{client_dir}: {exc.strerror or exc}")
            failed_client_names.add(client_dir.name)
            continue
        for order_dir in order_dirs:
            found.append(IndexedOrderFolder(
                vendor_key=vendor.key,
                vendor_name_snapshot=vendor.name,
                root_path=str(root),
                path=str(order_dir),
                display_name=order_dir.name,
                normalized_name=normalize_order_name(order_dir.name),
                client_folder=client_dir.name,
                indexed_at=now,
            ))
    return _WalkResult(found, errors, root_unavailable=False, failed_client_names=failed_client_names)


def build_order_index(vendedores: Optional[List[Vendedor]] = None) -> VendorIndexState:
    """Indexação completa (do zero) das pastas de todos os vendedores
    ATIVOS. Síncrona — quem chamar isto fora de um teste/console deve
    colocar numa thread própria (ver módulo docstring: a integração com a
    UI, inclusive o cuidado de não travar o Tkinter, é Etapa E)."""
    vendedores = vendedores if vendedores is not None else load_vendedores()
    folders: List[IndexedOrderFolder] = []
    errors: List[str] = []
    for v in vendedores:
        if not v.active:
            continue
        for vf in v.folders:
            result = _walk_vendor_root(v, vf.path)
            folders.extend(result.found)
            errors.extend(result.errors)
    return VendorIndexState(generated_at=_now_iso(), folders=folders, errors=errors)


def refresh_order_index(
    vendedores: Optional[List[Vendedor]] = None, *, previous: Optional[VendorIndexState] = None,
) -> VendorIndexState:
    """Reindexa, mas preserva os resultados já conhecidos de uma pasta raiz
    (ou de uma pasta de CLIENTE específica dentro dela) que ficou
    temporariamente indisponível nesta rodada (ver especificação, seção 8:
    "Uma origem indisponível não deverá apagar automaticamente os
    resultados previamente conhecidos.") — só substitui as entradas de uma
    pasta raiz/cliente quando ela responde de novo.

    Achado de revisão de código: uma falha numa única pasta de CLIENTE (não
    a raiz em si) descartava TODAS as pastas de cliente que responderam
    normalmente nesta mesma rodada, caindo pro snapshot antigo da raiz
    inteira — pedidos novos descobertos nas pastas saudáveis ficavam
    invisíveis até a pasta com problema voltar a responder. Corrigido:
    quando é a raiz em si que não responde (`root_unavailable`), continua
    preservando tudo que já era conhecido dela, como antes; quando só uma
    ou mais pastas de cliente específicas falham, mantém o que foi
    encontrado de verdade nas que responderam e só cai pro conhecido antes
    nas que falharam, nunca na raiz inteira."""
    vendedores = vendedores if vendedores is not None else load_vendedores()
    previous = previous if previous is not None else load_order_index()

    previous_by_root: Dict[Tuple[str, str], List[IndexedOrderFolder]] = {}
    previous_by_client: Dict[Tuple[str, str, str], List[IndexedOrderFolder]] = {}
    for f in previous.folders:
        previous_by_root.setdefault((f.vendor_key, f.root_path), []).append(f)
        previous_by_client.setdefault((f.vendor_key, f.root_path, f.client_folder), []).append(f)

    folders: List[IndexedOrderFolder] = []
    errors: List[str] = []
    for v in vendedores:
        if not v.active:
            continue
        for vf in v.folders:
            result = _walk_vendor_root(v, vf.path)
            errors.extend(result.errors)
            if result.root_unavailable:
                folders.extend(previous_by_root.get((v.key, vf.path), []))
                continue
            folders.extend(result.found)
            for client_name in result.failed_client_names:
                folders.extend(previous_by_client.get((v.key, vf.path, client_name), []))
    return VendorIndexState(generated_at=_now_iso(), folders=folders, errors=errors)


@dataclass
class OrderCandidate:
    vendor_key: str
    vendor_name_snapshot: str
    path: str
    display_name: str
    client_folder: str
    match_kind: str  # MATCH_EXACT | MATCH_FUZZY
    score: float  # 1.0 pra exato; similaridade (0..1) pra aproximado


def find_order_candidates(
    pedido_name: str,
    index: VendorIndexState,
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    max_fuzzy_candidates: int = DEFAULT_MAX_FUZZY_CANDIDATES,
) -> List[OrderCandidate]:
    """Motor de correspondência (ver especificação, seção 6 — "Prioridade da
    correspondência"): primeiro tenta correspondência EXATA do nome
    normalizado; só cai pra aproximada (difflib, só como sugestão) quando não
    houver nenhuma exata. Nunca decide um vínculo por conta própria — quando
    há mais de um candidato exato (pedido com o mesmo nome em vendedores
    diferentes), retorna todos, pra quem chamar apresentar a ambiguidade e
    pedir confirmação manual, igual ao exemplo da especificação."""
    target = normalize_order_name(pedido_name)
    if not target:
        return []

    exact = [
        OrderCandidate(
            vendor_key=f.vendor_key, vendor_name_snapshot=f.vendor_name_snapshot, path=f.path,
            display_name=f.display_name, client_folder=f.client_folder, match_kind=MATCH_EXACT, score=1.0,
        )
        for f in index.folders if f.normalized_name == target
    ]
    if exact:
        return exact

    scored: List[OrderCandidate] = []
    for f in index.folders:
        ratio = difflib.SequenceMatcher(None, target, f.normalized_name).ratio()
        if ratio >= fuzzy_threshold:
            scored.append(OrderCandidate(
                vendor_key=f.vendor_key, vendor_name_snapshot=f.vendor_name_snapshot, path=f.path,
                display_name=f.display_name, client_folder=f.client_folder, match_kind=MATCH_FUZZY, score=ratio,
            ))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:max_fuzzy_candidates]


def folder_for_vendor(pedido_name: str, index: VendorIndexState, vendor_key: str) -> Optional[str]:
    """Caminho da pasta do pedido dentro da raiz do vendedor já
    identificado/confirmado — usado depois que o vendedor já está resolvido,
    pra achar a pasta certa onde descobrir/vincular o PDF (ver
    core.order_pdfs). Reaproveitado por Registros e pelo painel de Operação
    (Parte 1 da conclusão do recurso), pra não duplicar a mesma busca."""
    match = next((c for c in find_order_candidates(pedido_name, index) if c.vendor_key == vendor_key), None)
    return match.path if match else None


_INDEX_STORE_FILENAME = "order_index.json"


def _index_store_path() -> Path:
    appdata = Path(os.environ.get("APPDATA") or str(Path.home()))
    base = appdata / "Nexor"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log_exception(_logger, "Order index directory unavailable", exc)
        raise ConfigurationWriteError(base / _INDEX_STORE_FILENAME, "Não foi possível acessar a pasta do índice de pedidos.") from exc
    return base / _INDEX_STORE_FILENAME


def _validate_index(raw: object, path: Path) -> None:
    require(isinstance(raw, dict), path, "$", "Esperado um objeto de índice.")
    if "folders" in raw:
        require(isinstance(raw["folders"], list), path, "folders", "Esperada uma lista de pastas indexadas.")
        for i, item in enumerate(raw["folders"]):
            require(isinstance(item, dict), path, f"folders[{i}]", "Esperado um objeto de pasta indexada.")
    if "errors" in raw:
        require(isinstance(raw["errors"], list), path, "errors", "Esperada uma lista de erros.")


_INDEXED_FOLDER_FIELDS = (
    "vendor_key", "vendor_name_snapshot", "root_path", "path", "display_name", "normalized_name",
    "client_folder", "indexed_at",
)


def load_order_index() -> VendorIndexState:
    """Cache local do índice (não é dado histórico/auditável — é só um
    resultado de varredura, inteiramente reconstruível por
    build_order_index/refresh_order_index; por isso vive num JSON próprio em
    %APPDATA%/Nexor, igual a printers.json/vendedores.json, e não nas
    tabelas do printlogs.db)."""
    path = _index_store_path()
    defaults = {"generated_at": "", "folders": [], "errors": []}
    raw = read_json_config(path, defaults, validator=_validate_index)
    folders = [
        IndexedOrderFolder(**{k: str(d.get(k, "") or "") for k in _INDEXED_FOLDER_FIELDS})
        for d in raw.get("folders", []) if isinstance(d, dict)
    ]
    return VendorIndexState(
        generated_at=str(raw.get("generated_at", "") or ""),
        folders=folders,
        errors=[str(e) for e in raw.get("errors", [])],
    )


def save_order_index(state: VendorIndexState) -> None:
    path = _index_store_path()
    data = {
        "generated_at": state.generated_at,
        "folders": [asdict(f) for f in state.folders],
        "errors": state.errors,
    }
    write_json_config(path, data, validator=_validate_index)
