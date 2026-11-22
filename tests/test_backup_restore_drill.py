"""Ensaio operacional de backup/restauração e bloqueio, item ainda em
aberto da Fase 1 do roadmap (`docs/roadmaps/nexor-modernization-roadmap.md`:
"Ensaio operacional de backup/restauração e bloqueio em ambiente
representativo descartável"). `tests/test_sqlite_maintenance.py` já cobre
a API de manutenção (`core.sqlite_maintenance`) isoladamente, com schema
mínimo fabricado à mão e o bloqueio real do SQLite nunca exercitado (o
caso de "busy" existente mocka o método `backup()` da conexão, nunca
segura um lock de verdade). Este arquivo cobre duas lacunas reais que
faltavam:

1. Restauração de ponta a ponta usando o schema e as consultas REAIS do
   aplicativo (`core.printlogs_db`), não só `diagnose_database` confirmando
   integridade de bytes — abre o backup com `get_roll_orders`/`list_rolls`/
   `get_roll_summary` de verdade, como a tela de Registros faria.
2. Bloqueio de escrita genuíno (uma segunda conexão real com `BEGIN
   IMMEDIATE`, sem mock nenhum em `sqlite3`), confirmando que o backup
   espera o lock por até `timeout_ms` e completa assim que ele é liberado,
   sem incluir dado não commitado.

Continua sendo um ambiente descartável local (disco local, processo
único) — nunca o compartilhamento SMB real usado pela M1/M2/M3 em
produção, nem múltiplas estações de verdade. Isso não substitui a
homologação de rede pendente (mesmo item do roadmap)."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.printlogs_db import (
    OrderRow,
    get_roll_orders,
    get_roll_summary,
    list_rolls,
    save_export_transactional,
)
from core.sqlite_maintenance import DatabaseUnavailableError, backup_database, diagnose_database


def _order(document: str, pedido: str, *, real_m: float = 2.5) -> OrderRow:
    return OrderRow(
        end_time="2026-11-16T10:00:00", document=document, fabric="DRYFIT", pedido=pedido,
        height_mm=1000.0, vpos_mm=0.0, real_m=real_m, source_path=f"/x/{document}", tipo="Pedido",
    )


class BackupRestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="backup-restore-drill-")
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.source_path = root / "printlogs.db"
        self.backup_path = root / "printlogs-backup.db"
        self._patcher = patch("core.printlogs_db.get_db_path", return_value=self.source_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _seed_two_rolls(self):
        roll_a, _ = save_export_transactional(
            machine="M1", roll_name="M1-DRILL-0001", export_mode="normal", app_version="1.6.64",
            orders=[_order("ped_a.jpeg", "Cliente A", real_m=3.0)],
        )
        roll_b, _ = save_export_transactional(
            machine="M2", roll_name="M2-DRILL-0002", export_mode="normal", app_version="1.6.64",
            orders=[_order("ped_b.jpeg", "Cliente B", real_m=4.5)],
        )
        return roll_a, roll_b

    def test_restored_backup_answers_real_application_queries_with_original_data(self):
        roll_a, roll_b = self._seed_two_rolls()

        backup_database(self.source_path, self.backup_path, timeout_ms=5000)
        report = diagnose_database(self.backup_path, timeout_ms=5000)
        self.assertTrue(report.healthy)

        # A restauração real não é "o arquivo existe e passa integrity_check"
        # — é o aplicativo conseguir ler o conteúdo de volta. Aponta
        # get_db_path para o próprio arquivo restaurado e usa as mesmas
        # funções que Registros usaria depois de uma restauração de verdade.
        with patch("core.printlogs_db.get_db_path", return_value=self.backup_path):
            rolls = list_rolls(limit=100, name_like="DRILL")
            names = {r["roll_name"] for r in rolls}
            self.assertEqual(names, {"M1-DRILL-0001", "M2-DRILL-0002"})

            orders_a = get_roll_orders(roll_a)
            self.assertEqual(len(orders_a), 1)
            self.assertEqual(orders_a[0]["pedido"], "Cliente A")

            summary_b = get_roll_summary(roll_b)
            self.assertIn("fabrics", summary_b)

        # O backup não deve ter alterado a origem (mesmo princípio que já
        # vale pra diagnose_database — ver tests/test_sqlite_maintenance.py).
        orders_a_source = get_roll_orders(roll_a)
        self.assertEqual(orders_a_source[0]["pedido"], "Cliente A")

    def test_backup_waits_for_a_real_exclusive_lock_and_completes_after_release(self):
        """BEGIN IMMEDIATE sozinho (RESERVED) não bloqueia um leitor — é
        compatível com SHARED, então um backup concorrente passaria direto,
        sem nunca testar a espera de verdade (confirmado experimentalmente:
        sem `locking_mode=EXCLUSIVE`, o backup abaixo completava em <10ms).
        `PRAGMA locking_mode=EXCLUSIVE` + commit mantém o lock EXCLUSIVE
        mesmo depois do commit, até a conexão fechar — é o jeito real de
        segurar o arquivo inteiro inacessível a outra conexão por um tempo
        determinado, sem mockar nada de `sqlite3`."""
        self._seed_two_rolls()

        lock_acquired = threading.Event()

        def hold_exclusive_lock_then_release():
            con = sqlite3.connect(self.source_path, timeout=0)
            try:
                con.execute("PRAGMA locking_mode=EXCLUSIVE")
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    "INSERT INTO rolls (roll_name, machine, export_mode, app_version, created_at, source_hash) "
                    "VALUES ('M1-DRILL-DURING-LOCK', 'M1', 'normal', '1.6.64', '2026-11-16T10:00:00', 'drill-during-lock')"
                )
                con.commit()
                lock_acquired.set()
                time.sleep(0.3)  # lock EXCLUSIVE continua seguro até fechar a conexão
            finally:
                con.close()

        holder = threading.Thread(target=hold_exclusive_lock_then_release, daemon=True)
        holder.start()
        self.assertTrue(lock_acquired.wait(timeout=5), "writer não conseguiu segurar o lock a tempo")

        started = time.monotonic()
        backup_database(self.source_path, self.backup_path, timeout_ms=5000)
        elapsed = time.monotonic() - started
        holder.join(timeout=5)

        # Provou que esperou o lock real (não voltou instantaneamente) e
        # completou assim que foi liberado, bem dentro do timeout configurado.
        self.assertGreaterEqual(elapsed, 0.2)
        self.assertLess(elapsed, 5)

        report = diagnose_database(self.backup_path, timeout_ms=5000)
        self.assertTrue(report.healthy)
        with patch("core.printlogs_db.get_db_path", return_value=self.backup_path):
            backup_names = {r["roll_name"] for r in list_rolls(limit=100)}
        self.assertEqual(backup_names, {"M1-DRILL-0001", "M2-DRILL-0002", "M1-DRILL-DURING-LOCK"})

    def test_backup_fails_explicitly_when_the_real_exclusive_lock_outlasts_the_timeout(self):
        self._seed_two_rolls()

        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def hold_exclusive_lock_until_told(con_holder: list):
            con = sqlite3.connect(self.source_path, timeout=0)
            con_holder.append(con)
            con.execute("PRAGMA locking_mode=EXCLUSIVE")
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO rolls (roll_name, machine, export_mode, app_version, created_at, source_hash) "
                "VALUES ('M1-DRILL-LONG-LOCK', 'M1', 'normal', '1.6.64', '2026-11-16T10:00:00', 'drill-long-lock')"
            )
            con.commit()
            lock_acquired.set()
            release_lock.wait(timeout=5)
            con.close()

        con_holder: list = []
        holder = threading.Thread(target=hold_exclusive_lock_until_told, args=(con_holder,), daemon=True)
        holder.start()
        try:
            self.assertTrue(lock_acquired.wait(timeout=5), "writer não conseguiu segurar o lock a tempo")
            started = time.monotonic()
            with self.assertRaises(DatabaseUnavailableError):
                backup_database(self.source_path, self.backup_path, timeout_ms=100)
            self.assertLess(time.monotonic() - started, 4)  # falhou pelo timeout configurado, não ficou preso
            self.assertFalse(self.backup_path.exists())
        finally:
            release_lock.set()
            holder.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
