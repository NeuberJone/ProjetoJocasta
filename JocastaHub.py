from __future__ import annotations

import json
import os
import importlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# Root precisa ser TkinterDnD.Tk para drag & drop
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore
    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


APP_NAME = "JocastaHub"


# =========================
# Config helpers
# =========================
def get_config_path() -> Path:
    """
    User-writable config path:
      - Windows: %APPDATA%\\JocastaHub\\config.json
      - Linux: ~/.config/JocastaHub/config.json
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.json"
    return Path.home() / ".config" / APP_NAME / "config.json"


def load_config() -> dict:
    path = get_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    path = get_config_path()
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
        super().__init__()

        self.title("Projeto Jocasta")
        self.geometry("1100x720")
        self.minsize(980, 600)

        # ---- config ----
        self.config_data = load_config()

        # ---- Notebook ----
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # ---- Fluxos de Trabalho ----
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
                ("Jarvis", "modules.Jarvis"),
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

        # ---- Menu ----
        self._build_menu()

        # ---- Fluxo inicial ----
        self.current_flow = self.config_data.get("default_flow", "SISBolt")
        if self.current_flow not in self.FLOWS:
            self.current_flow = "SISBolt"

        self.load_flow(self.current_flow)

    # =========================
    # Menu
    # =========================
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        menu_fluxos = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fluxos de Trabalho", menu=menu_fluxos)

        for flow_name in self.FLOWS.keys():
            menu_fluxos.add_command(
                label=flow_name,
                command=lambda fn=flow_name: self.load_flow(fn)
            )

        menu_fluxos.add_separator()

        # ✅ NOVA OPÇÃO (acima de recarregar)
        menu_fluxos.add_command(
            label="Definir fluxo atual como padrão",
            command=self.set_default_workflow
        )

        menu_fluxos.add_command(
            label="Recarregar fluxo atual",
            command=self.reload_current_flow
        )

        self.config(menu=menubar)

    # =========================
    # Workflow default
    # =========================
    def set_default_workflow(self) -> None:
        self.config_data["default_flow"] = self.current_flow
        save_config(self.config_data)

        messagebox.showinfo(
            "Projeto Jocasta",
            f"Fluxo '{self.current_flow}' definido como padrão."
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

        self.title(f"Projeto Jocasta — {flow_name}")

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
                f"Falha ao importar {module_name}.py:\n\n{type(mod).__name__}: {mod}"
            )
            return

        build_ui = getattr(mod, "build_ui", None)
        if not callable(build_ui):
            self._render_error(
                tab,
                f"O módulo {module_name}.py não tem build_ui(parent).\n"
                f"Ele precisa expor essa função para rodar dentro do Hub."
            )
            return

        try:
            ui = build_ui(tab)
            if isinstance(ui, tk.Widget):
                ui.pack(fill="both", expand=True)
        except Exception as e:
            self._render_error(
                tab,
                f"Falha ao montar UI de {module_name}.py:\n\n{type(e).__name__}: {e}"
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
