"""Explicit SQLite diagnostics and validated backups, without application configuration.

Sources are opened with ``mode=ro`` and never initialized, migrated or restored.
DELETE journaling remains the application's production setting; it still depends
on correct filesystem locks and does not guarantee safe concurrent use over SMB.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from core.logging_config import get_logger, log_exception


_logger = get_logger(__name__)


class DatabaseUnavailableError(sqlite3.OperationalError):
    """A database operation could not complete; the original cause is retained."""

    @classmethod
    def from_exception(cls, exc: BaseException, *, operation: str) -> DatabaseUnavailableError:
        """Build an actionable message from safe codes, never raw error text."""
        code = getattr(exc, "sqlite_errorcode", None)
        primary = (code & 0xFF) if isinstance(code, int) else None
        system_errno = getattr(exc, "errno", None)
        if primary in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            hint = "O banco de dados está ocupado. Aguarde e tente novamente; verifique operações abertas em outras máquinas se persistir."
        elif primary in (sqlite3.SQLITE_PERM, sqlite3.SQLITE_AUTH, sqlite3.SQLITE_READONLY) or isinstance(exc, PermissionError):
            hint = "Permissão insuficiente. Verifique as permissões do arquivo e da pasta de dados."
        elif primary == sqlite3.SQLITE_CANTOPEN:
            hint = "Verifique se o arquivo existe, as permissões e o acesso à pasta ou ao compartilhamento de rede."
        elif primary in (sqlite3.SQLITE_IOERR, sqlite3.SQLITE_PROTOCOL, sqlite3.SQLITE_FULL):
            hint = "Falha de armazenamento ou rede. Verifique o espaço disponível, o disco e a conexão com o compartilhamento."
        elif isinstance(exc, FileNotFoundError):
            hint = "Arquivo ou pasta não encontrado. Verifique a origem e a pasta de destino."
        else:
            hint = "Verifique a disponibilidade, as permissões e o acesso à pasta ou ao compartilhamento de rede."
        metadata = []
        name = getattr(exc, "sqlite_errorname", None)
        if isinstance(name, str) and re.fullmatch(r"SQLITE_[A-Z0-9_]+", name):
            metadata.append(name)
        if isinstance(code, int):
            metadata.append(f"sqlite_errorcode={code}")
        if isinstance(system_errno, int):
            metadata.append(f"errno={system_errno}")
        result = cls(f"Falha ao {operation}. {hint}" + (" (" + ", ".join(metadata) + ")" if metadata else ""))
        for attribute in ("sqlite_errorcode", "sqlite_errorname", "errno"):
            value = getattr(exc, attribute, None)
            if attribute != "sqlite_errorname" or (isinstance(value, str) and re.fullmatch(r"SQLITE_[A-Z0-9_]+", value)):
                if value is not None:
                    setattr(result, attribute, value)
        return result


@dataclass(frozen=True)
class ForeignKeyViolation:
    table: str
    rowid: int | None
    parent: str
    foreign_key_index: int


@dataclass(frozen=True)
class IntegrityReport:
    """Raw integrity messages and structured FK violations; never production rows.

    ``healthy`` is true only when integrity_check returned exactly ``ok`` and
    foreign_key_check completed without violations or errors. ``check_errors``
    contains SQLite error names when corruption/schema errors prevent a check.
    """

    integrity_messages: tuple[str, ...]
    foreign_key_violations: tuple[ForeignKeyViolation, ...]
    check_errors: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.integrity_messages == ("ok",) and not self.foreign_key_violations and not self.check_errors


class DatabaseIntegrityError(sqlite3.DatabaseError):
    """An unhealthy source or backup was rejected; details are in ``report``."""

    def __init__(self, report: IntegrityReport):
        super().__init__("A verificação de integridade do banco de dados falhou.")
        self.report = report


def _validate_timeout(timeout_ms: int) -> None:
    if type(timeout_ms) is not int or not 0 < timeout_ms <= 2_147_483_647:
        raise ValueError("timeout_ms deve ser um inteiro positivo de até 2147483647.")


def _readonly_uri(source_path: Path) -> str:
    uri = source_path.resolve().as_uri()
    # SQLite's default build rejects a non-local URI authority. An empty
    # authority plus a double-slash path represents a Windows UNC share.
    if uri.startswith("file://") and not uri.startswith("file:///"):
        uri = "file:////" + uri[len("file://"):]
    return uri + "?mode=ro"


def _open_readonly(source_path: Path, timeout_ms: int) -> sqlite3.Connection:
    con = sqlite3.connect(_readonly_uri(source_path), uri=True, timeout=timeout_ms / 1000)
    try:
        con.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        con.execute("PRAGMA query_only = ON")
        return con
    except BaseException:
        con.close()
        raise


def _primary_code(exc: sqlite3.Error) -> int | None:
    code = getattr(exc, "sqlite_errorcode", None)
    return (code & 0xFF) if isinstance(code, int) else None


def _error_name(exc: sqlite3.Error) -> str:
    return str(getattr(exc, "sqlite_errorname", type(exc).__name__))


def _diagnose_connection(con: sqlite3.Connection) -> IntegrityReport:
    try:
        messages = tuple(str(row[0]) for row in con.execute("PRAGMA integrity_check").fetchall())
    except sqlite3.DatabaseError as exc:
        if _primary_code(exc) not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise
        log_exception(_logger, "SQLite integrity check detected corruption", exc)
        return IntegrityReport((), (), (_error_name(exc),))
    try:
        violations = tuple(
            ForeignKeyViolation(str(row[0]), row[1], str(row[2]), int(row[3]))
            for row in con.execute("PRAGMA foreign_key_check").fetchall()
        )
    except sqlite3.DatabaseError as exc:
        if _primary_code(exc) not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_ERROR):
            raise
        log_exception(_logger, "SQLite foreign key check could not validate schema", exc)
        return IntegrityReport(messages, (), (_error_name(exc),))
    return IntegrityReport(messages, violations)


def diagnose_database(source_path: str | Path, *, timeout_ms: int = 5000) -> IntegrityReport:
    """Check an existing file using both PRAGMAs in one read transaction.

    An unhealthy database returns a report. Missing/inaccessible/locked sources
    raise DatabaseUnavailableError with their cause; they never appear healthy
    or become newly created empty databases. The caller chooses the path.
    """
    _validate_timeout(timeout_ms)
    try:
        with closing(_open_readonly(Path(source_path), timeout_ms)) as con:
            con.execute("BEGIN")
            report = _diagnose_connection(con)
        if not report.healthy:
            _logger.warning("SQLite diagnosis returned an unhealthy report")
        return report
    except (sqlite3.Error, OSError) as exc:
        log_exception(_logger, "SQLite diagnosis unavailable", exc)
        raise DatabaseUnavailableError.from_exception(exc, operation="verificar o banco de dados") from exc


def backup_database(
    source_path: str | Path,
    destination_path: str | Path,
    *,
    timeout_ms: int = 5000,
) -> Path:
    """Create and validate a new SQLite API backup, returning its Path.

    The source remains read-only. An exclusive destination reservation refuses
    any existing file (FileExistsError), including the source itself. Parent
    directories must already exist. Both source and backup must pass both
    checks, or DatabaseIntegrityError carries the unhealthy report. Other I/O
    and SQLite failures raise DatabaseUnavailableError. All handles close before
    failed output cleanup; only this attempt's newly reserved file is removed.
    No restore, overwrite or schema migration is performed.

    timeout_ms bounds SQLite lock waits, including backup API BUSY/LOCKED
    retries; it is not a size-dependent deadline for copying a healthy database.
    """
    _validate_timeout(timeout_ms)
    destination = Path(destination_path)
    reserved = False
    completed = False
    try:
        with closing(_open_readonly(Path(source_path), timeout_ms)) as source:
            source.execute("BEGIN")
            source_report = _diagnose_connection(source)
            if not source_report.healthy:
                raise DatabaseIntegrityError(source_report)

            descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            reserved = True
            os.close(descriptor)
            with closing(sqlite3.connect(str(destination), timeout=timeout_ms / 1000)) as backup:
                backup.execute(f"PRAGMA busy_timeout = {timeout_ms}")
                lock_deadline = time.monotonic() + timeout_ms / 1000

                def progress(status: int, remaining: int, total: int) -> None:
                    nonlocal lock_deadline
                    if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        if time.monotonic() >= lock_deadline:
                            cause = sqlite3.OperationalError("SQLite backup lock timeout")
                            cause.sqlite_errorcode = status
                            cause.sqlite_errorname = "SQLITE_BUSY" if status == sqlite3.SQLITE_BUSY else "SQLITE_LOCKED"
                            raise DatabaseUnavailableError.from_exception(cause, operation="criar o backup") from cause
                    else:
                        lock_deadline = time.monotonic() + timeout_ms / 1000

                source.backup(backup, pages=128, progress=progress, sleep=min(0.05, timeout_ms / 1000))
                report = _diagnose_connection(backup)
                if not report.healthy:
                    raise DatabaseIntegrityError(report)
        completed = True
        _logger.info("SQLite backup created and validated")
        return destination
    except FileExistsError:
        _logger.warning("SQLite backup refused an existing destination")
        raise FileExistsError("O destino do backup já existe; escolha um novo arquivo.") from None
    except (DatabaseIntegrityError, DatabaseUnavailableError) as exc:
        log_exception(_logger, "SQLite backup rejected", exc)
        raise
    except (sqlite3.Error, OSError) as exc:
        log_exception(_logger, "SQLite backup unavailable", exc)
        raise DatabaseUnavailableError.from_exception(exc, operation="criar o backup do banco de dados") from exc
    finally:
        if reserved and not completed:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                # A failed unlink cannot turn an unsuccessful backup into a
                # successful one or mask the original failure. Log metadata.
                log_exception(_logger, "SQLite incomplete backup cleanup failed", exc)
