"""
Camada central de temas do Nexor.

Um único lugar define as cores/tokens de cada tema (extraídos do protótipo
HTML em Referencia/nexor-prototipo-download.html) e sabe como aplicá-los:
- aos estilos ttk (botões, treeviews, abas, campos, etc.)
- aos widgets tk "clássicos" (Listbox, Text, Canvas, Menu, Entry, Button)
  que não seguem ttk.Style sozinhos
- a QUALQUER Toplevel novo que seja aberto depois (diálogos dos módulos),
  sem precisar alterar o código desses diálogos.

Não há migração de dados aqui — é só aparência. Nenhuma função de negócio
(exportação, cálculo, banco) é tocada por este módulo.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Optional


@dataclass(frozen=True)
class ThemeSpec:
    key: str
    label: str
    scheme: str  # "light" ou "dark" — só informativo/preview
    bg: str
    panel: str
    text: str
    muted: str
    line: str
    soft: str
    brand: str
    brand_soft: str
    danger: str
    on_brand: str
    font_family: str = "Segoe UI"
    relief: str = "flat"       # "flat" (temas modernos) ou "raised" (XP/98)
    borderwidth: int = 1
    square: bool = False       # True = cantos retos (Win98), sem padding extra


# Tokens extraídos de Referencia/nexor-prototipo-download.html
# (--n-bg, --n-panel, --n-text, --n-muted, --n-line, --n-soft, --n-brand,
#  --n-brand-soft, --n-danger, --n-on-brand de cada [data-theme="..."]).
THEMES: dict[str, ThemeSpec] = {
    "dark": ThemeSpec(
        key="dark", label="Escuro", scheme="dark",
        bg="#11171e", panel="#1a232e", text="#e7edf5", muted="#9badc0",
        line="#303c49", soft="#222e3c", brand="#49d4c5", brand_soft="#173c39",
        danger="#ff9999", on_brand="#102622",
    ),
    "light": ThemeSpec(
        key="light", label="Claro", scheme="light",
        bg="#f4f6f9", panel="#ffffff", text="#172737", muted="#617083",
        line="#dce4ec", soft="#eef3f7", brand="#087b76", brand_soft="#e1f4ef",
        danger="#ac3434", on_brand="#ffffff",
    ),
    "mid": ThemeSpec(
        key="mid", label="Meio-termo", scheme="dark",
        bg="#323a43", panel="#3e4853", text="#f2f5f8", muted="#c2ccd7",
        line="#596674", soft="#4b5763", brand="#79e0d2", brand_soft="#354f50",
        danger="#ffb5ac", on_brand="#203d38",
    ),
    "dracula": ThemeSpec(
        key="dracula", label="Dracula", scheme="dark",
        bg="#282a36", panel="#30323f", text="#f8f8f2", muted="#b8bfdf",
        line="#4c4f65", soft="#44475a", brand="#bd93f9", brand_soft="#453858",
        danger="#ff7979", on_brand="#282a36",
    ),
    "nord": ThemeSpec(
        key="nord", label="Nord", scheme="dark",
        bg="#2e3440", panel="#3b4252", text="#eceff4", muted="#b9c7d7",
        line="#566175", soft="#434c5e", brand="#88c0d0", brand_soft="#344f5b",
        danger="#f3a9b1", on_brand="#23353f",
    ),
    "solarized": ThemeSpec(
        key="solarized", label="Solarized", scheme="light",
        bg="#eee8d5", panel="#fdf6e3", text="#34494f", muted="#586e75",
        line="#d9d2bd", soft="#ece5cd", brand="#006f87", brand_soft="#dce9de",
        danger="#b62d27", on_brand="#fdf6e3",
    ),
    "xp": ThemeSpec(
        key="xp", label="Windows XP", scheme="light",
        bg="#d9e5f7", panel="#ece9d8", text="#17213a", muted="#4e5870",
        line="#a4b6cf", soft="#e0e7f1", brand="#154ab4", brand_soft="#cbdcf4",
        danger="#ad2424", on_brand="#ffffff",
        font_family="Tahoma", relief="raised", borderwidth=2,
    ),
    "win98": ThemeSpec(
        key="win98", label="Windows 98", scheme="light",
        bg="#008080", panel="#c0c0c0", text="#111111", muted="#3e3e3e",
        line="#808080", soft="#d4d0c8", brand="#000080", brand_soft="#d8d8e9",
        danger="#8b0000", on_brand="#ffffff",
        font_family="Tahoma", relief="raised", borderwidth=2, square=True,
    ),
}

DEFAULT_THEME = "dark"

_current_key: str = DEFAULT_THEME
_listeners: list[Callable[[str], None]] = []
_patched = False


def theme_keys_ordered() -> list[str]:
    """Ordem de exibição no seletor (Configurações → Aparência)."""
    return ["dark", "light", "mid", "dracula", "nord", "solarized", "xp", "win98"]


def get_spec(key: Optional[str] = None) -> ThemeSpec:
    return THEMES.get(key or _current_key, THEMES[DEFAULT_THEME])


def current_key() -> str:
    return _current_key


def _configure_ttk(style: ttk.Style, spec: ThemeSpec) -> None:
    style.theme_use("clam")

    base_font = (spec.font_family, 9)
    corner = 0 if spec.square else 2

    style.configure(".", background=spec.bg, foreground=spec.text, font=base_font)
    style.configure("TFrame", background=spec.bg)
    style.configure(
        "TLabelframe", background=spec.panel, foreground=spec.text,
        bordercolor=spec.line, relief=spec.relief, borderwidth=spec.borderwidth,
        padding=0,
    )
    style.configure(
        "TLabelframe.Label", background=spec.panel, foreground=spec.text,
        font=(spec.font_family, 10, "bold"), padding=(4, 2),
    )
    style.configure(
        "Card.TLabelframe", background=spec.panel, foreground=spec.text,
        bordercolor=spec.line, relief=spec.relief, borderwidth=spec.borderwidth,
    )
    style.configure(
        "Card.TLabelframe.Label", background=spec.panel, foreground=spec.text,
        font=(spec.font_family, 10, "bold"), padding=(8, 2),
    )
    style.configure("Panel.TFrame", background=spec.panel)
    style.configure("Soft.TFrame", background=spec.soft)
    style.configure("Panel.TLabel", background=spec.panel, foreground=spec.text)
    style.configure("PanelMuted.TLabel", background=spec.panel, foreground=spec.muted)
    style.configure(
        "Section.TLabel", background=spec.bg, foreground=spec.muted,
        font=(spec.font_family, 9, "bold"), padding=(0, 0, 0, 5),
    )
    style.configure("TLabel", background=spec.bg, foreground=spec.text)
    style.configure("Muted.TLabel", background=spec.bg, foreground=spec.muted)
    style.configure("PageTitle.TLabel", background=spec.bg, foreground=spec.text,
                    font=(spec.font_family, 18, "bold"))
    style.configure("PageSubtitle.TLabel", background=spec.bg, foreground=spec.muted,
                    font=(spec.font_family, 10))
    style.configure("Status.TFrame", background=spec.brand_soft)
    style.configure("Status.TLabel", background=spec.brand_soft, foreground=spec.brand,
                    font=(spec.font_family, 9))
    style.configure("Accent.TButton", background=spec.brand, foreground=spec.on_brand,
                    bordercolor=spec.brand, relief=spec.relief,
                    borderwidth=spec.borderwidth, padding=(12, 7))
    style.map("Accent.TButton", background=[("active", spec.brand), ("pressed", spec.brand)])
    style.configure("Badge.TLabel", background=spec.soft, foreground=spec.muted,
                    padding=(8, 3), font=(spec.font_family, 8))
    style.configure("Logo.TLabel", background=spec.brand, foreground=spec.on_brand,
                    padding=(5, 3), font=(spec.font_family, 12, "bold"))
    style.configure("TSeparator", background=spec.line)

    style.configure(
        "TButton", background=spec.panel, foreground=spec.text,
        bordercolor=spec.line, relief=spec.relief, borderwidth=spec.borderwidth,
        padding=(8, 4),
    )
    style.map(
        "TButton",
        background=[("active", spec.brand_soft), ("pressed", spec.brand_soft)],
        foreground=[("disabled", spec.muted)],
    )

    style.configure(
        "TEntry", fieldbackground=spec.panel, foreground=spec.text,
        bordercolor=spec.line, insertcolor=spec.text,
    )
    style.configure(
        "TCombobox", fieldbackground=spec.panel, foreground=spec.text,
        background=spec.panel, bordercolor=spec.line, arrowcolor=spec.text,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", spec.panel)],
        foreground=[("readonly", spec.text)],
    )
    style.configure("TSpinbox", fieldbackground=spec.panel, foreground=spec.text, bordercolor=spec.line)

    style.configure("TCheckbutton", background=spec.bg, foreground=spec.text)
    style.map("TCheckbutton", background=[("active", spec.bg)])
    style.configure("TRadiobutton", background=spec.bg, foreground=spec.text)
    style.map("TRadiobutton", background=[("active", spec.bg)])

    style.configure(
        "TNotebook", background=spec.bg, bordercolor=spec.line,
        tabmargins=(0, 0, 0, 0),
    )
    style.configure(
        "TNotebook.Tab", background=spec.soft, foreground=spec.muted,
        padding=(12, 8), bordercolor=spec.line,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", spec.panel)],
        foreground=[("selected", spec.text)],
    )

    style.configure(
        "Treeview", background=spec.panel, fieldbackground=spec.panel,
        foreground=spec.text, bordercolor=spec.line, rowheight=30,
    )
    style.configure(
        "Treeview.Heading", background=spec.soft, foreground=spec.muted,
        bordercolor=spec.line, relief="flat", padding=(8, 8),
    )
    style.map(
        "Treeview",
        background=[("selected", spec.brand)],
        foreground=[("selected", spec.on_brand)],
    )

    style.configure(
        "TScrollbar", background=spec.soft, troughcolor=spec.bg,
        bordercolor=spec.line, arrowcolor=spec.text,
    )
    style.configure("TPanedwindow", background=spec.bg)

    # Estilos próprios do menu lateral do Nexor (ver Nexor.py).
    style.configure(
        "Kicker.TLabel", background=spec.bg, foreground=spec.muted,
        font=(spec.font_family, 8, "bold"),
    )
    style.configure(
        "Nav.TButton", background=spec.bg, foreground=spec.text,
        anchor="w", padding=(10, 8), relief="flat", borderwidth=0,
        font=base_font,
    )
    style.map(
        "Nav.TButton",
        background=[("active", spec.soft)],
    )
    style.configure(
        "NavSelected.TButton", background=spec.brand_soft, foreground=spec.text,
        anchor="w", padding=(10, 8), relief="flat", borderwidth=0,
        font=(spec.font_family, 9, "bold"),
    )
    style.map(
        "NavSelected.TButton",
        background=[("active", spec.brand_soft)],
    )
    style.configure(
        "Tool.TButton", background=spec.bg, foreground=spec.muted,
        anchor="w", padding=(10, 6), relief="flat", borderwidth=0,
        font=base_font,
    )
    style.map(
        "Tool.TButton",
        background=[("active", spec.soft)],
    )


_TK_WIDGET_COLORS: dict[str, Callable[[tk.Widget, ThemeSpec], None]] = {}


def _safe_configure(widget: tk.Misc, **kwargs) -> None:
    try:
        widget.configure(**kwargs)
    except tk.TclError:
        pass


def _recolor_widget(widget: tk.Misc, spec: ThemeSpec) -> None:
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return

    if cls in ("Toplevel", "Tk"):
        _safe_configure(widget, background=spec.bg)
    elif cls == "Frame":
        _safe_configure(widget, background=spec.bg)
    elif cls == "Label":
        _safe_configure(widget, background=spec.bg, foreground=spec.text)
    elif cls == "Listbox":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            selectbackground=spec.brand, selectforeground=spec.on_brand,
            highlightbackground=spec.line, highlightcolor=spec.brand,
        )
    elif cls == "Text":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            insertbackground=spec.text, selectbackground=spec.brand,
            selectforeground=spec.on_brand, highlightbackground=spec.line,
        )
    elif cls == "Canvas":
        _safe_configure(widget, background=spec.bg, highlightbackground=spec.line)
    elif cls == "Menu":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            activebackground=spec.brand, activeforeground=spec.on_brand,
        )
    elif cls == "Button":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            activebackground=spec.brand_soft, activeforeground=spec.text,
        )
    elif cls == "Entry":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            insertbackground=spec.text,
        )
    elif cls == "Checkbutton":
        _safe_configure(widget, background=spec.bg, foreground=spec.text, selectcolor=spec.panel)
    elif cls == "Radiobutton":
        _safe_configure(widget, background=spec.bg, foreground=spec.text, selectcolor=spec.panel)
    elif cls == "Labelframe":
        _safe_configure(widget, background=spec.bg, foreground=spec.text)

    for child in widget.winfo_children():
        _recolor_widget(child, spec)


def apply_theme(root: tk.Misc, key: str) -> None:
    """Aplica `key` em todo o app: estilos ttk + widgets tk clássicos, em
    `root` e em qualquer Toplevel já aberto (a varredura é recursiva e
    alcança diálogos abertos normalmente). Também memoriza `key` como tema
    atual, usado em diálogos abertos depois (ver `_install_toplevel_autotheme`)."""
    global _current_key
    spec = get_spec(key)
    _current_key = spec.key

    style = ttk.Style(root)
    _configure_ttk(style, spec)
    _recolor_widget(root, spec)

    for cb in list(_listeners):
        try:
            cb(spec.key)
        except Exception:
            pass


def on_theme_changed(callback: Callable[[str], None]) -> None:
    """Registra um callback(key) chamado toda vez que o tema muda — usado
    por telas que precisam recolorir algo fora do alcance do walker padrão
    (ex.: cores calculadas dinamicamente)."""
    _listeners.append(callback)


def install_toplevel_autotheme() -> None:
    """Faz qualquer novo tk.Toplevel() já nascer com o tema atual aplicado,
    sem precisar alterar o código de cada diálogo dos módulos. Idempotente."""
    global _patched
    if _patched:
        return
    _patched = True

    orig_init = tk.Toplevel.__init__

    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)

        def _apply():
            try:
                _recolor_widget(self, get_spec(_current_key))
            except Exception:
                pass

        try:
            self.after_idle(_apply)
            # Os diálogos do Nexor são modais no protótipo. Tkinter não tem
            # overlay nativo, mas transient + grab + foco reproduzem a mesma
            # ordem de interação sem esconder ou substituir os callbacks.
            owner = getattr(self, "master", None)
            if owner is not None:
                self.transient(owner.winfo_toplevel())
            try:
                self.grab_set()
                self.focus_force()
            except tk.TclError:
                # O diálogo ainda pode ser criado em ambientes sem janela
                # mapeada (smoke tests e inicialização muito cedo).
                pass
            self.bind("<Escape>", lambda _event: self.destroy(), add="+")
            # Alguns diálogos montam conteúdo em callbacks posteriores ao
            # construtor. O evento de mapeamento reaplica os tokens sem
            # substituir callbacks nem recriar a janela.
            self.bind("<Map>", lambda _event: _apply(), add="+")
        except Exception:
            pass

    tk.Toplevel.__init__ = patched_init
