"""Windows GUI smoke check using only temporary application data in this repo.

Run manually: python scripts/smoke-ui-isolated.py
Needs a working Tcl/Tk installation and a desktop session; not a headless test.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    workspace = repo / "build" / "ui-smoke"
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workspace) as temporary, ExitStack() as cleanups:
        sandbox = Path(temporary)
        for variable in ("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR"):
            directory = sandbox / variable.lower()
            directory.mkdir()
            os.environ[variable] = str(directory)
        os.environ["XDG_STATE_HOME"] = str(sandbox / "state")
        tempfile.tempdir = os.environ["TEMP"]
        sys.path.insert(0, str(repo))

        from core.config import _config_path
        from core.logging_config import configure_logging, get_logger

        config = _config_path()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"base_dir": str(sandbox / "production"), "theme_name": "dark"}), encoding="utf-8")
        configure_logging(sandbox / "technical-logs")

        def close_logs():
            logger = get_logger("nexor")
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)

        cleanups.callback(close_logs)

        import tkinter as tk
        from Nexor import Nexor, MODULES, SETTINGS_TITLE, MANUAL_TITLE, RELEASE_NOTES_TITLE
        from core import theme
        from core.printlogs_db import save_export_transactional, OrderRow

        original_init = tk.Tk.__init__

        def hidden_init(root, *args, **kwargs):
            original_init(root, *args, **kwargs)
            root.withdraw()
            root.attributes("-alpha", 0.0)

        with patch.object(tk.Tk, "__init__", hidden_init), \
                patch("Nexor.messagebox.showerror") as errors, \
                patch("Nexor.messagebox.showwarning") as warnings:
            app = Nexor()
            try:
                app.geometry("980x600")
                app.deiconify()
                app.update()
                with patch.object(app, "_render_error", side_effect=AssertionError("Page failed to load")):
                    for title in [*[title for title, _ in MODULES], SETTINGS_TITLE, MANUAL_TITLE, RELEASE_NOTES_TITLE]:
                        app.load_module(title)
                        app.update_idletasks()
                        assert app.current_module == title
                        assert app._pages[title].winfo_ismapped(), title
                    for title, _ in MODULES:
                        assert title in app._page_uis, title
                    for key in theme.theme_keys_ordered():
                        app._select_theme(key)
                        app.update_idletasks()
                        button = app._nav_buttons[SETTINGS_TITLE]
                        assert button.winfo_ismapped(), key
                        assert button.winfo_height() >= button.winfo_reqheight(), key
                        assert button.winfo_y() + button.winfo_height() <= button.master.winfo_height(), key
                    app.load_module("Registros")
                    app.update()
                    registros = app._page_uis["Registros"]
                    for tab_id in registros.top_nb.tabs():
                        registros.top_nb.select(tab_id)
                        app.update()
                        tab_frame = app.nametowidget(tab_id)
                        label = registros.top_nb.tab(tab_id, "text")
                        assert registros.top_nb.winfo_ismapped(), label
                        assert tab_frame.winfo_ismapped(), label
                        assert tab_frame.winfo_height() > 0, label
                    registros.top_nb.select(registros.tab_search)
                    app.update()
                    for tab_id in registros.nb.tabs():
                        registros.nb.select(tab_id)
                        app.update()
                        tab_frame = app.nametowidget(tab_id)
                        label = registros.nb.tab(tab_id, "text")
                        assert tab_frame.winfo_ismapped(), label
                        assert tab_frame.winfo_height() > 0, label

                    with patch("modules.registros.ui.messagebox.showinfo") as info:
                        registros._current_roll_id = None
                        registros._open_roll_details_window()
                        assert info.called

                    save_export_transactional(
                        "M1", "RoloSmoke_01", "normal", "smoke-test",
                        [OrderRow(
                            end_time="2026-11-20T10:00:00", document="smoke.pdf", fabric="Tecido Smoke",
                            pedido="PEDIDO-SMOKE", height_mm=1000.0, vpos_mm=0.0, real_m=5.0,
                            source_path="C:/smoke/smoke.pdf",
                        )],
                    )
                    registros.reload()
                    app.update()
                    rolls = registros.tree_rolls.get_children()
                    assert rolls, "seeded roll not listed"
                    registros.tree_rolls.selection_set(rolls[0])
                    app.update()
                    assert registros._current_roll_id is not None
                    before = set(registros.winfo_children())
                    registros._open_roll_details_window()
                    app.update()
                    opened = [w for w in registros.winfo_children() if w not in before]
                    assert len(opened) == 1, opened
                    detail_window = opened[0]
                    assert "RoloSmoke_01" in detail_window.title(), detail_window.title()
                    detail_window.destroy()
                    app.update()
                assert not errors.called, errors.call_args_list
                assert not warnings.called, warnings.call_args_list
            finally:
                app.destroy()
            print("Windows UI: startup, six pages, eight themes and 980x600 navigation OK")
            print("Windows UI: Registros tabs and empty-selection dialog OK")
            print("Windows UI: Registros 'Abrir em janela' dialog with a real roll OK")

            config.write_bytes(b"{invalid configuration")
            damaged = config.read_bytes()
            app = Nexor()
            try:
                assert app.px_cfg is None
                app.load_module(SETTINGS_TITLE)
                app.load_module(RELEASE_NOTES_TITLE)
                app.update_idletasks()
                assert config.read_bytes() == damaged
                assert warnings.called
            finally:
                app.destroy()
            print("Windows UI: invalid config reported, preserved, help remains accessible OK")

if __name__ == "__main__":
    main()
