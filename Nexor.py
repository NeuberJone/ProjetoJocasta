from __future__ import annotations

import importlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.version import __version__
from core.config import load_config as load_pxcore_config, save_config as save_pxcore_config
from core.printers import (
    Printer,
    load_printers,
    save_printers,
    add_or_update_printer,
    remove_printer,
)

# Root precisa ser TkinterDnD.Tk para drag & drop
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore
    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


# Módulos do app, na ordem em que aparecem no menu lateral.
MODULES: list[tuple[str, str]] = [
    ("Planejador", "modules.planejador"),
    ("Operação", "modules.operacao"),
    ("Registros", "modules.registros"),
]


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception as e:
        return e


# =========================
# Main App
# =========================
class Nexor(RootBase):
    def __init__(self) -> None:
        # PXCore config (cria dirs e config automaticamente)
        try:
            self.px_cfg = load_pxcore_config()
        except Exception as e:
            self.px_cfg = None
            messagebox.showwarning(
                "PXCore",
                f"Falha ao carregar configurações do PXCore.\n\n{type(e).__name__}: {e}",
            )

        super().__init__()

        self.title(f"Nexor v{__version__}")
        self.geometry("1100x720")
        self.minsize(980, 600)

        self._pages: dict[str, ttk.Frame] = {}
        self._nav_buttons: dict[str, ttk.Button] = {}
        self.current_module: str | None = None

        # Menu
        self._build_menu()

        # Layout: menu lateral fixo à esquerda + área de conteúdo à direita
        self._build_sidebar_layout()

        # abre no primeiro módulo
        self.load_module(MODULES[0][0])

    # =========================
    # Menu
    # =========================
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        menu_config = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configurações", menu=menu_config)
        menu_config.add_command(label="Abrir Configurações", command=self.open_settings)
        menu_config.add_command(label="Gerenciar Impressoras…", command=self.open_printers_dialog)
        menu_config.add_separator()
        menu_config.add_command(label="Abrir Pasta do PXCore", command=self.open_pxcore_folder)

        self.config(menu=menubar)

    # =========================
    # Menu lateral + conteúdo
    # =========================
    def _build_sidebar_layout(self) -> None:
        style = ttk.Style(self)
        style.configure("Nav.TButton", anchor="w", padding=(10, 8))
        style.configure(
            "NavSelected.TButton", anchor="w", padding=(10, 8), font=("TkDefaultFont", 9, "bold")
        )

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        sidebar = ttk.Frame(container, width=170, padding=(8, 12))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        for title, _module_path in MODULES:
            btn = ttk.Button(
                sidebar, text=title, style="Nav.TButton",
                command=lambda t=title: self.load_module(t),
            )
            btn.pack(fill="x", pady=(0, 6))
            self._nav_buttons[title] = btn

        ttk.Separator(container, orient="vertical").pack(side="left", fill="y")

        self.content = ttk.Frame(container)
        self.content.pack(side="left", fill="both", expand=True)

    def load_module(self, title: str) -> None:
        module_path = dict(MODULES).get(title)
        if module_path is None:
            messagebox.showerror("Nexor", f"Módulo desconhecido: {title}")
            return

        if title not in self._pages:
            page = ttk.Frame(self.content)
            self._build_module_page(page, title, module_path)
            self._pages[title] = page

        if self.current_module is not None and self.current_module in self._nav_buttons:
            self._pages[self.current_module].pack_forget()
            self._nav_buttons[self.current_module].configure(style="Nav.TButton")

        self._pages[title].pack(fill="both", expand=True)
        self._nav_buttons[title].configure(style="NavSelected.TButton")
        self.current_module = title
        self.title(f"Nexor v{__version__} — {title}")

    def _build_module_page(self, page: ttk.Frame, title: str, module_path: str) -> None:
        mod = _safe_import(module_path)
        if isinstance(mod, Exception):
            self._render_error(page, f"Falha ao importar {module_path}:\n\n{type(mod).__name__}: {mod}")
            return

        build_ui = getattr(mod, "build_ui", None)
        if not callable(build_ui):
            self._render_error(page, f"O módulo {module_path} não possui build_ui(parent).")
            return

        try:
            ui = build_ui(page)
            if isinstance(ui, tk.Widget):
                ui.pack(fill="both", expand=True)
        except Exception as e:
            self._render_error(page, f"Falha ao montar UI de {title}:\n\n{type(e).__name__}: {e}")

    def _render_error(self, parent: ttk.Frame, text: str) -> None:
        t = tk.Text(parent, wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)

    # =========================
    # Settings / PXCore
    # =========================
    def open_pxcore_folder(self) -> None:
        try:
            from core.paths import open_in_explorer

            base_dir = getattr(self.px_cfg, "base_dir", None)
            if not base_dir:
                messagebox.showerror("PXCore", "Diretório base não encontrado.")
                return

            open_in_explorer(Path(str(base_dir)))
        except Exception as e:
            messagebox.showerror(
                "Configurações",
                f"Não foi possível abrir a pasta.\n\n{type(e).__name__}: {e}",
            )

    def open_settings(self) -> None:
        if self.px_cfg is None:
            messagebox.showerror("PXCore", "Config do PXCore não carregou.")
            return

        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("560x260")
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        # Base dir
        ttk.Label(frm, text="Diretório base do PXCore:").pack(anchor="w")
        base_var = tk.StringVar(value=str(getattr(self.px_cfg, "base_dir", "")))
        base_row = ttk.Frame(frm)
        base_row.pack(fill="x", pady=(4, 2))
        ttk.Entry(base_row, textvariable=base_var).pack(side="left", fill="x", expand=True)

        def browse_base_dir() -> None:
            chosen = filedialog.askdirectory(title="Selecionar diretório base do PXCore")
            if chosen:
                base_var.set(chosen)

        ttk.Button(base_row, text="Procurar…", command=browse_base_dir).pack(side="left", padx=(6, 0))

        ttk.Label(
            frm,
            text=(
                "Para usar o mesmo banco de dados (Registros, números sequenciais\n"
                "de rolo) e as mesmas pastas de PDF/JPG em vários computadores, aponte\n"
                "todos eles para a mesma pasta de rede compartilhada aqui."
            ),
            justify="left",
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 6))

        def save_base_dir() -> None:
            new_dir = base_var.get().strip()
            if not new_dir:
                messagebox.showerror("Configurações", "Informe um diretório base.")
                return
            self.px_cfg.base_dir = new_dir
            save_pxcore_config(self.px_cfg)
            messagebox.showinfo(
                "Configurações",
                "Diretório base salvo. Reinicie o aplicativo para aplicar as alterações.",
            )

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(0, 8))
        ttk.Button(btn_row, text="Salvar diretório base", command=save_base_dir).pack(side="left")
        ttk.Button(btn_row, text="📁 Abrir pasta", command=self.open_pxcore_folder).pack(
            side="left", padx=(6, 0)
        )

    # =========================
    # Impressoras
    # =========================
    def open_printers_dialog(self) -> None:
        printers: list[Printer] = load_printers()
        selected_key: dict[str, str | None] = {"value": None}

        win = tk.Toplevel(self)
        win.title("Gerenciar Impressoras")
        win.geometry("760x480")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        cols = ("display_name", "name", "speed", "jpg_dir", "jpg_filename", "notes")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
        for col, txt, w in [
            ("display_name", "Nome de exibição", 100),
            ("name", "Nome completo", 150),
            ("speed", "Velocidade (m/min)", 100),
            ("jpg_dir", "Pasta do JPG espelhado", 190),
            ("jpg_filename", "Nome do arquivo", 120),
            ("notes", "Observações", 120),
        ]:
            tree.heading(col, text=txt)
            tree.column(col, width=w, anchor="w")
        tree.pack(fill="both", expand=True, pady=(0, 10))

        form = ttk.Frame(frm)
        form.pack(fill="x")

        ttk.Label(form, text="Nome completo:").grid(row=0, column=0, sticky="w")
        var_name = tk.StringVar()
        ttk.Entry(form, textvariable=var_name, width=28).grid(row=0, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Nome de exibição (ex.: M1):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        var_display = tk.StringVar()
        ttk.Entry(form, textvariable=var_display, width=14).grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Velocidade (m/min):").grid(row=1, column=0, sticky="w")
        var_speed = tk.StringVar(value="1.50")
        ttk.Entry(form, textvariable=var_speed, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Observações:").grid(row=1, column=2, sticky="w", padx=(12, 0))
        var_notes = tk.StringVar()
        ttk.Entry(form, textvariable=var_notes, width=28).grid(row=1, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(form, text="Pasta do JPG espelhado:").grid(row=2, column=0, sticky="w", pady=(2, 0))
        var_jpg_dir = tk.StringVar()
        ttk.Entry(form, textvariable=var_jpg_dir, width=46).grid(
            row=2, column=1, columnspan=2, sticky="we", padx=6, pady=(2, 0)
        )

        def on_browse_jpg_dir() -> None:
            folder = filedialog.askdirectory(title="Pasta para salvar o JPG espelhado desta impressora")
            if folder:
                var_jpg_dir.set(folder)

        ttk.Button(form, text="Procurar…", command=on_browse_jpg_dir).grid(
            row=2, column=3, sticky="w", padx=6, pady=(2, 0)
        )

        ttk.Label(form, text="Nome do arquivo do JPG:").grid(row=3, column=0, sticky="w", pady=(2, 0))
        var_jpg_filename = tk.StringVar()
        ttk.Entry(form, textvariable=var_jpg_filename, width=28).grid(
            row=3, column=1, sticky="w", padx=6, pady=(2, 0)
        )
        ttk.Label(
            form,
            text="(opcionais — cada módulo decide se usa isso ou a pasta padrão)",
            foreground="gray",
        ).grid(row=4, column=1, columnspan=3, sticky="w", padx=6)

        def refresh_tree(select_key: str | None = None) -> None:
            tree.delete(*tree.get_children())
            for pr in printers:
                tree.insert(
                    "", "end", iid=pr.key,
                    values=(
                        pr.display_name, pr.name, f"{pr.speed_m_min:.2f}",
                        pr.jpg_output_dir, pr.jpg_output_filename, pr.notes,
                    ),
                )
            if select_key:
                tree.selection_set(select_key)

        def clear_form() -> None:
            selected_key["value"] = None
            var_name.set("")
            var_display.set("")
            var_speed.set("1.50")
            var_notes.set("")
            var_jpg_dir.set("")
            var_jpg_filename.set("")
            tree.selection_remove(*tree.selection())

        def on_select(_evt=None) -> None:
            sel = tree.selection()
            if not sel:
                return
            key = sel[0]
            pr = next((p for p in printers if p.key == key), None)
            if pr is None:
                return
            selected_key["value"] = pr.key
            var_name.set(pr.name)
            var_display.set(pr.display_name)
            var_speed.set(f"{pr.speed_m_min:.2f}")
            var_notes.set(pr.notes)
            var_jpg_dir.set(pr.jpg_output_dir)
            var_jpg_filename.set(pr.jpg_output_filename)

        tree.bind("<<TreeviewSelect>>", on_select)

        def on_save() -> None:
            nonlocal printers
            try:
                speed = float(var_speed.get().strip().replace(",", "."))
            except Exception:
                messagebox.showerror("Impressoras", "Velocidade inválida.")
                return

            try:
                printers = add_or_update_printer(
                    printers,
                    key=selected_key["value"],
                    name=var_name.get(),
                    display_name=var_display.get(),
                    speed_m_min=speed,
                    notes=var_notes.get().strip(),
                    jpg_output_dir=var_jpg_dir.get().strip(),
                    jpg_output_filename=var_jpg_filename.get().strip(),
                )
            except ValueError as e:
                messagebox.showerror("Impressoras", str(e))
                return

            save_printers(printers)
            new_key = selected_key["value"] or next(
                (p.key for p in printers if p.display_name == var_display.get().strip()), None
            )
            refresh_tree(select_key=new_key)
            selected_key["value"] = new_key

        def on_remove() -> None:
            nonlocal printers
            key = selected_key["value"]
            if not key:
                messagebox.showwarning("Impressoras", "Selecione uma impressora na lista.")
                return
            pr = next((p for p in printers if p.key == key), None)
            label = pr.display_name if pr else key
            if not messagebox.askyesno("Remover impressora", f"Remover a impressora '{label}'?"):
                return
            printers = remove_printer(printers, key)
            save_printers(printers)
            clear_form()
            refresh_tree()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Nova", command=clear_form).pack(side="left")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Remover", command=on_remove).pack(side="left", padx=6)
        ttk.Button(btns, text="Fechar", command=win.destroy).pack(side="right")

        refresh_tree()


def main() -> None:
    Nexor().mainloop()


if __name__ == "__main__":
    main()
