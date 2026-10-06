# Nexor Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize the desktop UI to match the Nexor HTML prototype while preserving real application behavior.

**Architecture:** A small shared Tk/ttk visual kit supplies page headers, cards, badges and status bars. Existing module callbacks and data models stay in place; only widget composition and theme application are adjusted.

**Tech Stack:** Python, Tkinter/ttk, tkinterdnd2 when available, SQLite, ReportLab/Pillow where already used.

**Spec:** `docs/superpowers/specs/2026-10-05-nexor-interface-design.md`

## Global Constraints

- Preserve the current desktop stack and business logic.
- Do not alter pre-existing staging.
- Preserve all eight themes and persistence.
- Do not use a production database for tests.

## Review Focus

- A theme change must preserve loaded module widgets and selections.
- Existing Tk `Text`, `Listbox`, `Canvas`, `Menu` and modal dialogs must receive the active theme.
- Narrow windows must retain access to tables through scrolling.
- Legacy roll module names must still route to the correct editor.
- Export/import callbacks must remain bound to real functions, not prototype simulations.

### Task 1: Shared visual kit and theme lifecycle

**Files:** Create `core/ui.py`, modify `core/theme.py`, test `tests/test_ui_contracts.py`.

- [ ] Add reusable page/card/status helpers and tests for the public theme/page contracts.
- [ ] Ensure new `Toplevel` widgets are themed after their children exist and re-themed when the active theme changes.
- [ ] Run `python -m unittest discover -s tests -v` and `python -m compileall -q Nexor.py core modules`.

### Task 2: Shell and Configurações

**Files:** Modify `Nexor.py`, test shell/theme contracts.

- [ ] Add the prototype hierarchy: brand mark, grouped navigation, breadcrumb badge and persistent status strip.
- [ ] Recompose Configurações into appearance, work directory, printer and fabric cards without replacing callbacks.
- [ ] Verify theme selection persists and pages are not rebuilt.

### Task 3: Planejador

**Files:** Modify `modules/planejador.py`.

- [ ] Recompose the planner into heading/import, print configuration, advanced queue options, tabbed files/queue/rolls/orders, summaries and export cards.
- [ ] Keep drag/drop, DPI, axis, queue generation, scraps, list import/export, CSV/PDF/JPG and edit/expand dialogs connected.

### Task 4: Operação

**Files:** Modify `modules/operacao/ui.py`.

- [ ] Recompose log import, machine/roll summary, block/order tabs and export card.
- [ ] Keep parser, grouping, order/fabric editing, spaces, export and history update callbacks unchanged.

### Task 5: Registros and catalog dialogs

**Files:** Modify `modules/registros/ui.py` and dialog layout code in `Nexor.py` as needed.

- [ ] Recompose filters, roll list, selected-roll header and summary/orders/events tabs.
- [ ] Preserve search, selection, legacy routing, copy-name and edit-roll flows.
- [ ] Align printer, fabric, scrap and space dialogs to shared spacing/theme helpers.

### Task 6: Verification and documentation

**Files:** Modify `README.md` or `CHANGELOG.md` only where pertinent; add comparison matrix under `docs/`.

- [ ] Run unit/contract tests, compile, and isolated domain smoke checks.
- [ ] Inspect supplied HTML/Nexor PNGs and record corrected differences and any capture limitations.
- [ ] Generate fresh captures if a graphical display is available; otherwise report visual verification as pending.
