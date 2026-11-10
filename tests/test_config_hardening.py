"""Configuration failures are exercised only against files beneath this repository."""
import hashlib
import importlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config, fabric_scraps, fabrics, printers
from core.json_store import ConfigurationError, ConfigurationValidationError


class IsolatedConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"
        self.patcher = patch("core.config._config_path", return_value=self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.real_ensure_dirs = config._ensure_dirs
        dirs = patch("core.config._ensure_dirs")
        dirs.start()
        self.addCleanup(dirs.stop)

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")


class MainConfigurationTests(IsolatedConfigTest):
    def test_first_run_creates_valid_config(self):
        cfg = config.load_config()
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["base_dir"], cfg.base_dir)

    def test_corrupt_empty_or_wrong_shape_file_is_never_reset(self):
        for original in ("", "{truncated", "[]", '{"dev_mode_enabled": "false"}'):
            with self.subTest(original=original):
                self.path.write_text(original, encoding="utf-8")
                with self.assertRaises(ConfigurationValidationError) as caught:
                    config.load_config()
                self.assertEqual(type(caught.exception).__name__, "ConfigurationValidationError")
                self.assertIn(str(self.path), str(caught.exception))
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_old_config_and_unknown_fields_survive_identity_and_save(self):
        original = {"base_dir": str(self.path.parent), "installation_id": "old-id", "future": {"nested": 1}}
        self.write(original)
        cfg = config.load_config()
        cfg.theme_name = "light"
        config.save_config(cfg)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["future"], original["future"])
        self.assertEqual(config.get_installation_id(), "old-id")
        self.assertEqual(saved["base_dir"], original["base_dir"])

    def test_save_cannot_overwrite_existing_corrupt_config(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ConfigurationValidationError):
            config.save_config(config.PXCoreConfig())
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{broken")

    def test_unrelated_save_cannot_remove_or_replace_existing_credentials_and_id(self):
        stored_hash = hashlib.sha1(b"secret").hexdigest()
        self.write({"base_dir": str(self.path.parent), "dev_password_hash": stored_hash, "installation_id": "stable"})
        cfg = config.PXCoreConfig(base_dir=str(self.path.parent), installation_id="other", dev_password_hash="")
        cfg.theme_name = "light"
        config.save_config(cfg)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["dev_password_hash"], stored_hash)
        self.assertEqual(saved["installation_id"], "stable")
        self.assertEqual(cfg.installation_id, "stable")

    def test_unavailable_work_directory_does_not_reset_config_and_is_logged(self):
        self.write({"base_dir": str(self.path.parent), "installation_id": "stable"})
        original = self.path.read_bytes()
        with patch("core.config._ensure_dirs", wraps=self.real_ensure_dirs), \
                patch.object(Path, "mkdir", side_effect=PermissionError("sensitive")), \
                self.assertLogs("nexor", level="ERROR") as logs:
            cfg = config.load_config()
        self.assertEqual(cfg.installation_id, "stable")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn("sensitive", "".join(record.getMessage() for record in logs.records))

    def test_module_corruption_is_visible_and_preserved(self):
        module_path = config.module_config_path("Estacao")
        module_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ConfigurationValidationError):
            config.read_module_cfg("Estacao", {"station_id": ""})
        with self.assertRaises(ConfigurationValidationError):
            config.write_module_cfg("Estacao", {"station_id": "PC1"})
        self.assertEqual(module_path.read_text(encoding="utf-8"), "{broken")


class PasswordTests(IsolatedConfigTest):
    def legacy(self):
        cfg = config.PXCoreConfig(base_dir=str(self.path.parent))
        cfg.dev_password_hash = hashlib.sha1(b"secret").hexdigest()
        config.save_config(cfg)
        return cfg

    def test_new_password_hashes_are_salted_and_verifiable(self):
        first = config.hash_password("secret")
        second = config.hash_password("secret")
        self.assertTrue(first.startswith("pbkdf2_sha256$600000$"))
        self.assertNotEqual(first, second)
        cfg = config.PXCoreConfig(dev_password_hash=first)
        self.assertTrue(config.verify_dev_password(cfg, "secret"))
        self.assertFalse(config.verify_dev_password(cfg, "wrong"))

    def test_legacy_hash_changes_only_after_correct_authentication(self):
        cfg = self.legacy()
        original = self.path.read_bytes()
        old_hash = cfg.dev_password_hash
        self.assertFalse(config.verify_dev_password(cfg, "wrong"))
        self.assertEqual(cfg.dev_password_hash, old_hash)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(config.verify_dev_password(cfg, "secret"))
        self.assertTrue(cfg.dev_password_hash.startswith("pbkdf2_sha256$"))
        self.assertEqual(json.loads(self.path.read_text())["dev_password_hash"], cfg.dev_password_hash)

    def test_stale_save_cannot_revert_successful_password_upgrade(self):
        cfg = self.legacy()
        stale = config.load_config()
        self.assertTrue(config.verify_dev_password(cfg, "secret"))
        upgraded = cfg.dev_password_hash
        stale.theme_name = "light"
        config.save_config(stale)
        self.assertEqual(json.loads(self.path.read_text())["dev_password_hash"], upgraded)

    def test_stale_legacy_authentication_cannot_replace_new_current_password(self):
        stale = self.legacy()
        current = config.load_config()
        config.set_dev_password(current, "changed")
        original = self.path.read_bytes()
        old_hash = stale.dev_password_hash
        self.assertFalse(config.verify_dev_password(stale, "secret"))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(stale.dev_password_hash, old_hash)
        self.assertTrue(config.verify_dev_password(stale, "changed"))
        self.assertEqual(stale.dev_password_hash, current.dev_password_hash)

    def test_legacy_authentication_does_not_save_unrelated_stale_fields(self):
        stale = self.legacy()
        changed = json.loads(self.path.read_text())
        changed.update({"base_dir": str(self.path.parent / "new-work-directory"), "theme_name": "light",
                        "installation_id": "current-id", "future": {"nested": 1}})
        self.write(changed)
        self.assertTrue(config.verify_dev_password(stale, "secret"))
        saved = json.loads(self.path.read_text())
        for field in ("base_dir", "theme_name", "installation_id", "future"):
            self.assertEqual(saved[field], changed[field])
        self.assertEqual(stale.dev_password_hash, saved["dev_password_hash"])

    def test_stale_pbkdf2_authentication_uses_current_saved_password(self):
        current = self.legacy()
        config.set_dev_password(current, "first")
        stale = config.load_config()
        config.set_dev_password(current, "second")
        original = self.path.read_bytes()
        self.assertFalse(config.verify_dev_password(stale, "first"))
        self.assertTrue(config.verify_dev_password(stale, "second"))
        self.assertEqual(self.path.read_bytes(), original)

    def test_standalone_legacy_authentication_with_missing_file_still_migrates(self):
        cfg = config.PXCoreConfig(base_dir=str(self.path.parent), dev_password_hash=hashlib.sha1(b"secret").hexdigest())
        self.assertTrue(config.verify_dev_password(cfg, "secret"))
        self.assertTrue(self.path.is_file())
        self.assertTrue(cfg.dev_password_hash.startswith("pbkdf2_sha256$"))

    def test_password_change_during_derivation_blocks_legacy_migration(self):
        cfg = self.legacy()
        old_hash = cfg.dev_password_hash
        real_hash = config.hash_password
        replacement = real_hash("changed")
        def change_disk_while_deriving(password):
            raw = json.loads(self.path.read_text())
            raw["dev_password_hash"] = replacement
            self.write(raw)
            return real_hash(password)
        with patch("core.config.hash_password", side_effect=change_disk_while_deriving):
            with self.assertRaises(ConfigurationError) as caught:
                config.verify_dev_password(cfg, "secret")
        self.assertEqual(type(caught.exception).__name__, "ConfigurationError")
        self.assertEqual(cfg.dev_password_hash, old_hash)
        self.assertEqual(json.loads(self.path.read_text())["dev_password_hash"], replacement)

    def test_stale_authentication_cannot_restore_cleared_or_removed_credentials(self):
        for remaining in ({"dev_password_hash": ""}, {}):
            with self.subTest(remaining=remaining):
                cfg = self.legacy()
                self.write(remaining)
                original = self.path.read_bytes()
                self.assertFalse(config.verify_dev_password(cfg, "secret"))
                self.assertEqual(self.path.read_bytes(), original)

    def test_explicit_password_change_replaces_existing_password(self):
        cfg = self.legacy()
        config.set_dev_password(cfg, "changed")
        self.assertTrue(config.verify_dev_password(cfg, "changed"))
        self.assertFalse(config.verify_dev_password(cfg, "secret"))

    def test_failed_migration_restores_hash_in_memory_and_disk(self):
        cfg = self.legacy()
        old_hash = cfg.dev_password_hash
        original = self.path.read_bytes()
        with patch("core.config.save_config", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                config.verify_dev_password(cfg, "secret")
        self.assertEqual(cfg.dev_password_hash, old_hash)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_password_change_restores_old_hash(self):
        cfg = self.legacy()
        old_hash = cfg.dev_password_hash
        with patch("core.config.save_config", side_effect=OSError("denied")):
            with self.assertRaises(OSError):
                config.set_dev_password(cfg, "new")
        self.assertEqual(cfg.dev_password_hash, old_hash)

    def test_malformed_or_unbounded_hashes_fail_closed_without_derivation(self):
        bad = ["bad", "pbkdf2_sha256$999999999999$" + "aa" * 16 + "$" + "bb" * 32,
               "pbkdf2_sha256$600000$zz$xx", "pbkdf2_sha256$1$" + "aa" * 16 + "$" + "bb" * 32]
        with patch("hashlib.pbkdf2_hmac", side_effect=AssertionError("must not derive")):
            for encoded in bad:
                self.assertFalse(config.verify_dev_password(config.PXCoreConfig(dev_password_hash=encoded), "secret"))


class JsonBoundaryTests(IsolatedConfigTest):
    def store(self):
        self.assertIsNotNone(importlib.util.find_spec("core.json_store"), "atomic JSON boundary is missing")
        return importlib.import_module("core.json_store")

    def test_read_permission_error_preserves_cause_and_source(self):
        store = self.store()
        self.write({"safe": True})
        original = self.path.read_bytes()
        with patch.object(Path, "read_text", side_effect=PermissionError("secret payload")):
            with self.assertRaises(store.ConfigurationReadError) as caught:
                store.read_json_config(self.path, {})
        self.assertIsInstance(caught.exception.__cause__, PermissionError)
        self.assertNotIn("secret payload", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_replace_and_fsync_leave_original_and_no_temporary_file(self):
        store = self.store()
        for operation in ("replace", "fsync"):
            with self.subTest(operation=operation):
                self.write({"old": 1})
                original = self.path.read_bytes()
                with patch("core.json_store.os." + operation, side_effect=OSError("interrupted")):
                    with self.assertRaises(store.ConfigurationWriteError):
                        store.write_json_config(self.path, {"new": 2})
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_json_nonfinite_duplicate_keys_and_invalid_output_are_rejected(self):
        store = self.store()
        for content in ('{"a": NaN}', '{"a": 1e999}', '{"a": 1, "a": 2}'):
            self.path.write_text(content, encoding="utf-8")
            with self.assertRaises(store.ConfigurationValidationError):
                store.read_json_config(self.path, {})
        self.write({"old": 1})
        with self.assertRaises(store.ConfigurationValidationError):
            store.write_json_config(self.path, {"bad": float("nan")})
        self.assertEqual(json.loads(self.path.read_text()), {"old": 1})

    def test_invalid_values_are_rejected_before_any_recovery_backup(self):
        store = self.store()
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(store.ConfigurationValidationError):
            store.recover_json_config(self.path, {"bad": float("inf")})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_recovery_replace_failure_keeps_original_and_preserved_copy(self):
        store = self.store()
        self.path.write_text("{broken", encoding="utf-8")
        with patch("core.json_store.os.replace", side_effect=PermissionError("denied")):
            with self.assertRaises(store.ConfigurationWriteError):
                store.recover_json_config(self.path, {})
        self.assertEqual(self.path.read_text(), "{broken")
        backups = list(self.path.parent.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "{broken")

    def test_missing_defaults_are_independent_and_invalid_nested_numbers_are_rejected(self):
        store = self.store()
        defaults = {"items": []}
        result = store.read_json_config(self.path, defaults)
        result["items"].append("change")
        self.assertEqual(defaults, {"items": []})
        self.path.write_text('{"nested": [1e999]}', encoding="utf-8")
        with self.assertRaises(store.ConfigurationValidationError):
            store.read_json_config(self.path, {})

    def test_recovery_is_explicit_and_preserves_every_original_byte(self):
        store = self.store()
        original = b"{corrupt\xff\n"
        self.path.write_bytes(original)
        backup = store.recover_json_config(self.path, {"recovered": True})
        self.assertEqual(backup.parent, self.path.parent)
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(json.loads(self.path.read_text()), {"recovered": True})
        second = store.recover_json_config(self.path, {})
        self.assertNotEqual(backup, second)
        self.assertEqual(backup.read_bytes(), original)


class CatalogueTests(IsolatedConfigTest):
    def test_catalogues_reject_corrupt_and_invalid_existing_files(self):
        stores = [(printers, "_store_path", printers.load_printers, printers.save_printers, []),
                  (fabrics, "_fabrics_store_path", fabrics.load_fabrics, fabrics.save_fabrics, {}),
                  (fabric_scraps, "_store_path", fabric_scraps.load_scraps, fabric_scraps.save_scraps, [])]
        for module, path_name, load, save, empty in stores:
            with self.subTest(module=module.__name__), patch.object(module, path_name, return_value=self.path):
                self.path.write_text("{broken", encoding="utf-8")
                with self.assertRaises(ConfigurationValidationError):
                    load()
                with self.assertRaises(ConfigurationValidationError):
                    save(empty)
                self.assertEqual(self.path.read_text(), "{broken")

    def test_printer_and_scrap_extension_fields_survive_edit(self):
        cases = [(printers, printers.load_printers, printers.save_printers,
                  {"key": "stable", "name": "Printer", "display_name": "M", "future": {"one": 1}}),
                 (fabric_scraps, fabric_scraps.load_scraps, fabric_scraps.save_scraps,
                  {"key": "stable", "name": "Scrap", "fabric": "Dryfit", "length_m": 3, "future": {"one": 1}})]
        for module, load, save, raw in cases:
            with self.subTest(module=module.__name__), patch.object(module, "_store_path", return_value=self.path):
                self.write([raw])
                entries = load()
                entries[0].name = "Edited"
                save(entries)
                saved = json.loads(self.path.read_text())[0]
                self.assertEqual(saved["key"], "stable")
                self.assertEqual(saved["future"], raw["future"])

    def test_fabric_legacy_format_and_extensions_survive(self):
        raw = {"Old": ["alias"], "New": {"aliases": ["new"], "roll_length_m": 30, "future": 9}}
        self.write(raw)
        with patch.object(fabrics, "_fabrics_store_path", return_value=self.path):
            data = fabrics.load_fabrics()
            fabrics.save_fabrics(data)
        self.assertEqual(json.loads(self.path.read_text())["New"]["future"], 9)

    def operation_config(self):
        # The package initializes its path at import time; isolate APPDATA first.
        with patch.dict(os.environ, {"APPDATA": str(self.path.parent)}):
            return importlib.import_module("modules.operacao.config")

    def test_operation_corruption_and_invalid_boolean_are_visible(self):
        operation = self.operation_config()
        with patch.object(operation, "CFG_PATH", self.path):
            for original in ("", "{broken", '{"group_consecutive_spaces": "false"}'):
                self.path.write_text(original, encoding="utf-8")
                with self.assertRaises(ConfigurationValidationError):
                    operation.load_cfg()
                with self.assertRaises(ConfigurationValidationError):
                    operation.save_cfg({})
                self.assertEqual(self.path.read_text(), original)

    def test_operation_preserves_metadata_after_existing_normalizers(self):
        operation = self.operation_config()
        from core.operators import normalize_operators
        from core.print_types import normalize_rules
        raw = {"future": 9, "operators": [{"identifier": "N", "name": "Operator", "future": 1}],
               "print_type_rules": [{"id": "stable", "name": "Rule", "pattern": "^R", "future": 2}]}
        self.write(raw)
        with patch.object(operation, "CFG_PATH", self.path):
            loaded = operation.load_cfg()
            loaded["operators"] = normalize_operators(loaded["operators"])
            loaded["print_type_rules"] = normalize_rules(loaded["print_type_rules"])
            operation.save_cfg(loaded)
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["future"], 9)
        self.assertEqual(saved["operators"][0]["future"], 1)
        self.assertEqual(saved["print_type_rules"][0]["future"], 2)
        self.assertEqual(saved["print_type_rules"][0]["id"], "stable")


if __name__ == "__main__":
    unittest.main()
