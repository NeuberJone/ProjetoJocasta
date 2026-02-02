from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

# Root precisa ser TkinterDnD.Tk para os apps com drag&drop funcionarem dentro das abas
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore
    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


def _safe_import(name: str):
    """
    Import seguro de módulos (retorna Exception em caso de erro).
    """
    try:
        return __import__(name)
    except Exception as e:
        return e


class JocastaHub(RootBase):
    """
    Hub por Fluxos de Trabalho:
      - SISBolt
      - Power Duplicate
      - Impressão
      - Utilitários
      - Legado

    Ao selecionar um fluxo, o Notebook é reconstruído mostrando somente
    os módulos daquele fluxo.
    """

    def __init__(self) -> None:
        super().__init__()

        self.title("Projeto Jocasta")
        self.geometry("1100x720")
        self.minsize(980, 600)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # Define os fluxos e quais módulos aparecem em cada um
        self.FLOWS: dict[str, list[tuple[str, str]]] = {
            "SISBolt": [
                ("PXFlow", "PXFlow"),
                ("PXComposer", "PXComposer"),
            ],
            "Power Duplicate": [
                ("PXDupe", "PXDupe"),
            ],
            "Impressão": [
                ("PXPrint", "PXPrint"),
            ],
            "Utilitários": [
                ("Jarvis", "Jarvis"),
            ],
            "Legado": [
                ("PXListLite", "PXListLite"),
                ("PXTotaList", "PXTotaList"),
                ("PXList", "PXList"),
                ("PXListPlus", "PXListPlus"),
                ("PXSort", "PXSort"),
                ("PXSortLite", "PXSortLite"),
            ],
        }

        # Menu principal (Fluxos de Trabalho)
        self._build_menu()

        # Fluxo inicial
        self.current_flow = "SISBolt"
        self.load_flow(self.current_flow)

    # =========================
    # Menu
    # =========================
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        menu_fluxos = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fluxos de Trabalho", menu=menu_fluxos)

        # Um item por fluxo
        for flow_name in self.FLOWS.keys():
            menu_fluxos.add_command(
                label=flow_name,
                command=lambda fn=flow_name: self.load_flow(fn)
            )

        menu_fluxos.add_separator()
        menu_fluxos.add_command(label="Recarregar fluxo atual", command=self.reload_current_flow)

        # Menu Ajuda (opcional)
        menu_ajuda = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Ajuda", menu=menu_ajuda)
        menu_ajuda.add_command(
            label="Sobre",
            command=lambda: messagebox.showinfo(
                "Projeto Jocasta",
                "JocastaHub — Hub por Fluxos de Trabalho\n\n"
                "Selecione um fluxo em 'Fluxos de Trabalho' para exibir apenas os módulos daquele grupo."
            )
        )

        self.config(menu=menubar)

    # =========================
    # Fluxos
    # =========================
    def reload_current_flow(self) -> None:
        self.load_flow(self.current_flow)

    def load_flow(self, flow_name: str) -> None:
        """
        Limpa todas as abas e recria somente as abas do fluxo selecionado.
        """
        if flow_name not in self.FLOWS:
            messagebox.showerror("Projeto Jocasta", f"Fluxo desconhecido: {flow_name}")
            return

        self.current_flow = flow_name
        self._clear_tabs()

        modules = self.FLOWS[flow_name]
        for title, module_name in modules:
            self._add_tab(title, module_name)

        # Atualiza o título com o fluxo atual
        self.title(f"Projeto Jocasta — {flow_name}")

    def _clear_tabs(self) -> None:
        """
        Remove todas as abas do Notebook.
        """
        for tab_id in self.nb.tabs():
            self.nb.forget(tab_id)

    # =========================
    # Tabs / Render
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
