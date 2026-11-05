"""Testes de modules/registros/px_export.py — exportação do contrato OrderContext para o
PX Tool Box (ver, no repositório PXToolBox, docs/integrations/nexor-order-context.md e
order-context-example.json). Usa um banco SQLite TEMPORÁRIO isolado (nunca o banco real
configurado em core/config) para nunca tocar dados reais de produção.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import init_schema
from modules.registros.px_export import (
    build_order_context_document,
    write_order_context_document,
)


class OrderContextExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp_dir.name) / "printlogs-test.db"

        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.db_path)
        self._patcher.start()

        # get_installation_id é importado por nome em px_export ("from core.config import
        # get_installation_id") — patchear core.config.get_installation_id não afetaria essa
        # referência já vinculada; precisa ser no namespace de px_export. Sem isto, o teste
        # tocaria o config.json real do usuário (%APPDATA%\PXCore\config.json).
        self._install_id_patcher = patch(
            "modules.registros.px_export.get_installation_id", return_value="test-install-abc"
        )
        self._install_id_patcher.start()

        con = sqlite3.connect(str(self.db_path))
        init_schema(con)
        con.execute(
            "INSERT INTO rolls (id, roll_name, machine, export_mode, created_at, source_hash) "
            "VALUES (1, 'M1_29-10-2026_0013', 'M1', 'normal', '2026-10-29T18:00:00', 'hash-abc')"
        )
        con.execute(
            "INSERT INTO orders "
            "(id, roll_id, end_time, document, fabric, pedido, tipo, height_mm, vpos_mm, "
            " real_m, source_path, observacao, job_hash) "
            "VALUES (1, 1, '2026-10-29T18:05:00', '16-10 - Dryfit - Joao Silva.pdf', "
            " 'Dryfit', 'Dryfit - Joao Silva', 'Camiseta', 300, 0, 2.5, "
            " 'D:\\Impressao\\M1\\16-10 - Dryfit - Joao Silva.pdf', '', '9f1c2a7e4b3d')"
        )
        # Linha de ESPAÇO real (avanço entre tecidos) — tipo/pedido vazios, exatamente como
        # get_roll_summary trata esses casos (ver core/printlogs_db.py).
        con.execute(
            "INSERT INTO orders (id, roll_id, pedido, tipo, job_hash) "
            "VALUES (2, 1, '', '', 'hash-espaco')"
        )
        con.commit()
        con.close()

    def tearDown(self):
        self._install_id_patcher.stop()
        self._patcher.stop()
        self._tmp_dir.cleanup()

    def test_build_order_context_document_matches_px_contract(self):
        document = build_order_context_document(1)

        self.assertIsNotNone(document)
        self.assertEqual(document["formatId"], "NexorOrderContext")
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(document["source"]["rollId"], 1)
        self.assertEqual(document["source"]["rollName"], "M1_29-10-2026_0013")
        self.assertEqual(document["source"]["machine"], "M1")
        self.assertEqual(document["source"]["installationId"], "test-install-abc")
        # databaseId é gerado e persistido na primeira leitura desta base de teste (ver
        # core/printlogs_db.get_database_id) — só confere que existe e é estável, nunca um
        # valor fixo (seria frágil, já que é um uuid gerado em tempo de teste).
        self.assertTrue(document["source"]["databaseId"])
        second_document = build_order_context_document(1)
        self.assertEqual(document["source"]["databaseId"], second_document["source"]["databaseId"])
        self.assertEqual(document["job"]["jobHash"], "9f1c2a7e4b3d")
        self.assertEqual(document["job"]["pedidoLabel"], "Dryfit - Joao Silva")
        self.assertEqual(document["job"]["fabric"], "Dryfit")
        self.assertEqual(document["job"]["tipo"], "Camiseta")
        # pedidoManual nunca é inventado: não é persistido na tabela orders (só existe em
        # memória durante a classificação, ver modules/operacao/models.py) — precisa estar
        # ausente do documento, nunca presente como False.
        self.assertNotIn("pedidoManual", document["job"])
        self.assertIn("exportedAtUtc", document)

    def test_build_order_context_document_returns_none_for_missing_order(self):
        self.assertIsNone(build_order_context_document(999))

    def test_build_order_context_document_for_space_row_has_empty_pedido_label(self):
        # O construtor nunca inventa um pedido para uma linha de espaço — é
        # responsabilidade da UI (on_export_order_context) recusar oferecer a exportação
        # quando o rótulo está vazio, não deste construtor mentir sobre o dado.
        document = build_order_context_document(2)
        self.assertEqual(document["job"]["pedidoLabel"], "")
        self.assertNotIn("fabric", document["job"])
        self.assertNotIn("tipo", document["job"])

    def test_write_order_context_document_produces_file_matching_the_document(self):
        document = build_order_context_document(1)
        out_path = Path(self._tmp_dir.name) / "export.json"

        write_order_context_document(document, str(out_path))

        with open(out_path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
        self.assertEqual(reloaded, document)

    def test_accented_and_special_characters_in_pedido_label_are_preserved(self):
        con = sqlite3.connect(str(self.db_path))
        con.execute(
            "INSERT INTO orders (id, roll_id, pedido, job_hash) VALUES (3, 1, 'João Çãmisetà', 'hash-3')"
        )
        con.commit()
        con.close()

        document = build_order_context_document(3)
        self.assertEqual(document["job"]["pedidoLabel"], "João Çãmisetà")

    def test_installation_id_failure_is_omitted_not_fatal(self):
        # Melhor esforço: se ler/gravar o id de instalação falhar (ex.: pasta de config sem
        # permissão), a exportação continua funcionando, só sem esse campo opcional — nunca
        # inventa um valor, nunca derruba a exportação por isso.
        self._install_id_patcher.stop()
        with patch("modules.registros.px_export.get_installation_id", side_effect=OSError("sem permissão")):
            document = build_order_context_document(1)
        self._install_id_patcher.start()

        self.assertIsNotNone(document)
        self.assertNotIn("installationId", document["source"])

    def test_write_order_context_document_accepts_path_with_spaces_and_accents(self):
        document = build_order_context_document(1)
        out_path = Path(self._tmp_dir.name) / "pasta com espaço e açentuação" / "joão.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        write_order_context_document(document, str(out_path))

        with open(out_path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
        self.assertEqual(reloaded, document)

    def test_write_order_context_document_raises_instead_of_silently_succeeding_on_failure(self):
        # "Gravação sem permissão" (ou qualquer outra falha de I/O): nunca é engolida aqui —
        # quem chama (on_export_order_context, em modules/registros/ui.py) decide a mensagem;
        # sem isso, uma falha real poderia virar um "sucesso" silencioso.
        document = build_order_context_document(1)
        caminho_pasta_inexistente = Path(self._tmp_dir.name) / "pasta-que-nao-existe" / "export.json"

        with self.assertRaises(OSError):
            write_order_context_document(document, str(caminho_pasta_inexistente))


if __name__ == "__main__":
    unittest.main()
