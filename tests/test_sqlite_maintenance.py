"""Maintenance never opens application configuration or a production database."""
import importlib
import importlib.util
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


class SQLiteMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("core.sqlite_maintenance"), "SQLite maintenance API is required")
        self.api = importlib.import_module("core.sqlite_maintenance")
        self.temp = tempfile.TemporaryDirectory(prefix="sqlite-maintenance-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source # á.db"
        self.destination = self.root / "backup.db"

    def seed(self, *, orphan=False):
        con = sqlite3.connect(self.source)
        try:
            con.executescript("CREATE TABLE parent (id INTEGER PRIMARY KEY); CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id)); INSERT INTO parent VALUES (1); INSERT INTO child VALUES (1, 1);")
            if orphan:
                con.execute("INSERT INTO child VALUES (2, 99)")
            con.commit()
        finally:
            con.close()

    def test_diagnosis_of_existing_legacy_database_does_not_initialize_schema(self):
        self.seed()
        before = self.source.read_bytes()
        report = self.api.diagnose_database(self.source)
        self.assertTrue(report.healthy)
        self.assertEqual(report.integrity_messages, ("ok",))
        self.assertEqual(report.foreign_key_violations, ())
        self.assertEqual(self.source.read_bytes(), before)
        con = sqlite3.connect(self.source)
        try:
            self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(), [("child",), ("parent",)])
        finally:
            con.close()

    def test_foreign_key_violations_make_report_unhealthy(self):
        self.seed(orphan=True)
        report = self.api.diagnose_database(self.source)
        self.assertFalse(report.healthy)
        self.assertEqual(report.integrity_messages, ("ok",))
        violation = report.foreign_key_violations[0]
        self.assertEqual((violation.table, violation.rowid, violation.parent, violation.foreign_key_index), ("child", 2, "parent", 0))

    def test_corrupt_source_has_unhealthy_diagnostic_and_is_preserved(self):
        self.source.write_bytes(b"not a SQLite database, preserve it")
        before = self.source.read_bytes()
        report = self.api.diagnose_database(self.source)
        self.assertFalse(report.healthy)
        self.assertEqual(self.source.read_bytes(), before)

    def test_missing_source_fails_explicitly_without_creating_it(self):
        with self.assertRaises(self.api.DatabaseUnavailableError):
            self.api.diagnose_database(self.source)
        self.assertFalse(self.source.exists())

    def test_locked_diagnosis_fails_explicitly_and_closes_handle(self):
        self.seed()
        writer = sqlite3.connect(self.source)
        try:
            writer.execute("BEGIN EXCLUSIVE")
            with self.assertRaises(self.api.DatabaseUnavailableError) as error:
                self.api.diagnose_database(self.source, timeout_ms=25)
            self.assertIsInstance(error.exception.__cause__, sqlite3.OperationalError)
        finally:
            writer.rollback()
            writer.close()
        self.source.rename(self.root / "closed.db")

    def test_backup_uses_committed_snapshot_and_preserves_source(self):
        self.seed()
        before = self.source.read_bytes()
        writer = sqlite3.connect(self.source)
        try:
            writer.execute("INSERT INTO parent VALUES (2)")
            result = self.api.backup_database(self.source, self.destination)
        finally:
            writer.rollback()
            writer.close()
        self.assertEqual(result, self.destination)
        con = sqlite3.connect(self.destination)
        try:
            self.assertEqual(con.execute("SELECT id FROM parent").fetchall(), [(1,)])
        finally:
            con.close()
        self.assertTrue(self.api.diagnose_database(self.destination).healthy)
        self.assertEqual(self.source.read_bytes(), before)

    def test_existing_backup_is_never_overwritten(self):
        self.seed()
        self.destination.write_bytes(b"old backup")
        with self.assertRaises(FileExistsError):
            self.api.backup_database(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b"old backup")

    def test_backup_refuses_source_as_destination(self):
        self.seed()
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            self.api.backup_database(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)

    def test_invalid_source_does_not_produce_successful_backup(self):
        self.seed(orphan=True)
        before = self.source.read_bytes()
        with self.assertRaises(self.api.DatabaseIntegrityError) as error:
            self.api.backup_database(self.source, self.destination)
        self.assertFalse(error.exception.report.healthy)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), before)

    def test_backup_validates_destination_after_sqlite_api_copy(self):
        self.seed()
        before = self.source.read_bytes()
        real_connect = sqlite3.connect

        class InvalidDestinationConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                super().backup(target, **kwargs)
                target.execute("INSERT INTO child VALUES (2, 99)")
                target.commit()

        def damaged_copy_connect(*args, **kwargs):
            if kwargs.get("uri"):
                kwargs["factory"] = InvalidDestinationConnection
            return real_connect(*args, **kwargs)

        with patch("core.sqlite_maintenance.sqlite3.connect", side_effect=damaged_copy_connect):
            with self.assertRaises(self.api.DatabaseIntegrityError) as error:
                self.api.backup_database(self.source, self.destination)
        self.assertEqual(error.exception.report.foreign_key_violations[0].rowid, 2)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), before)

    def test_corrupt_source_cannot_create_a_backup(self):
        self.source.write_bytes(b"corrupt source")
        with self.assertRaises(self.api.DatabaseIntegrityError):
            self.api.backup_database(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.source.read_bytes(), b"corrupt source")

    def test_unwritable_destination_parent_is_explicit_and_source_is_closed(self):
        self.seed()
        unavailable_destination = self.root / "absent" / "backup.db"
        with self.assertRaises(self.api.DatabaseUnavailableError) as error:
            self.api.backup_database(self.source, unavailable_destination)
        self.assertIsInstance(error.exception.__cause__, OSError)
        self.assertFalse(unavailable_destination.parent.exists())
        self.source.rename(self.root / "closed-source.db")

    def test_failed_sqlite_backup_closes_handles_and_removes_only_its_output(self):
        self.seed()
        old_backup = self.root / "old-backup.db"
        old_backup.write_bytes(b"keep")
        real_connect = sqlite3.connect
        captured = []

        class FailingBackupConnection(sqlite3.Connection):
            def backup(self, target, **kwargs):
                target.execute("CREATE TABLE incomplete (id)")
                raise sqlite3.OperationalError("private SQL details")

        def failing_connect(*args, **kwargs):
            if kwargs.get("uri"):
                kwargs["factory"] = FailingBackupConnection
            connection = real_connect(*args, **kwargs)
            captured.append(connection)
            return connection

        with patch("core.sqlite_maintenance.sqlite3.connect", side_effect=failing_connect):
            with self.assertRaises(self.api.DatabaseUnavailableError) as error:
                self.api.backup_database(self.source, self.destination)
        self.assertNotIn("private SQL", str(error.exception))
        self.assertFalse(self.destination.exists())
        self.assertEqual(old_backup.read_bytes(), b"keep")
        for connection in captured:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_busy_backup_retries_are_bounded(self):
        self.seed()
        real_connect = sqlite3.connect

        class BusyBackupConnection(sqlite3.Connection):
            def backup(self, target, *, progress, **kwargs):
                while True:
                    progress(sqlite3.SQLITE_BUSY, 1, 1)
                    time.sleep(0.005)

        def busy_connect(*args, **kwargs):
            if kwargs.get("uri"):
                kwargs["factory"] = BusyBackupConnection
            return real_connect(*args, **kwargs)

        started = time.monotonic()
        with patch("core.sqlite_maintenance.sqlite3.connect", side_effect=busy_connect):
            with self.assertRaises(self.api.DatabaseUnavailableError):
                self.api.backup_database(self.source, self.destination, timeout_ms=25)
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(self.destination.exists())

    def test_invalid_timeout_is_rejected_before_accessing_paths(self):
        for timeout in (-1, 0, True, 1.5):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    self.api.diagnose_database(self.source, timeout_ms=timeout)
                with self.assertRaises(ValueError):
                    self.api.backup_database(self.source, self.destination, timeout_ms=timeout)
        self.assertEqual(list(self.root.iterdir()), [])


class BackupRetentionTests(unittest.TestCase):
    """list_backups/prune_backups — item de roadmap (Fase 1) "formalizar
    diagnóstico, retenção de backups e ensaio de restauração": antes desta
    etapa, backup_database existia e era testado, mas nada decidia quantos
    backups manter nem reconhecia quais arquivos de uma pasta de destino
    eram backups de verdade (vs. qualquer outro arquivo que a pasta possa
    conter)."""

    def setUp(self):
        self.api = importlib.import_module("core.sqlite_maintenance")
        self.temp = tempfile.TemporaryDirectory(prefix="sqlite-retention-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _touch_backup(self, prefix: str, when: datetime) -> Path:
        path = self.root / self.api.backup_filename(prefix, when)
        path.write_bytes(b"fake db bytes")
        return path

    def test_list_backups_on_a_missing_directory_is_empty_not_an_error(self):
        self.assertEqual(self.api.list_backups(self.root / "does-not-exist", "printlogs"), [])

    def test_list_backups_ignores_unrelated_files_and_other_prefixes(self):
        wanted = self._touch_backup("printlogs", datetime(2026, 1, 1, 10, 0, 0))
        self._touch_backup("outro-prefixo", datetime(2026, 1, 1, 10, 0, 0))
        (self.root / "printlogs.db").write_bytes(b"not a backup, the live db itself")
        (self.root / "readme.txt").write_text("not a backup")
        self.assertEqual(self.api.list_backups(self.root, "printlogs"), [wanted])

    def test_list_backups_is_oldest_first(self):
        newer = self._touch_backup("printlogs", datetime(2026, 11, 19, 10, 0, 0))
        older = self._touch_backup("printlogs", datetime(2026, 11, 18, 9, 0, 0))
        self.assertEqual(self.api.list_backups(self.root, "printlogs"), [older, newer])

    def test_prune_keeps_the_newest_and_removes_the_rest(self):
        oldest = self._touch_backup("printlogs", datetime(2026, 11, 17, 10, 0, 0))
        middle = self._touch_backup("printlogs", datetime(2026, 11, 18, 10, 0, 0))
        newest = self._touch_backup("printlogs", datetime(2026, 11, 19, 10, 0, 0))

        removed = self.api.prune_backups(self.root, "printlogs", keep=1)

        self.assertEqual(removed, [oldest, middle])
        self.assertFalse(oldest.exists())
        self.assertFalse(middle.exists())
        self.assertTrue(newest.exists())

    def test_prune_never_touches_files_outside_its_own_prefix(self):
        self._touch_backup("printlogs", datetime(2026, 11, 17, 10, 0, 0))
        other_prefix = self._touch_backup("outro-modulo", datetime(2026, 11, 17, 10, 0, 0))

        self.api.prune_backups(self.root, "printlogs", keep=0)

        self.assertTrue(other_prefix.exists())

    def test_prune_with_enough_room_removes_nothing(self):
        a = self._touch_backup("printlogs", datetime(2026, 11, 17, 10, 0, 0))
        b = self._touch_backup("printlogs", datetime(2026, 11, 18, 10, 0, 0))
        self.assertEqual(self.api.prune_backups(self.root, "printlogs", keep=5), [])
        self.assertTrue(a.exists())
        self.assertTrue(b.exists())

    def test_negative_keep_is_rejected(self):
        with self.assertRaises(ValueError):
            self.api.prune_backups(self.root, "printlogs", keep=-1)

    def test_backup_filename_is_lexicographically_sortable_by_time(self):
        earlier = self.api.backup_filename("printlogs", datetime(2026, 1, 2, 3, 4, 5))
        later = self.api.backup_filename("printlogs", datetime(2026, 1, 2, 3, 4, 6))
        self.assertLess(earlier, later)


if __name__ == "__main__":
    unittest.main()
