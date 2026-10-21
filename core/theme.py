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
    # Sobrescritas por tema do protótipo (vazio = derivado dos tokens base).
    field_bg: str = ""         # input/select (XP/98 usam branco)
    table_bg: str = ""         # corpo da tabela (98 usa branco)
    heading_bg: str = ""       # cabeçalho da tabela (th usa --n-bg)
    button_bg: str = ""
    button_border: str = ""
    bevel_light: str = ""      # relevo XP/98 (claro/escuro)
    bevel_dark: str = ""
    top_bg: str = ""           # barra superior (XP/98 têm faixa azul)
    top_fg: str = ""
    top_muted: str = ""
    chip_bg: str = ""
    chip_fg: str = ""
    primary_bg: str = ""       # botão principal (XP é verde, 98 é cinza)
    primary_fg: str = ""
    nav_fg: str = ""
    nav_active_bg: str = ""
    nav_active_fg: str = ""
    status_bg: str = ""
    status_fg: str = ""
    tab_bg: str = ""           # abas XP/98 são caixas, não sublinhado
    tab_active_bg: str = ""
    card_title_fg: str = ""
    description: str = ""


def tok(spec: "ThemeSpec", name: str) -> str:
    """Valor efetivo de um token, aplicando os padrões do protótipo."""
    value = getattr(spec, name, "")
    if value:
        return value
    defaults = {
        "field_bg": spec.panel,
        "table_bg": spec.panel,
        "heading_bg": spec.bg,
        "button_bg": spec.panel,
        "button_border": spec.line,
        "bevel_light": "",
        "bevel_dark": "",
        "top_bg": spec.panel,
        "top_fg": spec.text,
        "top_muted": spec.muted,
        "chip_bg": spec.soft,
        "chip_fg": spec.muted,
        "primary_bg": spec.brand,
        "primary_fg": spec.on_brand,
        "nav_fg": spec.muted,
        "nav_active_bg": spec.brand_soft,
        "nav_active_fg": spec.brand,
        "status_bg": spec.brand_soft,
        "status_fg": spec.brand,
        "tab_bg": spec.panel,
        "tab_active_bg": spec.panel,
        "card_title_fg": spec.text,
    }
    return defaults.get(name, "")


# Tokens extraídos de Referencia/nexor-prototipo-download.html
# (--n-bg, --n-panel, --n-text, --n-muted, --n-line, --n-soft, --n-brand,
#  --n-brand-soft, --n-danger, --n-on-brand de cada [data-theme="..."]).
THEMES: dict[str, ThemeSpec] = {
    "dark": ThemeSpec(
        key="dark", label="Escuro", scheme="dark",
        bg="#11171e", panel="#1a232e", text="#e7edf5", muted="#9badc0",
        line="#303c49", soft="#222e3c", brand="#49d4c5", brand_soft="#173c39",
        danger="#ff9999", on_brand="#102622",
        description="Original · grafite e verde água",
    ),
    "light": ThemeSpec(
        key="light", label="Claro", scheme="light",
        bg="#f4f6f9", panel="#ffffff", text="#172737", muted="#617083",
        line="#dce4ec", soft="#eef3f7", brand="#087b76", brand_soft="#e1f4ef",
        danger="#ac3434", on_brand="#ffffff",
        description="Superfícies claras e contraste nítido",
    ),
    "mid": ThemeSpec(
        key="mid", label="Meio-termo", scheme="dark",
        bg="#323a43", panel="#3e4853", text="#f2f5f8", muted="#c2ccd7",
        line="#596674", soft="#4b5763", brand="#79e0d2", brand_soft="#354f50",
        danger="#ffb5ac", on_brand="#203d38",
        description="Cinza médio · menos diferença de brilho",
    ),
    "dracula": ThemeSpec(
        key="dracula", label="Dracula", scheme="dark",
        bg="#282a36", panel="#30323f", text="#f8f8f2", muted="#b8bfdf",
        line="#4c4f65", soft="#44475a", brand="#bd93f9", brand_soft="#453858",
        danger="#ff7979", on_brand="#282a36",
        description="Inspirado no VS Code · roxo e grafite",
    ),
    "nord": ThemeSpec(
        key="nord", label="Nord", scheme="dark",
        bg="#2e3440", panel="#3b4252", text="#eceff4", muted="#b9c7d7",
        line="#566175", soft="#434c5e", brand="#88c0d0", brand_soft="#344f5b",
        danger="#f3a9b1", on_brand="#23353f",
        description="Azul polar · frio e discreto",
    ),
    "solarized": ThemeSpec(
        key="solarized", label="Solarized", scheme="light",
        bg="#eee8d5", panel="#fdf6e3", text="#34494f", muted="#586e75",
        line="#d9d2bd", soft="#ece5cd", brand="#006f87", brand_soft="#dce9de",
        danger="#b62d27", on_brand="#fdf6e3",
        description="Creme quente · destaque azul petróleo",
    ),
    # XP/98: gradientes do protótipo viram a cor sólida dominante de cada
    # gradiente, já que ttk não desenha gradiente.
    "xp": ThemeSpec(
        key="xp", label="Windows XP", scheme="light",
        bg="#d9e5f7", panel="#ece9d8", text="#17213a", muted="#4e5870",
        line="#a4b6cf", soft="#e0e7f1", brand="#154ab4", brand_soft="#cbdcf4",
        danger="#ad2424", on_brand="#ffffff",
        font_family="Tahoma", relief="raised", borderwidth=2,
        field_bg="#ffffff", heading_bg="#e6e1d2", button_bg="#f6f4eb",
        button_border="#6a7e9c", bevel_light="#ffffff", bevel_dark="#d5ccb4",
        top_bg="#0052d6", top_fg="#ffffff", top_muted="#eaf2ff",
        chip_bg="#174eaa", chip_fg="#ffffff",
        primary_bg="#328e2d", primary_fg="#ffffff",
        nav_fg="#4e5870", nav_active_bg="#1c5fcb", nav_active_fg="#ffffff",
        status_bg="#ece9d8", status_fg="#374463",
        tab_bg="#e3dfd3", tab_active_bg="#ffffff", card_title_fg="#153e80",
        description="Luna · azul vivo, creme e botão verde",
    ),
    "win98": ThemeSpec(
        key="win98", label="Windows 98", scheme="light",
        bg="#008080", panel="#c0c0c0", text="#111111", muted="#3e3e3e",
        line="#808080", soft="#d4d0c8", brand="#000080", brand_soft="#d8d8e9",
        danger="#8b0000", on_brand="#ffffff",
        font_family="Tahoma", relief="raised", borderwidth=2, square=True,
        field_bg="#ffffff", table_bg="#ffffff", heading_bg="#c0c0c0",
        button_bg="#c0c0c0", button_border="#404040",
        bevel_light="#ffffff", bevel_dark="#808080",
        top_bg="#000080", top_fg="#ffffff", top_muted="#ffffff",
        chip_bg="#c0c0c0", chip_fg="#111111",
        primary_bg="#c0c0c0", primary_fg="#111111",
        nav_fg="#111111", nav_active_bg="#000080", nav_active_fg="#ffffff",
        status_bg="#c0c0c0", status_fg="#111111",
        tab_bg="#c0c0c0", tab_active_bg="#dedede",
        description="Clássico · cinza, relevo e azul marinho",
    ),
}

DEFAULT_THEME = "dark"

_current_key: str = DEFAULT_THEME
_listeners: list[Callable[[str], None]] = []
_patched = False


def theme_keys_ordered() -> list[str]:
    """Ordem canônica dos temas (inventários de captura e contratos)."""
    return ["dark", "light", "mid", "dracula", "nord", "solarized", "xp", "win98"]


def theme_keys_for_picker() -> list[str]:
    """Ordem da grade de temas no protótipo (Configurações → Aparência)."""
    return ["dark", "light", "mid", "dracula", "nord", "xp", "win98", "solarized"]


def get_spec(key: Optional[str] = None) -> ThemeSpec:
    return THEMES.get(key or _current_key, THEMES[DEFAULT_THEME])


def current_key() -> str:
    return _current_key


def _bevel(spec: ThemeSpec, fill: str) -> dict:
    """Cores de borda do clam: linha única nos temas modernos, relevo nos retrô."""
    light = tok(spec, "bevel_light") or fill
    dark = tok(spec, "bevel_dark") or fill
    return {"lightcolor": light, "darkcolor": dark}


def _configure_ttk(style: ttk.Style, spec: ThemeSpec) -> None:
    style.theme_use("clam")

    base_font = (spec.font_family, 9)
    bold_font = (spec.font_family, 9, "bold")
    retro = spec.relief == "raised"
    field_bg = tok(spec, "field_bg")
    button_bg = tok(spec, "button_bg")
    button_border = tok(spec, "button_border")
    table_bg = tok(spec, "table_bg")
    heading_bg = tok(spec, "heading_bg")

    style.configure(
        ".", background=spec.bg, foreground=spec.text, font=base_font,
        bordercolor=spec.line, lightcolor=spec.panel, darkcolor=spec.panel,
        troughcolor=spec.bg, focuscolor=spec.brand, selectbackground=spec.brand,
        selectforeground=spec.on_brand, insertcolor=spec.text,
    )

    # ---------------- superfícies ----------------
    style.configure("TFrame", background=spec.bg)
    style.configure("Panel.TFrame", background=spec.panel)
    style.configure("Soft.TFrame", background=spec.soft)
    card_border = {"bordercolor": button_border if retro else spec.line}
    card_border.update(_bevel(spec, spec.panel))
    for name in ("TLabelframe", "Card.TLabelframe"):
        style.configure(
            name, background=spec.panel, foreground=spec.text,
            relief="raised" if retro else "solid", borderwidth=spec.borderwidth,
            padding=0, **card_border,
        )
        style.configure(
            f"{name}.Label", background=spec.panel,
            foreground=tok(spec, "card_title_fg"),
            font=(spec.font_family, 10, "bold"), padding=(8, 4),
        )

    # ---------------- textos ----------------
    style.configure("TLabel", background=spec.bg, foreground=spec.text)
    style.configure("Muted.TLabel", background=spec.bg, foreground=spec.muted)
    style.configure("Panel.TLabel", background=spec.panel, foreground=spec.text)
    style.configure("PanelMuted.TLabel", background=spec.panel, foreground=spec.muted)
    style.configure("PanelTitle.TLabel", background=spec.panel, foreground=spec.text,
                    font=(spec.font_family, 13, "bold"))
    style.configure("PanelStrong.TLabel", background=spec.panel, foreground=spec.text,
                    font=bold_font)
    style.configure("PanelMetric.TLabel", background=spec.panel, foreground=spec.text,
                    font=(spec.font_family, 15, "bold"))
    style.configure(
        "Section.TLabel", background=spec.bg, foreground=spec.muted,
        font=bold_font, padding=(0, 0, 0, 5),
    )
    style.configure(
        "PanelSection.TLabel", background=spec.panel, foreground=spec.muted,
        font=bold_font, padding=(0, 0, 0, 5),
    )
    # .nx-head: no Windows 98 o cabeçalho da página é uma caixa cinza em relevo.
    head_bg = spec.panel if spec.square else spec.bg
    if spec.square:
        style.configure("Head.TFrame", background=head_bg, relief="raised", borderwidth=2,
                        bordercolor="#404040", lightcolor="#ffffff", darkcolor="#808080",
                        padding=14)
    else:
        style.configure("Head.TFrame", background=head_bg, relief="flat", borderwidth=0,
                        padding=0)
    style.configure("PageTitle.TLabel", background=head_bg, foreground=spec.text,
                    font=(spec.font_family, 18, "bold"))
    style.configure("PageSubtitle.TLabel", background=head_bg, foreground=spec.muted,
                    font=(spec.font_family, 10))
    style.configure("Badge.TLabel", background=tok(spec, "chip_bg"),
                    foreground=tok(spec, "chip_fg"), padding=(8, 3),
                    font=(spec.font_family, 8))
    style.configure("Tag.TLabel", background=spec.brand_soft, foreground=spec.brand,
                    padding=(7, 3), font=(spec.font_family, 8))
    style.configure("Info.TFrame", background=spec.brand_soft)
    style.configure("InfoBar.TFrame", background=spec.brand)
    style.configure("Info.TLabel", background=spec.brand_soft, foreground=spec.text)
    style.configure("Steps.TFrame", background=head_bg, padding=8 if spec.square else 0)
    style.configure("Step.TLabel", background=head_bg, foreground=spec.muted,
                    font=(spec.font_family, 8))
    style.configure("StepNum.TLabel", background=spec.soft, foreground=spec.muted,
                    padding=(6, 1), font=(spec.font_family, 8))
    style.configure("StepActive.TLabel", background=head_bg, foreground=spec.brand,
                    font=(spec.font_family, 8))
    style.configure("TSeparator", background=spec.line)

    # ---------------- shell: barra superior, menu lateral, status ----------------
    top_bg = tok(spec, "top_bg")
    style.configure("Top.TFrame", background=top_bg)
    style.configure("Top.TLabel", background=top_bg, foreground=tok(spec, "top_fg"),
                    font=(spec.font_family, 10, "bold"))
    style.configure("TopMuted.TLabel", background=top_bg, foreground=tok(spec, "top_muted"),
                    font=(spec.font_family, 10))
    style.configure("Logo.TLabel", background=spec.brand, foreground=spec.on_brand,
                    padding=(7, 3), font=(spec.font_family, 12, "bold"))
    style.configure("SideLogo.TLabel", background=spec.panel, foreground=spec.text,
                    font=(spec.font_family, 16, "bold"))
    style.configure(
        "Kicker.TLabel", background=spec.panel, foreground=spec.muted,
        font=(spec.font_family, 8, "bold"), padding=(12, 0, 0, 0),
    )
    nav_common = dict(anchor="w", padding=(11, 9), relief="flat", borderwidth=0,
                      bordercolor=spec.panel, lightcolor=spec.panel, darkcolor=spec.panel,
                      focuscolor=spec.panel)
    style.configure("Nav.TButton", background=spec.panel, foreground=tok(spec, "nav_fg"),
                    font=base_font, **nav_common)
    style.map("Nav.TButton", background=[("active", spec.soft)],
              foreground=[("active", spec.text)])
    active_bg = tok(spec, "nav_active_bg")
    style.configure("NavSelected.TButton", background=active_bg,
                    foreground=tok(spec, "nav_active_fg"), font=bold_font,
                    **{**nav_common, "bordercolor": active_bg, "lightcolor": active_bg,
                       "darkcolor": active_bg, "focuscolor": active_bg})
    style.map("NavSelected.TButton", background=[("active", active_bg)],
              foreground=[("active", tok(spec, "nav_active_fg"))])
    # Compatibilidade: o estilo antigo dos atalhos agora é idêntico ao menu.
    style.configure("Tool.TButton", background=spec.panel, foreground=tok(spec, "nav_fg"),
                    font=base_font, **nav_common)
    style.map("Tool.TButton", background=[("active", spec.soft)])

    status_bg = tok(spec, "status_bg")
    style.configure("Status.TFrame", background=status_bg)
    style.configure("Status.TLabel", background=status_bg, foreground=tok(spec, "status_fg"),
                    font=(spec.font_family, 9))

    # ---------------- botões ----------------
    button_pad = (10, 5) if retro else (12, 6)
    style.configure(
        "TButton", background=button_bg, foreground=spec.text,
        bordercolor=button_border, relief="raised" if retro else "solid", borderwidth=1,
        padding=button_pad, focuscolor=spec.brand, focusthickness=1,
        **_bevel(spec, button_bg),
    )
    style.map(
        "TButton",
        background=[("pressed", spec.soft), ("active", spec.soft)],
        foreground=[("disabled", spec.muted)],
        bordercolor=[("active", spec.brand if not retro else button_border)],
    )
    primary_bg = tok(spec, "primary_bg")
    style.configure(
        "Accent.TButton", background=primary_bg, foreground=tok(spec, "primary_fg"),
        bordercolor=spec.text if spec.square else primary_bg,
        relief="raised" if retro else "solid",
        borderwidth=1, padding=(12, 7),
        **_bevel(spec, primary_bg),
    )
    style.map("Accent.TButton", background=[("active", primary_bg), ("pressed", primary_bg)],
              foreground=[("active", tok(spec, "primary_fg"))])
    style.configure(
        "Ghost.TButton", background=spec.panel, foreground=spec.muted,
        bordercolor=spec.panel, lightcolor=spec.panel, darkcolor=spec.panel,
        relief="flat", padding=(6, 4),
    )
    style.map("Ghost.TButton", background=[("active", spec.soft)])

    # Menubutton (ex.: "Mais ações ▾") não herda o estilo de TButton por conta
    # própria — sem isso ficava com o visual padrão do tema do SO (branco),
    # destoando do resto da tela e ficando branco ao passar o mouse.
    style.configure(
        "TMenubutton", background=button_bg, foreground=spec.text,
        bordercolor=button_border, relief="raised" if retro else "solid", borderwidth=1,
        padding=button_pad, arrowcolor=spec.text,
        **_bevel(spec, button_bg),
    )
    style.map(
        "TMenubutton",
        background=[("pressed", spec.soft), ("active", spec.soft)],
        foreground=[("disabled", spec.muted)],
        arrowcolor=[("disabled", spec.muted)],
    )

    # ---------------- campos ----------------
    if spec.square:
        field_border = {"bordercolor": "#808080", "lightcolor": "#404040", "darkcolor": "#ffffff"}
    else:
        field_border = {"bordercolor": "#7f9db9" if spec.key == "xp" else spec.line,
                        "lightcolor": field_bg, "darkcolor": field_bg}
    style.configure(
        "TEntry", fieldbackground=field_bg, foreground=spec.text,
        insertcolor=spec.text, padding=(6, 4), **field_border,
    )
    style.map("TEntry", fieldbackground=[("disabled", spec.soft), ("readonly", field_bg)],
              bordercolor=[("focus", spec.brand)])
    style.configure(
        "TCombobox", fieldbackground=field_bg, foreground=spec.text,
        background=button_bg, arrowcolor=spec.text, padding=(6, 4),
        **field_border,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", field_bg), ("disabled", spec.soft)],
        foreground=[("readonly", spec.text)],
        background=[("active", spec.soft), ("pressed", spec.soft)],
        bordercolor=[("focus", spec.brand)],
        selectbackground=[("readonly", field_bg)],
        selectforeground=[("readonly", spec.text)],
    )
    style.configure("TSpinbox", fieldbackground=field_bg, foreground=spec.text,
                    background=button_bg, arrowcolor=spec.text, **field_border)

    indicator = dict(
        indicatorbackground=field_bg, indicatorforeground=spec.brand,
        upperbordercolor=spec.line if not spec.square else "#808080",
        lowerbordercolor=spec.line if not spec.square else "#ffffff",
        indicatormargin=(0, 0, 6, 0),
    )
    for prefix, bg in (("", spec.bg), ("Panel.", spec.panel)):
        for cls in ("TCheckbutton", "TRadiobutton"):
            style.configure(f"{prefix}{cls}", background=bg, foreground=spec.text, **indicator)
            style.map(f"{prefix}{cls}", background=[("active", bg)],
                      indicatorbackground=[("pressed", spec.soft), ("disabled", spec.soft)])

    # ---------------- abas ----------------
    tab_bg = tok(spec, "tab_bg")
    tab_active = tok(spec, "tab_active_bg")
    style.configure(
        "TNotebook", background=spec.panel, bordercolor=spec.line,
        lightcolor=spec.panel, darkcolor=spec.panel, tabmargins=(14, 6, 14, 0),
    )
    if retro:
        style.configure(
            "TNotebook.Tab", background=tab_bg, foreground=spec.muted,
            padding=(12, 6), bordercolor=spec.line, **_bevel(spec, tab_bg),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", tab_active)],
            foreground=[("selected", spec.brand)],
            expand=[("selected", (1, 2, 1, 0))],
        )
    else:
        style.configure(
            "TNotebook.Tab", background=spec.panel, foreground=spec.muted,
            padding=(4, 9), bordercolor=spec.panel, lightcolor=spec.panel,
            darkcolor=spec.panel, focuscolor=spec.panel,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", spec.panel), ("active", spec.panel)],
            foreground=[("selected", spec.brand), ("active", spec.text)],
            expand=[("selected", (0, 0, 0, 0))],
        )

    # ---------------- tabelas ----------------
    style.configure(
        "Treeview", background=table_bg, fieldbackground=table_bg,
        foreground=spec.text, bordercolor=spec.line, rowheight=30,
        lightcolor=table_bg, darkcolor=table_bg,
    )
    style.configure(
        "Treeview.Heading", background=heading_bg, foreground=spec.muted,
        relief="raised" if retro else "flat", padding=(10, 8),
        bordercolor=spec.line if retro else heading_bg,
        font=base_font, **_bevel(spec, heading_bg),
    )
    style.map("Treeview.Heading", background=[("active", spec.soft)])
    style.map(
        "Treeview",
        background=[("selected", spec.brand_soft)],
        foreground=[("selected", spec.text)],
    )

    # ---------------- rolagem e demais ----------------
    if retro:
        style.configure(
            "TScrollbar", background=spec.panel, troughcolor=spec.soft,
            bordercolor=spec.line, arrowcolor=spec.text, gripcount=0,
            **_bevel(spec, spec.panel),
        )
    else:
        style.configure(
            "TScrollbar", background=spec.soft, troughcolor=spec.bg,
            bordercolor=spec.bg, lightcolor=spec.soft, darkcolor=spec.soft,
            arrowcolor=spec.muted, gripcount=0, arrowsize=12,
        )
    style.map("TScrollbar", background=[("active", spec.line)])
    style.configure("TPanedwindow", background=spec.bg)
    style.configure("TProgressbar", background=spec.brand, troughcolor=spec.soft,
                    bordercolor=spec.line, lightcolor=spec.brand, darkcolor=spec.brand)

    # O clam traz style.map próprios (relevo das abas, borda de foco azul dos
    # campos, padding da aba ativa) que prevalecem sobre configure().
    tab_pad = (12, 6) if retro else (4, 9)
    tab_light = tok(spec, "bevel_light") or spec.panel
    tab_dark = tok(spec, "bevel_dark") or spec.panel
    style.map(
        "TNotebook.Tab",
        lightcolor=[("selected", tab_light), ("", tab_light)],
        darkcolor=[("selected", tab_dark), ("", tab_dark)],
        bordercolor=[("selected", spec.line if retro else spec.panel),
                     ("", spec.line if retro else spec.panel)],
        padding=[("selected", tab_pad), ("", tab_pad)],
    )
    if not spec.square:
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.map(name, lightcolor=[("focus", field_bg)], darkcolor=[("focus", field_bg)])
    style.map("TButton", lightcolor=[("pressed", tok(spec, "bevel_dark") or spec.soft)],
              darkcolor=[("pressed", tok(spec, "bevel_light") or spec.soft)])

    _install_tab_underline(style, spec)


# Sublinhado da aba ativa (.nx-tabs button.active { border-bottom:2px brand }).
# O clam não desenha borda só embaixo; um elemento de imagem de 2 px resolve
# sem mexer em nenhum Notebook dos módulos.
_TAB_IMAGES: dict[str, tk.PhotoImage] = {}


def _install_tab_underline(style: ttk.Style, spec: ThemeSpec) -> None:
    try:
        master = style.master
        current = _TAB_IMAGES.get("on")
        if current is None or current.tk is not master.tk:
            _TAB_IMAGES.pop("sep", None)
            _TAB_IMAGES["on"] = tk.PhotoImage(master=master, width=6, height=2)
            _TAB_IMAGES["off"] = tk.PhotoImage(master=master, width=6, height=2)
        retro = spec.relief == "raised"
        on_color = tok(spec, "tab_active_bg") if retro else spec.brand
        off_color = tok(spec, "tab_bg") if retro else spec.panel
        _TAB_IMAGES["on"].put(on_color, to=(0, 0, 6, 2))
        _TAB_IMAGES["off"].put(off_color, to=(0, 0, 6, 2))
        # Separador: o elemento nativo é um relevo 3D cuja sombra clara vira
        # uma faixa brilhante nos temas escuros; .nx usa linha chapada --n-line.
        if "sep" not in _TAB_IMAGES or _TAB_IMAGES["sep"].tk is not master.tk:
            _TAB_IMAGES["sep"] = tk.PhotoImage(master=master, width=1, height=1)
        _TAB_IMAGES["sep"].put(spec.line, to=(0, 0, 1, 1))
        if "NxSep.line" not in style.element_names():
            style.element_create("NxSep.line", "image", _TAB_IMAGES["sep"], sticky="nswe")
            for name in ("TSeparator", "Horizontal.TSeparator", "Vertical.TSeparator"):
                style.layout(name, [("NxSep.line", {"sticky": "nswe"})])
        if "NxTab.underline" not in style.element_names():
            style.element_create(
                "NxTab.underline", "image", _TAB_IMAGES["off"],
                ("selected", _TAB_IMAGES["on"]), border=(2, 0), sticky="ew",
            )
            style.layout("TNotebook.Tab", [
                ("Notebook.tab", {"sticky": "nswe", "children": [
                    ("NxTab.underline", {"side": "bottom", "sticky": "ew"}),
                    ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                        ("Notebook.label", {"side": "top", "sticky": ""}),
                    ]}),
                ]}),
            ])
    except tk.TclError:
        # Sem o elemento extra a aba continua funcional, só sem o sublinhado.
        pass


_TK_WIDGET_COLORS: dict[str, Callable[[tk.Widget, ThemeSpec], None]] = {}


def _safe_configure(widget: tk.Misc, **kwargs) -> None:
    try:
        widget.configure(**kwargs)
    except tk.TclError:
        pass


# Dentro de cartões, abas e diálogos o protótipo usa --n-panel. Widgets ttk
# criados com o estilo padrão herdariam --n-bg e formariam faixas de outra cor
# dentro do cartão (visível em todos os temas, gritante no Windows 98).
_PANEL_VARIANTS: dict[tuple[str, str], str] = {
    ("TFrame", ""): "Panel.TFrame",
    ("TFrame", "TFrame"): "Panel.TFrame",
    ("TLabel", ""): "Panel.TLabel",
    ("TLabel", "TLabel"): "Panel.TLabel",
    ("TLabel", "Muted.TLabel"): "PanelMuted.TLabel",
    ("TLabel", "PageTitle.TLabel"): "PanelTitle.TLabel",
    ("TLabel", "PageSubtitle.TLabel"): "PanelMuted.TLabel",
    ("TLabel", "Section.TLabel"): "PanelSection.TLabel",
    ("TCheckbutton", ""): "Panel.TCheckbutton",
    ("TRadiobutton", ""): "Panel.TRadiobutton",
}
_PANEL_STYLE_PREFIXES = ("Panel.", "Card.", "Info.")


def _ttk_style(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("style"))
    except tk.TclError:
        return ""


def _child_context(widget: tk.Misc, cls: str, ctx: str) -> str:
    """Superfície ('bg' ou 'panel') sobre a qual os filhos são desenhados."""
    if cls in ("TLabelframe", "Labelframe", "TNotebook"):
        return "panel"
    if cls == "Toplevel":
        return "panel"
    if cls in ("TFrame",):
        style = _ttk_style(widget)
        if style.startswith(_PANEL_STYLE_PREFIXES):
            return "panel"
        if style in ("Top.TFrame", "Status.TFrame"):
            return ctx
        if style in ("", "TFrame"):
            return ctx
        return "bg"
    return ctx


def _recolor_widget(widget: tk.Misc, spec: ThemeSpec, ctx: str = "bg") -> None:
    if getattr(widget, "_nx_static", False):
        return
    try:
        cls = widget.winfo_class()
    except tk.TclError:
        return

    surface = spec.panel if ctx == "panel" else spec.bg
    field_bg = tok(spec, "field_bg")

    variant = _PANEL_VARIANTS.get((cls, _ttk_style(widget))) if ctx == "panel" else None
    if variant:
        _safe_configure(widget, style=variant)

    if cls == "Tk":
        _safe_configure(widget, background=spec.bg)
    elif cls == "Toplevel":
        _safe_configure(widget, background=spec.panel)
    elif cls in ("Frame", "Canvas"):
        _safe_configure(widget, background=surface)
        if cls == "Canvas":
            _safe_configure(widget, highlightbackground=spec.line)
    elif cls == "Label":
        _safe_configure(widget, background=surface, foreground=spec.text)
    elif cls in ("Listbox", "Text"):
        _safe_configure(
            widget, background=field_bg, foreground=spec.text,
            selectbackground=spec.brand_soft, selectforeground=spec.text,
            highlightbackground=spec.line, highlightcolor=spec.brand,
            highlightthickness=1, relief="flat", borderwidth=0,
        )
        if cls == "Text":
            _safe_configure(widget, insertbackground=spec.text)
    elif cls == "Menu":
        _safe_configure(
            widget, background=spec.panel, foreground=spec.text,
            activebackground=spec.brand_soft, activeforeground=spec.text,
        )
    elif cls == "Button":
        _safe_configure(
            widget, background=tok(spec, "button_bg"), foreground=spec.text,
            activebackground=spec.soft, activeforeground=spec.text,
            highlightbackground=surface,
        )
    elif cls == "Entry":
        _safe_configure(
            widget, background=field_bg, foreground=spec.text,
            insertbackground=spec.text, relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=spec.line, highlightcolor=spec.brand,
        )
    elif cls in ("Checkbutton", "Radiobutton"):
        _safe_configure(widget, background=surface, foreground=spec.text,
                        activebackground=surface, selectcolor=field_bg)
    elif cls == "Labelframe":
        _safe_configure(widget, background=spec.panel, foreground=spec.text)

    child_ctx = _child_context(widget, cls, ctx)
    for child in widget.winfo_children():
        _recolor_widget(child, spec, child_ctx)


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


def fit_to_content(win: tk.Misc, margin: int = 40) -> None:
    """Aumenta um diálogo até o tamanho pedido pelo conteúdo.

    Vários diálogos fixam `geometry()` em pixels; com o escalonamento do
    Windows (ex.: 125%/150%) os botões de rodapé ficavam fora da janela.
    Só cresce — nunca encolhe o que o módulo definiu — e respeita a tela.
    """
    try:
        win.update_idletasks()
        req_w, req_h = win.winfo_reqwidth(), win.winfo_reqheight()
        cur_w, cur_h = win.winfo_width(), win.winfo_height()
        max_w = win.winfo_screenwidth() - margin
        max_h = win.winfo_screenheight() - margin * 2
        new_w = min(max(cur_w, req_w), max_w)
        new_h = min(max(cur_h, req_h), max_h)
        if new_w > cur_w or new_h > cur_h:
            x = max(0, min(win.winfo_x(), win.winfo_screenwidth() - new_w))
            y = max(0, min(win.winfo_y(), win.winfo_screenheight() - new_h - margin))
            win.geometry(f"{new_w}x{new_h}+{x}+{y}")
    except tk.TclError:
        pass


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

        def _first_map(_event=None):
            if getattr(self, "_nx_fitted", False):
                return
            self._nx_fitted = True
            self.after_idle(lambda: fit_to_content(self))

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
            self.bind("<Map>", _first_map, add="+")
        except Exception:
            pass

    tk.Toplevel.__init__ = patched_init
