"""Primitives visuais compartilhadas pelo shell e pelos módulos Nexor.

Os helpers só montam widgets; callbacks e estado continuam pertencendo aos
módulos que os usam.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


def page_metrics() -> dict[str, object]:
    """Métricas de composição compartilhadas pelas páginas Nexor.

    Mantém os valores do protótipo em um único contrato para que as telas
    Tkinter não acumulem espaçamentos ligeiramente diferentes.
    """
    return {
        "page_pad": (28, 22, 28, 18),
        "section_gap": 14,
        "card_pad": 14,
        "control_gap": 8,
    }


def make_status_text(*parts: object) -> str:
    """Monta a mensagem curta usada na barra inferior do protótipo."""
    return " · ".join(str(part) for part in parts if str(part).strip())


def page_heading(parent: tk.Misc, title: str, subtitle: str, *, action: Optional[Callable[[], None]] = None,
                 action_text: str = "") -> ttk.Frame:
    """Cria cabeçalho de página com título, subtítulo e ação opcional."""
    frame = ttk.Frame(parent, padding=(0, 0, 0, 14))
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=title, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text=subtitle, style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
    if action is not None:
        ttk.Button(frame, text=action_text, command=action, style="Accent.TButton").grid(
            row=0, column=1, rowspan=2, sticky="e", padx=(16, 0)
        )
    return frame


def card(parent: tk.Misc, title: str = "", *, padding: int = 14) -> ttk.LabelFrame:
    """Cria um cartão/agrupamento com espaçamento consistente."""
    return ttk.LabelFrame(parent, text=title, padding=padding, style="Card.TLabelframe")


def page_scroll_container(parent: tk.Misc) -> tuple[ttk.Frame, tk.Canvas]:
    """Cria o contêiner rolável padrão para páginas longas."""
    frame = ttk.Frame(parent)
    canvas = tk.Canvas(frame, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    body = ttk.Frame(canvas, padding=page_metrics()["page_pad"])
    window_id = canvas.create_window((0, 0), window=body, anchor="nw")
    body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
    return body, canvas


def status_bar(parent: tk.Misc, variable: tk.StringVar) -> ttk.Frame:
    """Cria a barra de status inferior, sem impor quem atualiza a mensagem."""
    frame = ttk.Frame(parent, style="Status.TFrame", padding=(14, 7))
    ttk.Label(frame, textvariable=variable, style="Status.TLabel").pack(anchor="w")
    return frame


def dialog_header(parent: tk.Misc, title: str, subtitle: str = "") -> ttk.Frame:
    """Cabeçalho compacto para diálogos Tkinter equivalentes ao modal HTML."""
    frame = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 0, 0, 12))
    ttk.Label(frame, text=title, style="PageTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PanelMuted.TLabel").pack(anchor="w", pady=(3, 0))
    return frame
