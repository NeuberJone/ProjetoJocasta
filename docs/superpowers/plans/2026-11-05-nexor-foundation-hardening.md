# Nexor foundation hardening implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent tasks and review. No commit or push is authorized.

**Goal:** Strengthen existing configuration, local DEV authentication, SQLite diagnostics/backup, logging, tests and documentation without changing production behavior.

**Architecture:** Keep public entry points and existing file locations. Add small stdlib services for atomic JSON, password derivation, rotating technical logging and SQLite maintenance. Application boundaries report failures; production calculations and integration payloads remain unchanged.

**Tech Stack:** Python 3.13 baseline, Tkinter, SQLite, unittest, existing Pillow/ReportLab/PyMuPDF/tkinterdnd2, PyInstaller.

**Spec:** User's “Nexor — Fase 1: Consolidação, segurança e confiabilidade”, supplied 2026-11-05. This plan records the execution decisions; the user's complete requirements remain authoritative.

## Global constraints

- Work exclusively in `C:\Projetos\ProjetoJocasta`; retain existing uncommitted release-note changes and `.gitignore` edits.
- No commit, push, installer, version change, destructive migration, real user configuration/database access during tests, new business modules or GUI replacement.
- Preserve public APIs, config locations (especially `%APPDATA%\PXCore`), IDs, database history, themes, exports and PX Tool Box contracts.
- User-facing language uses “arquivo”, “item” or “trabalho de impressão”; technical `Job` names remain compatible.
- Existing migrations must preserve source legacy tables; diagnostics and backup must never initialize/migrate the source.

## Initial evidence / review focus

- Baseline: `python -m unittest discover -s tests -q`: 170 tests, OK.
- Configuration corruption must never select defaults and overwrite the existing file; test invalid/empty JSON, denied access, failed replace, original preservation, old configs and IDs.
- Authentication must preserve a legacy hash until successful authentication and successful persistence; test malformed formats and failed persistence.
- A SQLite source opened for diagnostics/backup must not be created, migrated, changed or overwritten; test absent/corrupt/locked sources, FK violations, rollback, failed backups and duplicate destinations.
- Callback failures and partial exports must not report full success or write sensitive payloads into technical logs.
- Windows and SMB validation are distinct from isolated unit tests; record what was actually tested.

## Task 1 — Atomic configuration and local DEV password (configuration agent)

Files: `core/config.py`, new `core/json_store.py`, optional `core/passwords.py`, existing JSON configuration stores and focused unittest modules. Coordinate exact file ownership before edits.

- [ ] Write and run failing unittest cases for first run, valid/old/empty/invalid configs, denied access, interrupted writes, preserved fields/IDs and module/store corruption.
- [ ] Introduce typed configuration errors, same-directory tempfile + flush/fsync + os.replace and validation before persistence. Existing unreadable/corrupt files remain untouched. Recovery requires an explicit function; never silently reset.
- [ ] Preserve existing public configuration and authentication signatures. Read SHA-1 hashes, compare securely, derive salted PBKDF2-HMAC-SHA256 hashes using stdlib, migrate only after correct credentials; preserve memory/disk on persistence failure.
- [ ] Protect module/operation/printer/fabric/scrap stores through common JSON persistence without modifying calculation rules.
- [ ] Run focused tests and report API/error handling to parent for UI integration.

## Task 2 — SQLite reliability and maintenance (database agent)

Files: `core/printlogs_db.py`, new `core/database_maintenance.py`, focused database tests.

- [ ] Test connection/PRAGMA failure cleanup, busy timeout, rollback and preservation of legacy schema/history.
- [ ] Keep `connect()` compatible, configure busy timeout, translate failures with cause and log safely, retain existing journal mode and source tables during migration.
- [ ] Implement `diagnose_database(path=None)` and `backup_database(destination, source=None)` on separate read-only source connections. Use integrity_check + foreign_key_check; no ensure_schema in maintenance.
- [ ] Use SQLite backup API, exclusive destination reservation/no overwrite, validate produced database, clean only files created by this attempt after failure. Bound retry time under lock.
- [ ] Run focused tests including consistent committed snapshots, corrupt/FK-invalid sources, duplicate destinations, failed backup and closed handles.

## Task 3 — Technical logging and UI boundaries (parent)

Files: new `core/logging_config.py`, `Nexor.py`, `core/paths.py`, selected import/export/settings UI handlers, tests.

- [ ] Test rotating logging path, idempotence, levels/origin/traceback, bounded files and redaction without real APPDATA.
- [ ] Configure application logging at startup under local Windows application data, independent of production/printer logs. Expose `get_logger(name)` and `log_exception(logger, message, exc)` safely to workers.
- [ ] Handle startup and Tk callback errors visibly, preserving causes. Add safe technical diagnostics at critical filesystem/import/export boundaries.
- [ ] Correct success reporting after database failure without changing calculations or export formats; keep partial output explicitly reported.
- [ ] Validate settings saves do not claim success on persistence failure and keep GUI usable with damaged config.

## Task 4 — Dependency/build/CI/documentation foundation (documentation agent)

Files: requirements definitions, `.github/workflows/tests.yml`, `Nexor.spec`, README, CHANGELOG, `docs/architecture/current-state.md`, `docs/architecture/technical-debt.md`, `docs/roadmaps/nexor-modernization-roadmap.md`.

- [ ] Inventory actual imports and installed versions; pin runtime/build dependencies with rationale, and distinguish portable tests/Windows build.
- [ ] Retain and explain Tcl/Tk spec adaptations. Document isolated build output so existing artifacts remain preserved. Do not generate an installer.
- [ ] Add CI without publishing side effects; validate YAML and commands locally where possible, explicitly report CI not remotely executed.
- [ ] Describe actual architecture, file locations, recovery/backup APIs, network limitations, integration contract and evidence. Mark roadmap complete only with implemented code and validation.

## Task 5 — Review and acceptance

- [ ] Independent code/spec review of each workstream and final integration; address material findings.
- [ ] Run `python -m unittest discover -s tests -v` and `python -m compileall -q Nexor.py core modules`.
- [ ] Run isolated Windows GUI smoke checks for startup/modules/themes/recovery, only if Tcl/Tk execution is available; no production config/database.
- [ ] Inspect final diff for business rule, contract, path, version and user-change preservation. Record validation limitations and manual SMB/real printer requirements.
- [ ] Deliver diagnosis, changed files, implementation, test outcomes, remaining risks, manual checks, phase 2 recommendations and suggested branch/English commit. Do not commit or push.

## Execution decisions

- Stay in the official directory; no worktree elsewhere. Suggested branch remains a suggestion unless Git permissions allow creating it without additional workflow overhead.
- PBKDF2 avoids a new authentication dependency. Database hashes identifying production records remain unchanged.
- Logging uses the `nexor` logger namespace; module names remain visible. Secret values and production payloads are not logged.
- Phase 1 does not regenerate or overwrite prior artifacts in `dist/`.
