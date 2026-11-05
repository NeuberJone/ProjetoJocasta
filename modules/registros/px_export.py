"""Exportação do CONTEXTO DE PRODUÇÃO para o PX Tool Box DEV (ver, no repositório PXToolBox,
docs/integrations/nexor-order-context.md e order-context-example.json). O nome técnico do
contrato (formatId "NexorOrderContext") e os nomes de campo (rollId, jobHash, pedidoLabel...)
permanecem por compatibilidade com arquivos/testes já existentes — mas isto NÃO é um pedido
comercial: o Nexor não tem essa entidade hoje (sem número/cliente/status formais). O texto
exibido ao usuário (nesta tela e na do PX) usa "contexto de produção"/"trabalho de
impressão"/"rolo", nunca "pedido" como se fosse um número comercial, nunca "Job".

SOMENTE LEITURA: nada aqui altera o rolo/trabalho de impressão, nem qualquer outro dado do
Nexor. Nunca abre o PX ou o CorelDRAW automaticamente — o fluxo é sempre "exportar aqui ->
importar manualmente no PX", nunca uma chamada direta entre os dois processos.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.config import get_installation_id
from modules.registros.repository import load_order_context

FORMAT_ID = "NexorOrderContext"
SCHEMA_VERSION = 1


def build_order_context_document(order_id: int) -> dict[str, Any] | None:
    """Monta o documento do contrato a partir de um trabalho de impressão real. Retorna None
    se o id não existir (nunca inventa um documento para um registro inexistente).

    Campos opcionais (fabric/tipo/sourceFileReference) só entram no documento quando
    realmente conhecidos. ``pedidoManual`` é deliberadamente OMITIDO: é um estado que só
    existe em memória durante a classificação (modules/operacao/models.py), nunca persistido
    na tabela ``orders`` — nunca inventado como False aqui.

    ``source.installationId`` (ver core/config.get_installation_id) e ``source.databaseId``
    (ver core/printlogs_db.get_database_id) são dois identificadores DIFERENTES, cada um com
    sua própria garantia — nenhum dos dois é uma identificação global:

    - ``installationId``: por INSTALAÇÃO/máquina (config local, fora do arquivo .db). Muda se
      a configuração for reinstalada; permanece igual se a mesma instalação apontar para bases
      .db diferentes (não ajuda a distinguir bases nesse caso); pode ser DUPLICADO se alguém
      copiar o arquivo de configuração para outra máquina sem copiar a base.
    - ``databaseId``: por ARQUIVO printlogs.db (gravado dentro do próprio arquivo). Viaja com
      o arquivo numa cópia/restauração/pasta de rede compartilhada entre instalações
      diferentes — por isso é o campo que de fato identifica "mesma base de dados", mesmo
      quando installationId varia entre as máquinas que a acessam.

    Nenhum dos dois substitui ``(rollId, jobHash)`` como identidade do trabalho — são só
    contexto adicional para o PX notar quando dois contextos vêm da mesma base ou não.
    """
    row = load_order_context(order_id)
    if row is None:
        return None

    job: dict[str, Any] = {
        "jobHash": row["job_hash"],
        "pedidoLabel": row.get("pedido") or "",
    }
    if row.get("fabric"):
        job["fabric"] = row["fabric"]
    if row.get("tipo"):
        job["tipo"] = row["tipo"]
    if row.get("source_path"):
        job["sourceFileReference"] = row["source_path"]

    try:
        installation_id = get_installation_id()
    except Exception:
        # Melhor esforço: a exportação não pode falhar só porque o id de instalação não pôde
        # ser lido/gravado (ex.: pasta de config sem permissão) — o documento sai sem esse
        # campo opcional, igual a uma instalação que nunca o teve.
        installation_id = ""

    source: dict[str, Any] = {
        "rollId": row["roll_id"],
        "rollName": row.get("roll_name") or "",
        "machine": row.get("machine") or "",
    }
    if installation_id:
        source["installationId"] = installation_id
    if row.get("database_id"):
        source["databaseId"] = row["database_id"]

    return {
        "formatId": FORMAT_ID,
        "schemaVersion": SCHEMA_VERSION,
        "exportedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "job": job,
    }


def write_order_context_document(document: dict[str, Any], destination_path: str) -> None:
    """Escreve um documento já montado (ver build_order_context_document) no caminho
    escolhido pelo usuário. A confirmação de sobrescrita é responsabilidade do diálogo de
    "Salvar como" que escolheu ``destination_path`` (comportamento nativo do sistema) — esta
    função nunca pergunta de novo nem decide isso por conta própria."""
    with open(destination_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)


def export_order_context_to_file(order_id: int, destination_path: str) -> bool:
    """Atalho: monta o documento a partir do pedido e grava direto. Retorna False (sem
    lançar) se o pedido não existir mais — quem chama decide a mensagem exibida. Nunca altera
    o status do pedido."""
    document = build_order_context_document(order_id)
    if document is None:
        return False

    write_order_context_document(document, destination_path)
    return True
