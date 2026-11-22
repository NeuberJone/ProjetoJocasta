"""Primitives visuais compartilhadas pelo shell e pelos módulos Nexor.

Os helpers só montam widgets; callbacks e estado continuam pertencendo aos
módulos que os usam.
"""

from __future__ import annotations

import threading
import tkinter as tk
import weakref
from tkinter import ttk
from typing import Any, Callable, Optional

from core import theme
from core.logging_config import get_logger, log_exception

_logger = get_logger(__name__)

# ttk ignora "padding" vindo do estilo em frames; as caixas que só têm
# preenchimento interno no Windows 98 (.nx-head/.nx-step) são ajustadas aqui.
_BOXED: "weakref.WeakKeyDictionary[ttk.Frame, int]" = weakref.WeakKeyDictionary()


def _sync_boxed(_key: str = "") -> None:
    boxed = theme.get_spec().square
    for frame, pad in list(_BOXED.items()):
        try:
            frame.configure(padding=pad if boxed else 0)
        except tk.TclError:
            pass


theme.on_theme_changed(_sync_boxed)


def _boxed(frame: ttk.Frame, pad: int) -> ttk.Frame:
    _BOXED[frame] = pad
    try:
        frame.configure(padding=pad if theme.get_spec().square else 0)
    except tk.TclError:
        pass
    return frame


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


def columns_for_width(width: int, *, minimum: int = 280, maximum: int = 4) -> int:
    """Calcula colunas para grades que não devem criar overflow horizontal."""
    if width <= 0:
        return 1
    return max(1, min(maximum, width // max(1, minimum)))


def make_status_text(*parts: object) -> str:
    """Monta a mensagem curta usada na barra inferior do protótipo."""
    return " · ".join(str(part) for part in parts if str(part).strip())


def page_heading(parent: tk.Misc, title: str, subtitle: str, *, action: Optional[Callable[[], None]] = None,
                 action_text: str = "") -> ttk.Frame:
    """Cria cabeçalho de página com título, subtítulo e ação opcional."""
    outer = ttk.Frame(parent, padding=(0, 0, 0, 14))
    frame = _boxed(ttk.Frame(outer, style="Head.TFrame"), 14)
    frame.pack(fill="x")
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=title, style="PageTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(frame, text=subtitle, style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
    if action is not None:
        ttk.Button(frame, text=action_text, command=action, style="Accent.TButton").grid(
            row=0, column=1, rowspan=2, sticky="e", padx=(16, 0)
        )
    return outer


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

    def _on_wheel(event) -> None:
        # Ignora o scroll enquanto algum diálogo modal tiver o grab do Tk —
        # sem isso, rolar a roda sobre um diálogo aberto também rola a
        # página por trás dele (o cursor não "sai" do canvas quando o
        # diálogo só aparece por cima, sem mover o mouse), deixando um
        # espaço em branco no topo da página ao fechar o diálogo.
        if canvas.grab_current() is not None:
            return
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", _on_wheel))
    canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
    return body, canvas


def status_bar(parent: tk.Misc, variable: tk.StringVar) -> ttk.Frame:
    """Cria a barra de status inferior, sem impor quem atualiza a mensagem."""
    frame = ttk.Frame(parent, style="Status.TFrame", padding=(14, 7))
    ttk.Label(frame, textvariable=variable, style="Status.TLabel").pack(anchor="w")
    return frame


def dialog_header(parent: tk.Misc, title: str, subtitle: str = "") -> ttk.Frame:
    """Cabeçalho compacto para diálogos Tkinter equivalentes ao modal HTML."""
    frame = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 0, 0, 0))
    ttk.Label(frame, text=title, style="PanelTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PanelMuted.TLabel").pack(anchor="w", pady=(3, 0))
    ttk.Separator(frame).pack(fill="x", pady=(12, 0))
    return frame


def info_banner(parent: tk.Misc, text: str) -> ttk.Frame:
    """Aviso informativo com faixa de destaque à esquerda (protótipo da Operação)."""
    frame = ttk.Frame(parent, style="InfoBar.TFrame", padding=(3, 0, 0, 0))
    inner = ttk.Frame(frame, style="Info.TFrame", padding=(14, 10))
    inner.pack(fill="both", expand=True)
    ttk.Label(inner, text=text, style="Info.TLabel", wraplength=900, justify="left").pack(anchor="w")
    return frame


def step_indicator(parent: tk.Misc, steps: list[str], active: int = 0) -> ttk.Frame:
    """Indicador de etapas numeradas (somente leitura, sem navegação)."""
    outer = ttk.Frame(parent, padding=(0, 0, 0, 16))
    frame = _boxed(ttk.Frame(outer, style="Steps.TFrame"), 8)
    frame.pack(fill="x")
    for index, label in enumerate(steps):
        ttk.Label(frame, text=str(index + 1), style="StepNum.TLabel").pack(side="left")
        style = "StepActive.TLabel" if index == active else "Step.TLabel"
        ttk.Label(frame, text=label, style=style).pack(side="left", padx=(6, 14))
    return outer


def run_async(
    widget: tk.Misc,
    work: Callable[[], Any],
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> None:
    """Roda `work` numa thread separada e entrega o resultado (ou erro) de
    volta na thread principal do Tkinter via `widget.after(0, ...)` — nunca
    atualiza um widget direto de dentro da thread de trabalho. Introduzido
    pela Etapa E do recurso de identificação de vendedor (ver
    core/order_files.py e core/order_pdfs.py), cuja indexação de pastas de
    rede e geração de miniaturas de PDF são as primeiras operações do Nexor
    potencialmente lentas o bastante pra exigir isto (regra obrigatória:
    "Não bloquear a interface durante pesquisas ou geração de miniaturas").

    Uma excecão dentro de `work` nunca mata a thread silenciosamente: é
    capturada e entregue a `on_error` (se informado), do mesmo jeito seguro
    via `after`; sem `on_error`, só é registrada no log.

    Achado de revisão de código: se a janela for fechada ENQUANTO a thread
    de trabalho ainda está rodando (ex.: "Atualizar índice"/"Criar backup"
    numa pasta de rede lenta), `widget.after(...)` pode falhar ao agendar
    (widget já destruído) ou o callback entregue pode falhar ao tentar
    atualizar um botão/variável que não existe mais — nos dois casos é só
    registrado no log, nunca propagado (a thread de trabalho já terminou;
    não há mais ninguém esperando o resultado)."""
    def _deliver(callback: Callable[[], None]) -> None:
        try:
            widget.after(0, callback)
        except tk.TclError as exc:
            log_exception(_logger, "run_async: widget destroyed before result could be delivered", exc)

    def _run_callback(callback: Callable[[Any], None], value: Any) -> None:
        try:
            callback(value)
        except tk.TclError as exc:
            log_exception(_logger, "run_async: widget destroyed while callback was running", exc)

    def _runner() -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 - repassa qualquer erro pro callback, nunca deixa a thread morrer silenciosamente
            if on_error is not None:
                _deliver(lambda: _run_callback(on_error, exc))
            else:
                log_exception(_logger, "Unhandled error in background task", exc)
            return
        if on_done is not None:
            _deliver(lambda: _run_callback(on_done, result))

    threading.Thread(target=_runner, daemon=True).start()


def ask_pick_from_list(
    parent: tk.Misc,
    title: str,
    prompt: str,
    items: list,
    label_fn: Callable[[Any], str],
) -> Optional[Any]:
    """Diálogo modal simples de escolha única — usado tanto para ambiguidade
    de vendedor/PDF (vários candidatos encontrados) quanto para correção
    manual ("Alterar vendedor...", "Escolher vendedor..."/"Escolher PDF..."
    do painel de pré-visualização em Operação). Sem seleção == Cancelar
    (retorna None, nunca escolhe o primeiro item por conta própria).

    Originalmente só em modules/registros/ui.py; promovido pra aqui quando
    o painel de pré-visualização de Operação (Parte 1 da conclusão do
    recurso de identificação de vendedor/PDF) passou a precisar do mesmo
    diálogo, pra não duplicar a implementação."""
    if not items:
        return None
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    win.grab_set()
    result: dict = {"value": None}

    ttk.Label(win, text=prompt, wraplength=440, justify="left").pack(anchor="w", padx=12, pady=(12, 6))
    listbox = tk.Listbox(win, height=min(8, len(items)), width=72, exportselection=False)
    for item in items:
        listbox.insert("end", label_fn(item))
    # Achado de revisão de código: um `selection_set(0)` aqui pré-selecionava
    # o primeiro item da lista — clicar em "Confirmar" sem escolher nada
    # devolvia esse primeiro item como se fosse a escolha do operador,
    # contradizendo a garantia documentada acima ("nunca escolhe o primeiro
    # item por conta própria"). Removido: sem clique numa linha, `on_ok`
    # já trata "nenhuma seleção" igual a Cancelar.
    listbox.pack(fill="both", expand=True, padx=12)

    def on_ok() -> None:
        sel = listbox.curselection()
        if sel:
            result["value"] = items[sel[0]]
        win.destroy()

    def on_cancel() -> None:
        win.destroy()

    btn_row = ttk.Frame(win)
    btn_row.pack(fill="x", padx=12, pady=12)
    ttk.Button(btn_row, text="Confirmar", command=on_ok).pack(side="right")
    ttk.Button(btn_row, text="Cancelar", command=on_cancel).pack(side="right", padx=(0, 8))

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    win.wait_window()
    return result["value"]
