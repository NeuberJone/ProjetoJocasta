from __future__ import annotations

import tkinter as tk
from tkinter import ttk


# Root precisa ser TkinterDnD.Tk para os apps com drag&drop funcionarem dentro das abas
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore
    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception as e:
        return e


class JocastaHub(RootBase):
    def __init__(self) -> None:
        super().__init__()

        self.title("Projeto Jocasta")
        self.geometry("1100x720")
        self.minsize(980, 600)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self._add_tab("PXList", "PXList")
        self._add_tab("PXTotaList", "PXTotaList")
        self._add_tab("PXListLite", "PXListLite")
        self._add_tab("PXListPlus", "PXListPlus")
        self._add_tab("PXSort", "PXSort")
        self._add_tab("PXSortLite", "PXSortLite")
        self._add_tab("Jarvis", "Jarvis")

    def _add_tab(self, title: str, module_name: str) -> None:
        tab = ttk.Frame(self.nb)
        tab.pack(fill="both", expand=True)
        self.nb.add(tab, text=title)

        mod = _safe_import(module_name)
        if isinstance(mod, Exception):
            self._render_error(tab, f"Falha ao importar {module_name}.py:\n\n{type(mod).__name__}: {mod}")
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
            self._render_error(tab, f"Falha ao montar UI de {module_name}.py:\n\n{type(e).__name__}: {e}")

    def _render_error(self, parent: ttk.Frame, text: str) -> None:
        t = tk.Text(parent, wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)


def main() -> None:
    JocastaHub().mainloop()


if __name__ == "__main__":
    main()
