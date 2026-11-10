import logging
from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest

from core.logging_config import configure_logging, get_logger, log_exception


class TechnicalLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.log_dir = Path(self.temp.name)
        self.addCleanup(self.close_handlers)

    def close_handlers(self):
        logger = logging.getLogger("nexor")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_repeated_setup_writes_one_copy_with_module_and_all_levels(self):
        configure_logging(self.log_dir, level=logging.DEBUG)
        configure_logging(self.log_dir, level=logging.DEBUG)
        logger = get_logger("core.config")
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            logger.log(level, "event-%s", level)
        contents = (self.log_dir / "nexor.log").read_text(encoding="utf-8")
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            self.assertEqual(contents.count(f"event-{level}"), 1)
        self.assertIn("nexor.core.config", contents)

    def test_exception_has_stack_and_type_without_sensitive_message(self):
        configure_logging(self.log_dir)
        try:
            raise ValueError("password=private-password source=private-production-data")
        except ValueError as exc:
            log_exception(get_logger(__name__), "Configuration write failed", exc)
        contents = (self.log_dir / "nexor.log").read_text(encoding="utf-8")
        self.assertIn("Traceback", contents)
        self.assertIn("ValueError", contents)
        self.assertIn("Configuration write failed", contents)
        self.assertNotIn("private-password", contents)
        self.assertNotIn("private-production-data", contents)

    def test_rotation_limits_history(self):
        configure_logging(self.log_dir)
        handler = logging.getLogger("nexor").handlers[0]
        handler.maxBytes = 80
        logger = get_logger(__name__)
        for _ in range(20):
            logger.info("An event long enough to trigger rotation")
        self.assertLessEqual(len(list(self.log_dir.glob("nexor.log*"))), 4)
        self.assertTrue((self.log_dir / "nexor.log.1").exists())

    def test_cached_logger_does_not_send_raw_exception_to_fallback_after_cleanup(self):
        logger = get_logger(__name__)
        self.close_handlers()
        output = io.StringIO()
        with redirect_stderr(output):
            log_exception(logger, "Read failed", ValueError("secret=do-not-print"))
        self.assertNotIn("do-not-print", output.getvalue())


if __name__ == "__main__":
    unittest.main()
