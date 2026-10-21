from __future__ import annotations

import importlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.version import __version__
from core.config import load_config as load_pxcore_config, save_config as save_pxcore_config
from core import theme
from core.ui import card, dialog_header, page_heading, page_scroll_container, status_bar
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

SETTINGS_TITLE = "Configurações"


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
        self.geometry("1280x800")
        self.minsize(980, 600)

        self._pages: dict[str, ttk.Frame] = {}
        self._page_uis: dict[str, object] = {}
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._theme_buttons: dict[str, ttk.Button] = {}
        self.current_module: str | None = None
        self._status_var = tk.StringVar(value="Pronto · Nexor carregado")

        # Tema: aplica o salvo (ou o padrão) e garante que diálogos novos,
        # de qualquer módulo, já nasçam com o tema atual aplicado.
        theme.install_toplevel_autotheme()
        theme.apply_theme(self, getattr(self.px_cfg, "theme_name", theme.DEFAULT_THEME))
        # Mantém a grade de temas coerente mesmo quando o tema é aplicado por
        # outro caminho que não o clique no cartão.
        theme.on_theme_changed(lambda _key: self._mark_active_theme())

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
        # Estilos "Nav.TButton"/"NavSelected.TButton"/"Tool.TButton"/
        # "Kicker.TLabel" são configurados centralmente por core/theme.py
        # (já aplicados pela chamada a theme.apply_theme em __init__).
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        # Menu lateral sobre --n-panel, como .nx-side do protótipo.
        sidebar = ttk.Frame(container, width=202, padding=(14, 24), style="Panel.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        logo_row = ttk.Frame(sidebar, style="Panel.TFrame", padding=(10, 0))
        logo_row.pack(fill="x", pady=(0, 28))
        ttk.Label(logo_row, text="N", style="Logo.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(logo_row, text="nexor.", style="SideLogo.TLabel").pack(side="left")

        ttk.Label(sidebar, text="PRODUÇÃO TÊXTIL", style="Kicker.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        for title, _module_path in MODULES:
            btn = ttk.Button(
                sidebar, text=title, style="Nav.TButton",
                command=lambda t=title: self.load_module(t),
            )
            btn.pack(fill="x", pady=(0, 6))
            self._nav_buttons[title] = btn

        ttk.Label(sidebar, text="GERENCIAMENTO", style="Kicker.TLabel").pack(
            anchor="w", pady=(22, 8)
        )
        for text, command in (
            ("Impressoras", self.open_printers_dialog),
            ("Tecidos", self.open_fabrics_shortcut),
            ("Pedaços de tecido", self.open_scraps_shortcut),
        ):
            ttk.Button(sidebar, text=text, style="Nav.TButton", command=command).pack(
                fill="x", pady=(0, 6)
            )
        settings_btn = ttk.Button(
            sidebar, text="Configurações", style="Nav.TButton",
            command=lambda: self.load_module(SETTINGS_TITLE),
        )
        settings_btn.pack(fill="x", pady=(0, 6))
        self._nav_buttons[SETTINGS_TITLE] = settings_btn

        ttk.Separator(container, orient="vertical").pack(side="left", fill="y")

        content_wrap = ttk.Frame(container)
        content_wrap.pack(side="left", fill="both", expand=True)

        header = ttk.Frame(content_wrap, padding=(26, 16), style="Top.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Produção  /", style="TopMuted.TLabel").pack(side="left")
        self._breadcrumb_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._breadcrumb_var, style="Top.TLabel").pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(header, text="Produção · ambiente local", style="Badge.TLabel").pack(side="right")
        ttk.Separator(content_wrap).pack(fill="x")

        # A barra de status precisa ser empacotada antes do conteúdo: com o
        # conteúdo em side="left"+expand, ela sobrava só numa fresta à direita.
        status_bar(content_wrap, self._status_var).pack(side="bottom", fill="x")
        ttk.Separator(content_wrap).pack(side="bottom", fill="x")
        self.content = ttk.Frame(content_wrap)
        self.content.pack(side="top", fill="both", expand=True)

    def _ensure_module_built(self, title: str) -> None:
        """Garante que a página exista em self._pages/self._page_uis, sem
        trocar a página visível — usado pelos atalhos de Tecidos/Pedaços de
        tecido, que precisam da UI do Planejador montada só para acessar seus
        diálogos, não para navegar até lá."""
        if title in self._pages:
            return
        page = ttk.Frame(self.content)
        if title == SETTINGS_TITLE:
            self._build_settings_page(page)
        else:
            module_path = dict(MODULES).get(title)
            if module_path is None:
                messagebox.showerror("Nexor", f"Módulo desconhecido: {title}")
                return
            self._build_module_page(page, title, module_path)
        self._pages[title] = page
        # A página é construída depois da aplicação inicial do tema.
        # Reaplicar aqui é essencial para widgets Tk clássicos (Text,
        # Listbox e Canvas), que não herdam ttk.Style automaticamente.
        theme.apply_theme(self, theme.current_key())

    def load_module(self, title: str) -> None:
        self._ensure_module_built(title)

        if self.current_module is not None and self.current_module in self._pages:
            self._pages[self.current_module].pack_forget()
            if self.current_module in self._nav_buttons:
                self._nav_buttons[self.current_module].configure(style="Nav.TButton")

        self._pages[title].pack(fill="both", expand=True)
        if title in self._nav_buttons:
            self._nav_buttons[title].configure(style="NavSelected.TButton")
        self.current_module = title
        self._breadcrumb_var.set(title)
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
            if isinstance(ui, tk.Widget) and not ui.winfo_manager():
                ui.pack(fill="both", expand=True)
            self._page_uis[title] = ui
        except Exception as e:
            self._render_error(page, f"Falha ao montar UI de {title}:\n\n{type(e).__name__}: {e}")

    def _render_error(self, parent: ttk.Frame, text: str) -> None:
        t = tk.Text(parent, wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)

    # =========================
    # Atalhos pro Planejador (Tecidos / Pedaços de tecido)
    # =========================
    def open_fabrics_shortcut(self) -> None:
        self._ensure_module_built("Planejador")
        hook = getattr(self._page_uis.get("Planejador"), "open_fabrics_dialog", None)
        if callable(hook):
            hook()
        else:
            messagebox.showerror("Tecidos", "Não foi possível abrir o cadastro de tecidos.")

    def open_scraps_shortcut(self) -> None:
        self._ensure_module_built("Planejador")
        hook = getattr(self._page_uis.get("Planejador"), "open_scraps_dialog", None)
        if callable(hook):
            hook()
        else:
            messagebox.showerror("Pedaços de tecido", "Não foi possível abrir o cadastro de pedaços.")

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
        """Mantido por compatibilidade (menu "Configurações" → "Abrir
        Configurações") — agora navega pra página em vez de abrir um popup."""
        self.load_module(SETTINGS_TITLE)

    def _build_settings_page(self, page: ttk.Frame) -> None:
        if self.px_cfg is None:
            self._render_error(page, "Config do PXCore não carregou.")
            return

        # A grade de temas com prévias empurra os demais cartões para baixo
        # da dobra em 800 px; a página rola como Planejador e Operação.
        outer, canvas = page_scroll_container(page)
        canvas.master.pack(fill="both", expand=True)

        page_heading(outer, "Configurações",
                     "Aparência, pastas, cadastros e padrões de cada módulo.").pack(fill="x")

        # Aparência vem primeiro no protótipo: as escolhas ficam visíveis sem
        # obrigar o usuário a atravessar o formulário de diretório.
        self._build_appearance_box(outer)

        # ---- Diretório de trabalho ----
        base_box = card(outer, "Diretório de trabalho", padding=14)
        base_box.pack(fill="x", pady=(0, 12))

        ttk.Label(base_box, text="Diretório base do PXCore:").pack(anchor="w")
        base_var = tk.StringVar(value=str(getattr(self.px_cfg, "base_dir", "")))
        base_row = ttk.Frame(base_box)
        base_row.pack(fill="x", pady=(4, 2))
        ttk.Entry(base_row, textvariable=base_var).pack(side="left", fill="x", expand=True)

        def browse_base_dir() -> None:
            chosen = filedialog.askdirectory(title="Selecionar diretório base do PXCore")
            if chosen:
                base_var.set(chosen)

        ttk.Button(base_row, text="Procurar…", command=browse_base_dir).pack(side="left", padx=(6, 0))

        ttk.Label(
            base_box,
            text=(
                "Para usar o mesmo banco de dados (Registros, números sequenciais\n"
                "de rolo) e as mesmas pastas de PDF/JPG em vários computadores, aponte\n"
                "todos eles para a mesma pasta de rede compartilhada aqui."
            ),
            justify="left",
            style="Muted.TLabel",
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

        btn_row = ttk.Frame(base_box)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Salvar diretório base", command=save_base_dir).pack(side="left")
        ttk.Button(btn_row, text="📁 Abrir pasta", command=self.open_pxcore_folder).pack(
            side="left", padx=(6, 0)
        )

        # Cadastros de Impressoras/Tecidos/Pedaços de tecido já ficam sempre
        # visíveis no menu lateral ("Gerenciamento") — não duplica os cartões
        # aqui, só aponta pra lá.
        ttk.Label(
            outer,
            text="Cadastros de Impressoras, Tecidos e Pedaços de tecido: menu lateral → Gerenciamento.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 12))

        # ---- Configurações fixas dos módulos (antes espalhadas nas telas) ----
        try:
            from modules import configuracoes
        except Exception as e:  # noqa: BLE001
            self._render_error(outer, f"Falha ao carregar configurações dos módulos:\n\n{type(e).__name__}: {e}")
            return
        section_boxes = []
        for build in (
            configuracoes.build_print_types_section,
            configuracoes.build_operacao_section,
            configuracoes.build_planejador_section,
            configuracoes.build_registros_section,
        ):
            section_box = build(outer, self._on_module_settings_saved)
            section_box.pack(fill="x", pady=(12, 0))
            section_boxes.append(section_box)

        save_all_row = ttk.Frame(outer)
        save_all_row.pack(fill="x", pady=(16, 24))
        ttk.Button(
            save_all_row,
            text="Salvar todas as configurações",
            style="Accent.TButton",
            command=lambda: self._save_all_settings(section_boxes),
        ).pack(anchor="w")

    def _save_all_settings(self, section_boxes: list) -> None:
        """Salva de uma vez as seções de Configurações que têm algo a
        persistir (Tipos de impressão, Operação, Planejador — Registros só
        tem a ação de reclassificar, que já age na hora). Cada seção valida
        os próprios campos e avisa o erro específico; esta função só agrega
        o resultado final."""
        any_section = False
        all_ok = True
        for section_box in section_boxes:
            save_fn = getattr(section_box, "save", None)
            if not callable(save_fn):
                continue
            any_section = True
            try:
                if save_fn() is False:
                    all_ok = False
            except Exception as e:  # noqa: BLE001
                all_ok = False
                messagebox.showerror(
                    "Configurações", f"Falha ao salvar uma das seções.\n\n{type(e).__name__}: {e}"
                )

        if not any_section:
            return

        if all_ok:
            self._status_var.set("Todas as configurações foram salvas")
            messagebox.showinfo("Configurações", "Todas as configurações foram salvas.")
        else:
            messagebox.showwarning(
                "Configurações",
                "Algumas seções não foram salvas — corrija o que foi indicado e clique em "
                "\"Salvar todas as configurações\" de novo.",
            )

    def _on_module_settings_saved(self, module_title: str) -> None:
        """Repassa a configuração nova para a página já aberta, sem reiniciar."""
        hook = getattr(self._page_uis.get(module_title), "reload_settings", None)
        if callable(hook):
            try:
                hook()
            except Exception as e:  # noqa: BLE001
                messagebox.showwarning(
                    module_title,
                    f"Configuração salva, mas a tela aberta não recarregou.\n\n{type(e).__name__}: {e}",
                )
        self._status_var.set(f"Configurações de {module_title} salvas")

    def _build_appearance_box(self, outer: ttk.Frame) -> None:
        box = card(outer, "Aparência", padding=14)
        box.pack(fill="x", pady=(0, 12))

        self._theme_current_var = tk.StringVar(value="")
        ttk.Label(box, textvariable=self._theme_current_var, style="Muted.TLabel").pack(
            anchor="w", pady=(0, 6)
        )

        # Escolha de tema é ocasional (normalmente só uma vez) — fica
        # recolhida por padrão pra não empurrar o resto da página pra baixo.
        self._theme_grid_state = {"open": False}
        grid_wrap = ttk.Frame(box)

        def toggle_theme_grid() -> None:
            self._theme_grid_state["open"] = not self._theme_grid_state["open"]
            if self._theme_grid_state["open"]:
                grid_wrap.pack(fill="x", pady=(4, 0))
                btn_toggle_theme.configure(text="Mudar tema ▾")
            else:
                grid_wrap.pack_forget()
                btn_toggle_theme.configure(text="Mudar tema ▸")

        btn_toggle_theme = ttk.Button(box, text="Mudar tema ▸", command=toggle_theme_grid)
        btn_toggle_theme.pack(anchor="w")

        grid = ttk.Frame(grid_wrap)
        grid.pack(fill="x", pady=(10, 0))

        self._theme_check_vars: dict[str, tk.StringVar] = {}
        for i, key in enumerate(theme.theme_keys_for_picker()):
            spec = theme.get_spec(key)
            # Cartão = .nx-theme-choice; a borda vira highlight do Frame para
            # poder ficar com 2 px da cor de destaque quando ativo.
            choice = tk.Frame(grid, highlightthickness=1, borderwidth=0, cursor="hand2")
            choice.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0, 14), pady=(0, 14))

            preview = tk.Canvas(choice, height=74, highlightthickness=0, borderwidth=0, cursor="hand2")
            preview._nx_static = True  # cores do tema exibido, não do tema ativo
            preview.pack(fill="x", padx=9, pady=(9, 9))
            preview.bind("<Configure>", lambda e, c=preview, s=spec: self._draw_theme_preview(c, s))

            label_row = ttk.Frame(choice)
            label_row.pack(fill="x", padx=9)
            name = ttk.Label(label_row, text=spec.label, style="PanelStrong.TLabel")
            name.pack(side="left")
            check_var = tk.StringVar(value="")
            check = ttk.Label(label_row, textvariable=check_var, style="Panel.TLabel")
            check.pack(side="right")
            self._theme_check_vars[key] = check_var
            desc = ttk.Label(choice, text=spec.description, style="PanelMuted.TLabel")
            desc.pack(anchor="w", padx=9, pady=(2, 9))

            for widget in (choice, preview, label_row, name, check, desc):
                widget.bind("<Button-1>", lambda _e, k=key: self._select_theme(k))
            self._theme_buttons[key] = choice

        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="theme")

        ttk.Label(
            grid_wrap, text="Aplicação imediata em todas as telas. A escolha fica salva neste computador.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        self._mark_active_theme()

    @staticmethod
    def _draw_theme_preview(canvas: tk.Canvas, spec: "theme.ThemeSpec") -> None:
        w = max(canvas.winfo_width(), 60)
        h = 74
        side = int(w * 0.25)
        canvas.delete("all")
        canvas.configure(background=spec.bg)
        canvas.create_rectangle(0, 0, side, h, fill=spec.panel, outline="")
        canvas.create_rectangle(10, 10, side - 10, 13, fill=spec.brand, outline="")
        for y in (21, 29, 37):
            canvas.create_rectangle(10, y, side - 10, y + 2, fill=spec.muted, outline="")
        canvas.create_rectangle(side + 10, 10, side + int((w - side) * 0.55), 13,
                                fill=spec.text, outline="")
        canvas.create_rectangle(side + 10, 21, w - 10, 39, fill=spec.panel, outline="")
        canvas.create_rectangle(w - 10 - int((w - side) * 0.22), 58, w - 10, 63,
                                fill=spec.brand, outline="")

    def _select_theme(self, key: str) -> None:
        theme.apply_theme(self, key)
        if self.px_cfg is not None:
            self.px_cfg.theme_name = key
            save_pxcore_config(self.px_cfg)
        self._mark_active_theme()

    def _mark_active_theme(self) -> None:
        if not self._theme_buttons:
            return
        active = theme.current_key()
        current = theme.get_spec(active)
        if hasattr(self, "_theme_current_var"):
            self._theme_current_var.set(f"Tema atual: {current.label}")
        for key, choice in self._theme_buttons.items():
            is_active = key == active
            choice.configure(
                background=current.panel,
                highlightthickness=2 if is_active else 1,
                highlightbackground=current.brand if is_active else current.line,
                highlightcolor=current.brand if is_active else current.line,
            )
            self._theme_check_vars[key].set("✓" if is_active else "")

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
        dialog_header(frm, "Impressoras", "Máquinas disponíveis e destino dos JPGs espelhados.").pack(fill="x")

        cols = ("display_name", "name", "speed", "jpg_dir", "jpg_filename", "sec_log", "notes")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=8)
        for col, txt, w in [
            ("display_name", "Nome de exibição", 100),
            ("name", "Nome completo", 150),
            ("speed", "Velocidade (m/min)", 100),
            ("jpg_dir", "Pasta do JPG espelhado", 190),
            ("jpg_filename", "Nome do arquivo", 120),
            ("sec_log", "Log adicional", 110),
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
            style="Muted.TLabel",
        ).grid(row=4, column=1, columnspan=3, sticky="w", padx=6)

        var_sec_enabled = tk.BooleanVar(value=False)
        var_sec_folder = tk.StringVar()

        ttk.Checkbutton(
            form, text="Log adicional (cruza com outro log pra confirmar a impressão real)",
            variable=var_sec_enabled,
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Label(form, text="Pasta do log adicional:").grid(row=6, column=0, sticky="w", pady=(2, 0))
        ent_sec_folder = ttk.Entry(form, textvariable=var_sec_folder, width=46)
        ent_sec_folder.grid(row=6, column=1, columnspan=2, sticky="we", padx=6, pady=(2, 0))

        def on_browse_sec_folder() -> None:
            folder = filedialog.askdirectory(title="Pasta do log adicional (log diário da impressão real)")
            if folder:
                var_sec_folder.set(folder)

        btn_sec_folder = ttk.Button(form, text="Procurar…", command=on_browse_sec_folder)
        btn_sec_folder.grid(row=6, column=3, sticky="w", padx=6, pady=(2, 0))

        def _update_sec_folder_state(*_a) -> None:
            state = "normal" if var_sec_enabled.get() else "disabled"
            ent_sec_folder.configure(state=state)
            btn_sec_folder.configure(state=state)

        var_sec_enabled.trace_add("write", _update_sec_folder_state)
        _update_sec_folder_state()

        def refresh_tree(select_key: str | None = None) -> None:
            tree.delete(*tree.get_children())
            for pr in printers:
                tree.insert(
                    "", "end", iid=pr.key,
                    values=(
                        pr.display_name, pr.name, f"{pr.speed_m_min:.2f}",
                        pr.jpg_output_dir, pr.jpg_output_filename,
                        "Sim" if pr.secondary_log_enabled else "Não",
                        pr.notes,
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
            var_sec_enabled.set(False)
            var_sec_folder.set("")
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
            var_sec_enabled.set(pr.secondary_log_enabled)
            var_sec_folder.set(pr.secondary_log_folder)

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
                    secondary_log_enabled=bool(var_sec_enabled.get()),
                    secondary_log_folder=var_sec_folder.get().strip(),
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
