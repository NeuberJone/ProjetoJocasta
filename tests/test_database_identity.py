"""Testes dos cenários reais de identidade pedidos na tarefa de validação do contexto de
produção (ver core/printlogs_db.get_database_id e core/config.get_installation_id) — nunca
toca o banco/config real do usuário, sempre arquivos temporários isolados.

Cada teste aqui corresponde a um cenário da seção "1. Verificar cenários" da tarefa:
uma instalação com duas bases; duas instalações na mesma base; cópia/restauração da base em
outra máquina; cópia da configuração local; exportações antigas sem os campos novos.
"""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import get_installation_id
from core.printlogs_db import get_database_id, init_schema


def _fresh_db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    init_schema(con)
    return con


class DatabaseIdentityScenarioTests(unittest.TestCase):
    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp_dir.name)

    def tearDown(self):
        self._tmp_dir.cleanup()

    def test_uma_instalacao_duas_bases_mesmo_installation_id_database_id_diferente(self):
        """Uma única instalação (mesmo installationId) apontando para duas bases .db
        diferentes — installationId NÃO distingue; databaseId sim."""
        with patch("core.config._config_path", return_value=self.tmp_path / "config.json"):
            installation_id = get_installation_id()
            installation_id_again = get_installation_id()
        self.assertEqual(installation_id, installation_id_again)

        con_a = _fresh_db(self.tmp_path / "base-a.db")
        con_b = _fresh_db(self.tmp_path / "base-b.db")
        try:
            db_id_a = get_database_id(con_a)
            db_id_b = get_database_id(con_b)
        finally:
            con_a.close()
            con_b.close()

        self.assertNotEqual(db_id_a, db_id_b)

    def test_duas_instalacoes_mesma_base_database_id_igual_installation_id_diferente(self):
        """Duas 'instalações' (duas configs locais diferentes) conectando na MESMA base
        (cenário real: base_dir em pasta de rede compartilhada — ver connect(), comentário do
        journal_mode) — databaseId precisa ser IGUAL; installationId pode ser diferente."""
        shared_db_path = self.tmp_path / "base-compartilhada.db"
        con_setup = _fresh_db(shared_db_path)
        con_setup.close()

        with patch("core.config._config_path", return_value=self.tmp_path / "maquina-1.json"):
            installation_id_1 = get_installation_id()
        with patch("core.config._config_path", return_value=self.tmp_path / "maquina-2.json"):
            installation_id_2 = get_installation_id()
        self.assertNotEqual(installation_id_1, installation_id_2)

        con_1 = sqlite3.connect(str(shared_db_path))
        con_1.row_factory = sqlite3.Row
        con_2 = sqlite3.connect(str(shared_db_path))
        con_2.row_factory = sqlite3.Row
        try:
            db_id_from_machine_1 = get_database_id(con_1)
            db_id_from_machine_2 = get_database_id(con_2)
        finally:
            con_1.close()
            con_2.close()

        self.assertEqual(db_id_from_machine_1, db_id_from_machine_2)

    def test_copia_ou_restauracao_da_base_preserva_database_id(self):
        """Copiar o arquivo .db (backup/restauração em outra máquina) preserva o databaseId,
        porque ele está GRAVADO DENTRO do arquivo, não derivado do caminho/máquina."""
        original_path = self.tmp_path / "original.db"
        con = _fresh_db(original_path)
        try:
            original_id = get_database_id(con)
        finally:
            con.close()

        copied_path = self.tmp_path / "subpasta" / "restaurado-em-outra-maquina.db"
        copied_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original_path, copied_path)

        con_copy = sqlite3.connect(str(copied_path))
        con_copy.row_factory = sqlite3.Row
        try:
            copied_id = get_database_id(con_copy)
        finally:
            con_copy.close()

        self.assertEqual(original_id, copied_id)

    def test_copia_da_configuracao_local_duplica_installation_id_mas_nao_database_id(self):
        """Copiar só o config.json (sem a base) para outra máquina faz as duas 'instalações'
        reportarem o MESMO installationId mesmo tendo bases diferentes — por isso installationId
        isolado NUNCA prova que duas exportações vieram da mesma base; só databaseId prova."""
        original_config = self.tmp_path / "original-config.json"
        with patch("core.config._config_path", return_value=original_config):
            installation_id_original = get_installation_id()

        copied_config = self.tmp_path / "copiado-em-outra-maquina.json"
        shutil.copyfile(original_config, copied_config)
        with patch("core.config._config_path", return_value=copied_config):
            installation_id_copiado = get_installation_id()

        # Mesmo installationId (config copiada) ...
        self.assertEqual(installation_id_original, installation_id_copiado)

        # ... mas cada 'máquina' tem sua própria base, com databaseId DIFERENTE —
        # demonstrando que installationId sozinho não é prova de mesma base.
        con_original_db = _fresh_db(self.tmp_path / "base-maquina-original.db")
        con_outra_db = _fresh_db(self.tmp_path / "base-maquina-copiada.db")
        try:
            db_id_original = get_database_id(con_original_db)
            db_id_outra = get_database_id(con_outra_db)
        finally:
            con_original_db.close()
            con_outra_db.close()

        self.assertNotEqual(db_id_original, db_id_outra)

    def test_primeira_chamada_em_base_nova_gera_e_persiste(self):
        con = _fresh_db(self.tmp_path / "nova.db")
        try:
            first = get_database_id(con)
            second = get_database_id(con)
        finally:
            con.close()
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_corrida_na_primeira_criacao_converge_no_mesmo_id(self):
        """Simula duas conexões 'batendo' na criação do id ao mesmo tempo (ex.: duas
        instalações abrindo uma base de rede recém-criada simultaneamente) — o rowid fixo (1)
        com INSERT OR IGNORE garante que só uma INSERT vence e as duas leituras convergem."""
        db_path = self.tmp_path / "corrida.db"
        con_1 = _fresh_db(db_path)
        con_2 = sqlite3.connect(str(db_path))
        con_2.row_factory = sqlite3.Row
        try:
            # Ambas enxergam a tabela vazia antes de qualquer uma persistir.
            self.assertIsNone(con_1.execute("SELECT id FROM db_identity WHERE rowid = 1").fetchone())
            self.assertIsNone(con_2.execute("SELECT id FROM db_identity WHERE rowid = 1").fetchone())

            id_1 = get_database_id(con_1)
            id_2 = get_database_id(con_2)
        finally:
            con_1.close()
            con_2.close()

        self.assertEqual(id_1, id_2)
        con_check = sqlite3.connect(str(db_path))
        con_check.row_factory = sqlite3.Row
        try:
            rows = con_check.execute("SELECT id FROM db_identity").fetchall()
        finally:
            con_check.close()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
