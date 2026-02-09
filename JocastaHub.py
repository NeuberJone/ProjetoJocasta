from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from core.version import __version__
from core.config import load_config as load_pxcore_config


# Root precisa ser TkinterDnD.Tk para drag & drop
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore

    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


APP_NAME = "JocastaHub"


# =========================
# Hub Config helpers (prefs do Hub: ex. default_flow)
# =========================
def get_hub_config_path() -> Path:
    """
    User-writable config path:
      - Windows: %APPDATA%\\JocastaHub\\config.json
      - Linux: ~/.config/JocastaHub/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.json"
    return Path.home() / ".config" / APP_NAME / "config.json"


def load_hub_config() -> dict:
    path = get_hub_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_hub_config(cfg: dict) -> None:
    path = get_hub_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception as e:
        return e


# =========================
# Main App
# =========================
class JocastaHub(RootBase):
    def __init__(self) -> None:
        # Carrega config do PXCore (cria pastas/arquivos se necessário)
        try:
            self.px_cfg = load_pxcore_config()
        except Exception as e:
            self.px_cfg = None
            messagebox.showwarning(
                "PXCore",
                f"Falha ao carregar configurações do PXCore.\n\n{type(e).__name__}: {e}",
            )

        super().__init__()

        self.title(f"Projeto Jocasta v{__version__}")
        self.geometry("1100x720")
        self.minsize(980, 600)

        # Prefs do Hub (default_flow)
        self.config_data = load_hub_config()

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # Fluxos: (display_name, module_name)
        self.FLOWS: dict[str, list[tuple[str, str]]] = {
            "SISBolt": [
                ("PXFlow", "modules.PXFlow"),
                ("PXComposer", "modules.PXComposer"),
            ],
            "Power Duplicate": [
                ("PXDupe", "modules.PXDupe"),
            ],
            "Impressão": [
                ("PXPrintLogs", "modules.PXPrintLogs"),
                ("PXPrint", "modules.PXPrint"),
            ],
            "Utilitários": [
                ("PXOrderList", "modules.PXOrderList"),
                ("PXBridge", "modules.PXBridge"),
            ],
            "Legado": [
                ("PXListLite", "modules.PXListLite"),
                ("PXTotaList", "modules.PXTotaList"),
                ("PXList", "modules.PXList"),
                ("PXListPlus", "modules.PXListPlus"),
                ("PXSort", "modules.PXSort"),
                ("PXSortLite", "modules.PXSortLite"),
            ],
        }

        # Menu
        self._build_menu()

        # Fluxo inicial
        self.current_flow = self.config_data.get("default_flow", "SISBolt")
        if self.current_flow not in self.FLOWS:
            self.current_flow = "SISBolt"

        self.load_flow(self.current_flow)

    # =========================
    # Menu
    # =========================
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        # ---- Fluxos de Trabalho ----
        menu_fluxos = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fluxos de Trabalho", menu=menu_fluxos)

        for flow_name in self.FLOWS.keys():
            menu_fluxos.add_command(
                label=flow_name,
                command=lambda fn=flow_name: self.load_flow(fn),
            )

        menu_fluxos.add_separator()

        menu_fluxos.add_command(
            label="Definir fluxo atual como padrão",
            command=self.set_default_workflow,
        )

        menu_fluxos.add_command(
            label="Recarregar fluxo atual",
            command=self.reload_current_flow,
        )

        # ---- Configurações ----
        menu_config = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configurações", menu=menu_config)

        menu_config.add_command(label="Abrir Configurações", command=self.open_settings)
        menu_config.add_separator()
        menu_config.add_command(label="Abrir Pasta do PXCore", command=self.open_pxcore_folder)

        # ✅ aplica na janela (sem isso o menu não aparece)
        self.config(menu=menubar)

    # =========================
    # Config actions
    # =========================
    def open_pxcore_folder(self) -> None:
        try:
            from core.paths import open_in_explorer

            cfg = load_pxcore_config()
            if not cfg:
                messagebox.showerror("Configurações", "Config do PXCore não carregou (cfg=None).")
                return

            # cfg pode ser dataclass (cfg.base_dir) ou dict (cfg["base_dir"])
            base_dir = getattr(cfg, "base_dir", None)
            if base_dir is None and isinstance(cfg, dict):
                base_dir = cfg.get("base_dir")

            if not base_dir:
                messagebox.showerror("Configurações", "base_dir não encontrado na configuração do PXCore.")
                return

            open_in_explorer(Path(str(base_dir)))

        except Exception as e:
            messagebox.showerror(
                "Configurações",
                f"Não foi possível abrir a pasta.\n\n{type(e).__name__}: {e}",
            )



    def open_settings(self) -> None:
        from core.config import save_config as save_pxcore_config

        cfg = load_pxcore_config()

        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("520x260")
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        # Diretório base
        ttk.Label(frm, text="Diretório base do PXCore:").pack(anchor="w")
        base_dir = getattr(cfg, "base_dir", None)
        if base_dir is None and isinstance(cfg, dict):
            base_dir = cfg.get("base_dir", "")
        base_var = tk.StringVar(value=str(base_dir or ""))

        ttk.Entry(frm, textvariable=base_var, state="readonly").pack(fill="x", pady=(4, 8))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(0, 12))
        ttk.Button(btns, text="📁 Abrir pasta", command=self.open_pxcore_folder).pack(side="left")

        # Modo Dev (salva no config do PXCore)
        dev_var = tk.BooleanVar(value=bool(getattr(cfg, "dev_mode_enabled", False)))

        def on_toggle_dev() -> None:
            cfg.dev_mode_enabled = dev_var.get()
            save_pxcore_config(cfg)

        ttk.Checkbutton(
            frm,
            text="Ativar Modo Dev",
            variable=dev_var,
            command=on_toggle_dev,
        ).pack(anchor="w")

        ttk.Separator(frm).pack(fill="x", pady=12)
        ttk.Label(frm, text="(Senha do Modo Dev será adicionada na próxima etapa.)").pack(anchor="w")

    # =========================
    # Workflow default
    # =========================
    def set_default_workflow(self) -> None:
        self.config_data["default_flow"] = self.current_flow
        save_hub_config(self.config_data)

        messagebox.showinfo(
            "Projeto Jocasta",
            f"Fluxo '{self.current_flow}' definido como padrão.",
        )

    # =========================
    # Fluxos
    # =========================
    def reload_current_flow(self) -> None:
        self.load_flow(self.current_flow)

    def load_flow(self, flow_name: str) -> None:
        if flow_name not in self.FLOWS:
            messagebox.showerror("Projeto Jocasta", f"Fluxo desconhecido: {flow_name}")
            return

        self.current_flow = flow_name
        self._clear_tabs()

        for title, module_name in self.FLOWS[flow_name]:
            self._add_tab(title, module_name)

        self.title(f"Projeto Jocasta v{__version__} — {flow_name}")

    def _clear_tabs(self) -> None:
        for tab_id in self.nb.tabs():
            self.nb.forget(tab_id)

    # =========================
    # Tabs
    # =========================
    def _add_tab(self, title: str, module_name: str) -> None:
        tab = ttk.Frame(self.nb)
        tab.pack(fill="both", expand=True)
        self.nb.add(tab, text=title)

        mod = _safe_import(module_name)
        if isinstance(mod, Exception):
            self._render_error(
                tab,
                f"Falha ao importar {module_name}.py:\n\n{type(mod).__name__}: {mod}",
            )
            return

        build_ui = getattr(mod, "build_ui", None)
        if not callable(build_ui):
            self._render_error(
                tab,
                f"O módulo {module_name}.py não tem build_ui(parent).\n"
                f"Ele precisa expor essa função para rodar dentro do Hub.",
            )
            return

        try:
            ui = build_ui(tab)
            if isinstance(ui, tk.Widget):
                ui.pack(fill="both", expand=True)
        except Exception as e:
            self._render_error(
                tab,
                f"Falha ao montar UI de {module_name}.py:\n\n{type(e).__name__}: {e}",
            )

    def _render_error(self, parent: ttk.Frame, text: str) -> None:
        t = tk.Text(parent, wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)


def main() -> None:
    JocastaHub().mainloop()


if __name__ == "__main__":
    main()
