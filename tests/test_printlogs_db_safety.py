"""SQLite safety checks against repository-local disposable databases only."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import printlogs_db as db


class PrintlogsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sqlite-safety-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "printlogs.db"
        self.path_patch = patch("core.printlogs_db.get_db_path", return_value=self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def order(self, document="original"):
        return db.OrderRow("2026-11-05T10:00:00", document, "fabric", "pedido", 1000, 0, 1, "source")

    def save(self, orders=None):
        return db.save_export_transactional("M1", "roll", "normal", "test", orders or [self.order()])[0]

    def inspect(self, sql):
        con = sqlite3.connect(self.path)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_failed_pragma_closes_real_connection_and_preserves_cause(self):
        class DeniedPragmaConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if "journal_mode" in sql:
                    raise sqlite3.OperationalError("private path must not escape")
                return super().execute(sql, *args, **kwargs)

        connection = sqlite3.connect(self.path, factory=DeniedPragmaConnection)
        self.addCleanup(connection.close)
        with patch("core.printlogs_db.sqlite3.connect", return_value=connection):
            with self.assertRaises(sqlite3.OperationalError) as error:
                db.connect()
        self.assertEqual(type(error.exception).__name__, "DatabaseUnavailableError")
        self.assertIsInstance(error.exception.__cause__, sqlite3.OperationalError)
        self.assertNotIn("private path", str(error.exception))
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_busy_timeout_is_explicit_even_if_driver_default_is_changed(self):
        class NoDefaultTimeoutConnection(sqlite3.Connection):
            pass

        connection = sqlite3.connect(self.path, timeout=0, factory=NoDefaultTimeoutConnection)
        with patch("core.printlogs_db.sqlite3.connect", return_value=connection):
            con = db.connect()
        try:
            self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(con.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        finally:
            con.close()

    def test_unavailable_messages_distinguish_lock_permission_and_network_errors(self):
        for code, name, reason in (
            (sqlite3.SQLITE_BUSY, "SQLITE_BUSY", "ocupado"),
            (sqlite3.SQLITE_LOCKED, "SQLITE_LOCKED", "ocupado"),
            (sqlite3.SQLITE_READONLY, "SQLITE_READONLY", "permiss"),
            (sqlite3.SQLITE_CANTOPEN, "SQLITE_CANTOPEN", "arquivo existe"),
            (sqlite3.SQLITE_IOERR, "SQLITE_IOERR", "rede"),
        ):
            with self.subTest(code=code):
                cause = sqlite3.OperationalError("secret production SQL")
                cause.sqlite_errorcode = code
                cause.sqlite_errorname = name
                with patch("core.printlogs_db.sqlite3.connect", side_effect=cause):
                    with self.assertRaises(sqlite3.OperationalError) as result:
                        db.connect()
                self.assertIn(reason, str(result.exception).lower())
                self.assertIn(name, str(result.exception))
                self.assertNotIn("secret production SQL", str(result.exception))
                self.assertIs(result.exception.__cause__, cause)

    def test_configuration_path_failure_retains_its_original_type_and_cause(self):
        original = PermissionError("configuration unavailable")
        with patch("core.printlogs_db.get_db_path", side_effect=original):
            with self.assertRaises(PermissionError) as result:
                db.connect()
        self.assertIs(result.exception, original)

    def test_legacy_original_table_is_preserved_and_migration_is_idempotent(self):
        roll_id = self.save()
        con = db.connect()
        try:
            con.execute("CREATE TABLE roll_original_orders (roll_id INTEGER PRIMARY KEY, orders_json TEXT, saved_at TEXT)")
            con.execute("INSERT INTO roll_original_orders VALUES (?, ?, ?)", (roll_id, '[{"document":"legacy"}]', "old"))
            con.commit()
            db.ensure_schema(con)
            db.ensure_schema(con)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("roll_original_orders", tables)
            legacy = con.execute("SELECT orders_json, saved_at FROM roll_original_orders").fetchall()
            versions = con.execute("SELECT version_no, orders_json FROM roll_order_versions").fetchall()
        finally:
            con.close()
        self.assertEqual([tuple(row) for row in legacy], [('[{"document":"legacy"}]', "old")])
        self.assertEqual([tuple(row) for row in versions], [(0, '[{"document":"legacy"}]')])

    def test_failed_export_event_rolls_back_roll_and_orders(self):
        with patch("core.printlogs_db.log_event", side_effect=sqlite3.OperationalError("event rejected")):
            with self.assertRaises(sqlite3.OperationalError):
                self.save()
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM rolls"), [(0,)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM orders"), [(0,)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM events"), [(0,)])

    def test_failed_update_event_preserves_orders_and_version_history(self):
        roll_id = self.save()
        with patch("core.printlogs_db.log_event", side_effect=sqlite3.OperationalError("event rejected")):
            with self.assertRaises(sqlite3.OperationalError):
                db.update_roll_orders(roll_id, "M1", "changed", "normal", "test", [self.order("replacement")])
        self.assertEqual(self.inspect("SELECT document FROM orders"), [("original",)])
        self.assertEqual(self.inspect("SELECT roll_name FROM rolls"), [("roll",)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM roll_order_versions"), [(0,)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM events"), [(1,)])

    def test_failed_reexport_event_preserves_existing_roll(self):
        original_id = self.save()
        with patch("core.printlogs_db.log_event", side_effect=sqlite3.OperationalError("event rejected")):
            with self.assertRaises(sqlite3.OperationalError):
                self.save()
        self.assertEqual(self.inspect("SELECT id FROM rolls"), [(original_id,)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM orders"), [(1,)])
        self.assertEqual(self.inspect("SELECT COUNT(*) FROM events"), [(1,)])


if __name__ == "__main__":
    unittest.main()
