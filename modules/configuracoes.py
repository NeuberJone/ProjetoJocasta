"""Seções de produção da página Configurações.

Reúne as configurações fixas que antes ficavam espalhadas pelos módulos:
tipos de impressão e arquivos de espaço (Operação), padrões de cálculo e
exportação (Planejador) e manutenção dos registros salvos (Registros).
Cada seção salva no mesmo arquivo de configuração que o módulo já lia, e
avisa a página via `on_saved(modulo)` para recarregar sem reiniciar.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from core.config import read_module_cfg, write_module_cfg
from core.fabrics import known_fabric_names_with_aliases
from core.operators import normalize_operators
from core.print_pattern import (
    ALL_KINDS,
    KIND_FIXED,
    KIND_LABELS,
    KIND_OPTIONAL,
    KIND_SEPARATOR,
    MATCH_MODE_CONTAINS,
    MATCH_MODE_LABELS,
    MATCH_MODE_START,
    PEDIDO_MODE_AUTO,
    PEDIDO_MODE_FIXED,
    PEDIDO_MODE_LABELS,
    SEPARATOR_CHARS,
    SEPARATOR_LABELS,
    Component,
    build_pattern,
    components_to_list,
    new_rule_id,
    strip_extension,
)
from core.print_pattern_analyzer import analyze_examples
from core.print_types import (
    DEFAULT_RULES,
    DEFAULT_SUBTYPES,
    FALLBACK_TYPE,
    classify_document,
    classify_with_detail,
    detect_conflicts,
    normalize_rules,
    normalize_subtypes,
    validate_pattern,
)
from core.ui import card, dialog_header
from modules.operacao.config import load_cfg as load_operacao_cfg
from modules.operacao.config import save_cfg as save_operacao_cfg
from modules.operacao.parser import normalize_space_entries

# Tipos de bloco que o editor visual oferece no seletor por linha —
# "Separador" é modelado como linha própria (combobox de caractere) e
# "Opcional" ainda não tem UI dedicada (ver limitações no relatório da
# funcionalidade), então ficam de fora da lista de opções por bloco.
_BLOCK_KIND_OPTIONS: List[str] = [
    k for k in ALL_KINDS if k not in (KIND_SEPARATOR, KIND_OPTIONAL)
]
_BLOCK_KIND_LABELS: List[str] = [KIND_LABELS[k] for k in _BLOCK_KIND_OPTIONS]
_LABEL_TO_KIND: Dict[str, str] = {v: k for k, v in KIND_LABELS.items()}

_SEP_LABELS: List[str] = [SEPARATOR_LABELS[c] for c in SEPARATOR_CHARS]
_LABEL_TO_SEP: Dict[str, str] = {v: k for k, v in SEPARATOR_LABELS.items()}

_MODE_LABELS: List[str] = list(MATCH_MODE_LABELS.values())
_LABEL_TO_MODE: Dict[str, str] = {v: k for k, v in MATCH_MODE_LABELS.items()}

_PEDIDO_MODE_LABELS: List[str] = list(PEDIDO_MODE_LABELS.values())
_LABEL_TO_PEDIDO_MODE: Dict[str, str] = {v: k for k, v in PEDIDO_MODE_LABELS.items()}

PLANNER_MODULE = "Planejador"

# Valores iniciais do Planejador — eram fixos no código da tela.
PLANNER_DEFAULTS: Dict[str, object] = {
    "report_mode_default": "full",
    "mirror_jpg_width_mode": "17",
    "mirror_jpg_width_cm_custom": 17.0,
    "mirror_jpg_dpi": 300,
    "use_printer_jpg_path_default": False,
    "dpi": 150.0,
    "axis": "altura",
    "setup_min": 2.0,
    "mode": "tecido",
    "gap_between": 1.0,
    "gap_endroll": 1.0,
    "gap_files": 0.0,
    "roll_other": 60.0,
    "auto_fabric_order": True,
    "scrap_bleed_cm": 5.0,
}

SavedCallback = Callable[[str], None]


def load_planner_cfg() -> dict:
    return read_module_cfg(PLANNER_MODULE, dict(PLANNER_DEFAULTS))


def save_planner_cfg(cfg: dict) -> None:
    write_module_cfg(PLANNER_MODULE, cfg)


def _num(text: str, label: str, *, minimum: float = 0.0, maximum: Optional[float] = None) -> float:
    try:
        value = float((text or "").replace(",", ".").strip())
    except ValueError:
        raise ValueError(f"{label}: informe um número.")
    if value < minimum or (maximum is not None and value > maximum):
        limit = f"entre {minimum:g} e {maximum:g}" if maximum is not None else f"a partir de {minimum:g}"
        raise ValueError(f"{label}: use um valor {limit}.")
    return value


def _fmt(value: object) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _export_defaults_rows(parent: ttk.Frame, cfg: dict, row: int) -> Callable[[], dict]:
    """Linhas 'Modo do PDF' e 'JPG espelhado' (iguais em Planejador e Operação)."""
    var_mode = tk.StringVar(value=str(cfg.get("report_mode_default", "full")))
    var_jpg = tk.StringVar(value=str(cfg.get("mirror_jpg_width_mode", "17")))
    var_custom = tk.StringVar(value=_fmt(cfg.get("mirror_jpg_width_cm_custom", 17.0)))

    ttk.Label(parent, text="Modo do PDF").grid(row=row, column=0, sticky="w", pady=4)
    mode_row = ttk.Frame(parent)
    mode_row.grid(row=row, column=1, columnspan=3, sticky="w", pady=4)
    ttk.Radiobutton(mode_row, text="Completo", value="full", variable=var_mode).pack(side="left")
    ttk.Radiobutton(mode_row, text="Resumido", value="summary", variable=var_mode).pack(
        side="left", padx=(10, 0)
    )

    ttk.Label(parent, text="JPG espelhado").grid(row=row + 1, column=0, sticky="w", pady=4)
    jpg_row = ttk.Frame(parent)
    jpg_row.grid(row=row + 1, column=1, columnspan=3, sticky="w", pady=4)
    for text, value in (("17 cm", "17"), ("21 cm", "21"), ("Personalizado", "custom")):
        ttk.Radiobutton(jpg_row, text=text, value=value, variable=var_jpg).pack(side="left", padx=(0, 10))
    ent_custom = ttk.Entry(jpg_row, textvariable=var_custom, width=6)
    ent_custom.pack(side="left")
    ttk.Label(jpg_row, text="cm").pack(side="left", padx=(4, 0))

    def _custom_state(*_):
        ent_custom.configure(state="normal" if var_jpg.get() == "custom" else "disabled")

    var_jpg.trace_add("write", _custom_state)
    _custom_state()

    var_printer_path = tk.BooleanVar(value=bool(cfg.get("use_printer_jpg_path_default", False)))
    ttk.Checkbutton(
        parent, text="Usar pasta/arquivo da impressora para o JPG espelhado",
        variable=var_printer_path,
    ).grid(row=row + 2, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def collect() -> dict:
        out = {
            "report_mode_default": var_mode.get(),
            "mirror_jpg_width_mode": var_jpg.get(),
            "use_printer_jpg_path_default": bool(var_printer_path.get()),
        }
        if var_jpg.get() == "custom":
            out["mirror_jpg_width_cm_custom"] = _num(var_custom.get(), "Largura do JPG", minimum=8, maximum=40)
        else:
            out["mirror_jpg_width_cm_custom"] = float(var_jpg.get())
        return out

    return collect


# ---------------------------------------------------------------------------
# Editor visual de um padrão de impressão (modal) — orquestra o fluxo
# "exemplos -> estrutura sugerida -> confirmação -> regex" descrito em
# core/print_pattern.py (modelo/compilador) e
# core/print_pattern_analyzer.py (sugestão a partir de exemplos). A regra de
# negócio mora nesses dois módulos; esta função só monta a tela e chama
# `on_save` com o dict final.
# ---------------------------------------------------------------------------
def open_pattern_editor(
    parent: tk.Misc,
    *,
    rule: Optional[dict],
    other_rules: List[dict],
    on_save: Callable[[dict], None],
) -> None:
    is_new = rule is None
    base_rule: dict = dict(rule) if rule else {
        "id": None,
        "name": "",
        "pattern": "",
        "match_mode": MATCH_MODE_START,
        "components": None,
        "examples": [],
        "custom_regex": False,
        "active": True,
    }

    # Uma regra "simples" é um único bloco de texto fixo (sem regex
    # personalizada) — é o que o modo básico do editor produz. Uma regra
    # existente nesse formato reabre em modo básico; qualquer outra (com
    # mais blocos, tecido, data etc., ou regex manual) reabre em modo
    # avançado, pra não arriscar perder estrutura que o modo básico não
    # consegue representar.
    _raw_components = base_rule.get("components") or []
    _is_simple_rule = (
        isinstance(_raw_components, list) and len(_raw_components) == 1
        and isinstance(_raw_components[0], dict) and _raw_components[0].get("kind") == KIND_FIXED
        and not base_rule.get("custom_regex")
    )
    initial_keyword = str(_raw_components[0].get("value") or "") if _is_simple_rule else ""
    initial_advanced = bool(rule) and not _is_simple_rule

    dlg = tk.Toplevel(parent)
    dlg.title("Novo padrão de impressão" if is_new else f"Editar padrão: {base_rule.get('name') or ''}")
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    dlg.geometry("840x720")
    dlg.minsize(760, 560)

    frm = ttk.Frame(dlg, padding=14)
    frm.pack(fill="both", expand=True)

    dialog_header(
        frm,
        "Novo padrão de impressão" if is_new else "Editar padrão de impressão",
        "Modo simples: uma palavra-chave que precisa aparecer no nome do arquivo. Modo avançado: "
        "dê exemplos de nome de arquivo e o Nexor sugere a estrutura e gera a regex.",
    ).pack(fill="x", pady=(0, 10))

    # ---- estado ----
    examples: List[str] = list(base_rule.get("examples") or [])
    rows: List[dict] = []  # cada item: {"role": "content"/"sep", ...vars...}
    custom_state = {"manual": bool(base_rule.get("custom_regex")) or not base_rule.get("components")}
    analyzer_warnings: List[str] = []
    suppress_trace = {"on": False}
    fabric_cache: Dict[str, object] = {}

    def fabric_names():
        if "value" not in fabric_cache:
            fabric_cache["value"] = known_fabric_names_with_aliases()
        return fabric_cache["value"]

    # ---- topo: tipo + correspondência ----
    top = ttk.Frame(frm)
    top.pack(fill="x")
    ttk.Label(top, text="Tipo:").grid(row=0, column=0, sticky="w")
    var_name = tk.StringVar(value=base_rule.get("name", ""))
    ttk.Entry(top, textvariable=var_name, width=24).grid(row=0, column=1, sticky="w", padx=(6, 18))

    ttk.Label(top, text="Correspondência:").grid(row=0, column=2, sticky="w")
    var_mode_label = tk.StringVar(value=MATCH_MODE_LABELS.get(base_rule.get("match_mode", MATCH_MODE_START), _MODE_LABELS[0]))
    cb_mode = ttk.Combobox(top, values=_MODE_LABELS, textvariable=var_mode_label, state="readonly", width=16)
    cb_mode.grid(row=0, column=3, sticky="w", padx=(6, 0))

    var_warn_duplicate = tk.BooleanVar(value=bool(base_rule.get("warn_duplicate", True)))
    ttk.Checkbutton(
        top, text="Avisar duplicidade entre rolos (mesmo pedido + tecido já impresso)",
        variable=var_warn_duplicate,
    ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

    ttk.Label(top, text="Nome do pedido:").grid(row=2, column=0, sticky="w", pady=(8, 0))
    var_pedido_mode_label = tk.StringVar(
        value=PEDIDO_MODE_LABELS.get(base_rule.get("pedido_mode", PEDIDO_MODE_AUTO), _PEDIDO_MODE_LABELS[0])
    )
    cb_pedido_mode = ttk.Combobox(
        top, values=_PEDIDO_MODE_LABELS, textvariable=var_pedido_mode_label, state="readonly", width=26
    )
    cb_pedido_mode.grid(row=2, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(8, 0))

    var_pedido_fixed = tk.StringVar(value=str(base_rule.get("pedido_fixed") or ""))
    entry_pedido_fixed = ttk.Entry(top, textvariable=var_pedido_fixed, width=20)

    def _sync_pedido_fixed_entry(_evt=None):
        if _LABEL_TO_PEDIDO_MODE.get(var_pedido_mode_label.get()) == PEDIDO_MODE_FIXED:
            entry_pedido_fixed.grid(row=2, column=3, sticky="w", padx=(6, 0), pady=(8, 0))
        else:
            entry_pedido_fixed.grid_forget()

    cb_pedido_mode.bind("<<ComboboxSelected>>", _sync_pedido_fixed_entry)
    _sync_pedido_fixed_entry()

    ttk.Label(
        top,
        text='Como identificar o pedido pra arquivos deste tipo — "Nome fixo" usa sempre o mesmo '
        'nome (ex.: Reposição -> "Variados") em vez de tentar ler do nome do arquivo.',
        style="Muted.TLabel", wraplength=780, justify="left",
    ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))

    # ---- modo simples vs avançado ----
    mode_state = {"advanced": initial_advanced}
    btn_mode = ttk.Button(frm, text="")
    btn_mode.pack(anchor="w", pady=(10, 0))

    dynamic_area = ttk.Frame(frm)
    dynamic_area.pack(fill="x", pady=(8, 0))

    # ---- simples ----
    simple_box = ttk.LabelFrame(dynamic_area, text="Padrão simples", padding=10)
    ttk.Label(
        simple_box,
        text="Se o nome do arquivo combinar com esta palavra-chave (conforme a Correspondência "
        "acima), o Tipo é aplicado. Para padrões com partes variáveis (tecido, data, número...), "
        "use o modo avançado.",
        style="Muted.TLabel", wraplength=780, justify="left",
    ).pack(anchor="w")
    kw_row = ttk.Frame(simple_box)
    kw_row.pack(fill="x", pady=(8, 0))
    ttk.Label(kw_row, text="Palavra-chave:").pack(side="left")
    var_keyword = tk.StringVar(value=initial_keyword)
    ttk.Entry(kw_row, textvariable=var_keyword, width=40).pack(
        side="left", padx=(6, 0), fill="x", expand=True
    )

    # ---- exemplos ----
    ex_box = ttk.LabelFrame(dynamic_area, text="Exemplos de nome de arquivo", padding=10)

    lb_examples = tk.Listbox(ex_box, height=4, exportselection=False)
    lb_examples.pack(fill="x")

    def refresh_examples_listbox():
        lb_examples.delete(0, tk.END)
        for ex in examples:
            lb_examples.insert(tk.END, ex)

    refresh_examples_listbox()

    ex_form = ttk.Frame(ex_box)
    ex_form.pack(fill="x", pady=(6, 0))
    var_new_example = tk.StringVar()
    ttk.Entry(ex_form, textvariable=var_new_example).pack(side="left", fill="x", expand=True)

    def add_example():
        text = var_new_example.get().strip()
        if not text:
            return
        examples.append(text)
        var_new_example.set("")
        refresh_examples_listbox()
        if not rows:
            reanalyze(force=True)
        else:
            update_preview()

    def remove_example():
        sel = lb_examples.curselection()
        if not sel:
            messagebox.showwarning("Padrão de impressão", "Selecione um exemplo na lista.")
            return
        del examples[sel[0]]
        refresh_examples_listbox()
        update_preview()

    ttk.Button(ex_form, text="Adicionar exemplo", command=add_example).pack(side="left", padx=(6, 0))
    ttk.Button(ex_form, text="Remover exemplo", command=remove_example).pack(side="left", padx=(6, 0))

    # ---- estrutura identificada ----
    struct_box = ttk.LabelFrame(dynamic_area, text="Estrutura identificada", padding=10)
    rows_frame = ttk.Frame(struct_box)
    rows_frame.pack(fill="x")
    lbl_struct_empty = ttk.Label(
        struct_box,
        text="Adicione um exemplo de nome de arquivo para ver a estrutura sugerida.",
        style="Muted.TLabel",
    )

    def render_rows():
        for child in rows_frame.winfo_children():
            child.destroy()
        if not rows:
            lbl_struct_empty.pack(anchor="w")
            return
        lbl_struct_empty.pack_forget()
        for i, row in enumerate(rows):
            line = ttk.Frame(rows_frame)
            line.pack(fill="x", pady=2)
            if row["role"] == "sep":
                ttk.Label(line, text="separador", style="Muted.TLabel", width=16).pack(side="left")
                cb = ttk.Combobox(line, values=_SEP_LABELS, textvariable=row["sep_var"],
                                   state="readonly", width=14)
                cb.pack(side="left", padx=(6, 0))
                continue

            sample_txt = row["sample"] if len(row["sample"]) <= 28 else row["sample"][:25] + "..."
            ttk.Label(line, text=f'"{sample_txt}"', width=22).pack(side="left")
            cb = ttk.Combobox(line, values=_BLOCK_KIND_LABELS, textvariable=row["kind_var"],
                               state="readonly", width=20)
            cb.pack(side="left", padx=(6, 0))

            value_entry = ttk.Entry(line, textvariable=row["value_var"], width=20)

            def sync_value_entry(_evt=None, row=row, entry=value_entry):
                if _LABEL_TO_KIND.get(row["kind_var"].get()) == KIND_FIXED:
                    entry.pack(side="left", padx=(6, 0))
                else:
                    entry.pack_forget()

            row["kind_var"].trace_add("write", lambda *_a, f=sync_value_entry: (f(), on_row_changed()))
            row["value_var"].trace_add("write", lambda *_a: on_row_changed())
            sync_value_entry()

            note_txt = row.get("note") or (f"confiança: {row.get('confidence')}" if row.get("confidence") else "")
            if note_txt:
                ttk.Label(line, text=note_txt, style="Muted.TLabel", wraplength=260, justify="left").pack(
                    side="left", padx=(10, 0)
                )
        for row in rows:
            if row["role"] == "sep":
                row["sep_var"].trace_add("write", lambda *_a: on_row_changed())

    def on_row_changed(*_a):
        if not suppress_trace["on"]:
            update_preview()

    def components_from_rows() -> List[Component]:
        out: List[Component] = []
        for row in rows:
            if row["role"] == "sep":
                char = _LABEL_TO_SEP.get(row["sep_var"].get(), "-")
                out.append(Component(kind=KIND_SEPARATOR, value=char))
            else:
                kind = _LABEL_TO_KIND.get(row["kind_var"].get(), "texto_variavel")
                value = row["value_var"].get().strip() if kind == KIND_FIXED else None
                out.append(Component(kind=kind, value=value))
        return out

    def build_rows_from_analysis(result) -> None:
        rows.clear()
        cursor = 0
        for comp in result.components:
            if comp.kind == KIND_SEPARATOR:
                rows.append({
                    "role": "sep",
                    "sep_var": tk.StringVar(value=SEPARATOR_LABELS.get(comp.value or "-", _SEP_LABELS[0])),
                })
            else:
                sug = result.blocks[cursor]
                cursor += 1
                rows.append({
                    "role": "content",
                    "sample": sug.sample_text,
                    "kind_var": tk.StringVar(value=KIND_LABELS.get(sug.kind, sug.kind)),
                    "value_var": tk.StringVar(value=sug.value or ""),
                    "confidence": sug.confidence,
                    "note": sug.note,
                })

    def build_rows_from_components(components: List[dict]) -> None:
        rows.clear()
        for raw in components:
            kind = raw.get("kind")
            if kind == KIND_SEPARATOR:
                rows.append({
                    "role": "sep",
                    "sep_var": tk.StringVar(value=SEPARATOR_LABELS.get(raw.get("value") or "-", _SEP_LABELS[0])),
                })
            else:
                rows.append({
                    "role": "content",
                    "sample": raw.get("value") or KIND_LABELS.get(kind, kind or ""),
                    "kind_var": tk.StringVar(value=KIND_LABELS.get(kind, kind or "")),
                    "value_var": tk.StringVar(value=raw.get("value") or ""),
                    "confidence": None,
                    "note": None,
                })

    # ---- avançado (regex) ----
    adv_state = {"open": False}
    adv_toggle_var = tk.BooleanVar(value=False)
    adv_box = ttk.Frame(dynamic_area)
    var_regex = tk.StringVar(value=base_rule.get("pattern", ""))
    lbl_custom_notice = ttk.Label(adv_box, text="", style="Muted.TLabel", wraplength=760, justify="left")

    def set_regex_programmatically(value: str) -> None:
        suppress_trace["on"] = True
        var_regex.set(value)
        suppress_trace["on"] = False

    def on_regex_box_changed(*_a):
        if suppress_trace["on"]:
            return
        if not custom_state["manual"]:
            custom_state["manual"] = True
            lbl_custom_notice.configure(
                text="Regex personalizada: a partir de agora, mudanças na estrutura visual não são "
                "aplicadas automaticamente. Use \"Reanalisar exemplos\" para substituí-la pela regex gerada."
            )
        refresh_preview_only()

    var_regex.trace_add("write", on_regex_box_changed)

    def toggle_advanced():
        adv_state["open"] = not adv_state["open"]
        if adv_state["open"]:
            adv_box.pack(fill="x", pady=(12, 0))
            btn_advanced.configure(text="▲ Ocultar regex")
        else:
            adv_box.pack_forget()
            btn_advanced.configure(text="Editar regex manualmente ▼")

    btn_advanced = ttk.Button(dynamic_area, text="Editar regex manualmente ▼", command=toggle_advanced)

    ttk.Label(adv_box, text="Regex gerada:").pack(anchor="w")
    ttk.Entry(adv_box, textvariable=var_regex).pack(fill="x", pady=(2, 4))
    lbl_custom_notice.pack(anchor="w")

    # ---- prévia ----
    preview_box = ttk.LabelFrame(frm, text="Prévia da regra", padding=10)
    preview_box.pack(fill="x", pady=(12, 0))
    var_preview = tk.StringVar()
    ttk.Label(preview_box, textvariable=var_preview, justify="left", wraplength=780).pack(anchor="w")

    test_row = ttk.Frame(preview_box)
    test_row.pack(fill="x", pady=(8, 0))
    ttk.Label(test_row, text="Testar nome de arquivo:").pack(side="left")
    var_test_name = tk.StringVar()
    ttk.Entry(test_row, textvariable=var_test_name).pack(side="left", fill="x", expand=True, padx=6)
    var_test_result = tk.StringVar()
    ttk.Label(preview_box, textvariable=var_test_result, justify="left", wraplength=780).pack(
        anchor="w", pady=(4, 0)
    )

    def preview_examples() -> List[str]:
        if not mode_state["advanced"]:
            kw = var_keyword.get().strip()
            return [kw] if kw else []
        return examples

    def current_pattern() -> str:
        mode = _LABEL_TO_MODE.get(var_mode_label.get(), MATCH_MODE_START)
        if not mode_state["advanced"]:
            kw = var_keyword.get().strip()
            if not kw:
                return ""
            return build_pattern([Component(kind=KIND_FIXED, value=kw)], mode, fabric_names=fabric_names())
        if custom_state["manual"]:
            return var_regex.get().strip()
        comps = components_from_rows()
        if not comps:
            return ""
        return build_pattern(comps, mode, fabric_names=fabric_names())

    def current_mode() -> str:
        return _LABEL_TO_MODE.get(var_mode_label.get(), MATCH_MODE_START)

    def test_against(text: str, pattern: str) -> bool:
        if not pattern or not text.strip():
            return False
        doc = strip_extension(text).strip()
        try:
            if current_mode() == MATCH_MODE_CONTAINS:
                return bool(re.search(pattern, doc, re.IGNORECASE))
            return bool(re.match(pattern, doc, re.IGNORECASE))
        except re.error:
            return False

    def run_tester(*_a):
        text = var_test_name.get()
        if not text.strip():
            var_test_result.set("")
            return
        pattern = current_pattern()
        ok = test_against(text, pattern)
        msg = ("✓ combina com esta regra" if ok else "✗ não combina com esta regra")
        others_hit = detect_conflicts([text], other_rules, fabric_names=fabric_names()).get(text, [])
        if others_hit:
            msg += f"\nAtenção: também combina com: {', '.join(others_hit)} (a ordem da lista decide a prioridade)."
        var_test_result.set(msg)

    var_test_name.trace_add("write", run_tester)

    def refresh_preview_only():
        pattern = current_pattern()
        lines = []
        if not pattern:
            lines.append(
                "Informe a palavra-chave para ver a prévia." if not mode_state["advanced"]
                else "Defina a estrutura (ou a regex, no modo avançado) para ver a prévia."
            )
        else:
            for ex in preview_examples():
                mark = "✓" if test_against(ex, pattern) else "✗"
                lines.append(f"{mark} {ex}")
            lines.append(f"Regex: {pattern}")
        conflicts = detect_conflicts(preview_examples(), other_rules, fabric_names=fabric_names())
        for ex, names in conflicts.items():
            lines.append(f'Atenção: "{ex}" também combina com: {", ".join(names)}.')
        if mode_state["advanced"]:
            for w in analyzer_warnings:
                lines.append(f"Aviso: {w}")
        var_preview.set("\n".join(lines))
        run_tester()

    def update_preview():
        if mode_state["advanced"] and not custom_state["manual"]:
            pattern = current_pattern()
            if pattern:
                set_regex_programmatically(pattern)
        refresh_preview_only()

    var_keyword.trace_add("write", lambda *_a: update_preview())

    cb_mode.bind("<<ComboboxSelected>>", lambda _e: update_preview())

    def reanalyze(force: bool = False):
        if not examples:
            messagebox.showwarning("Padrão de impressão", "Informe ao menos um exemplo de nome de arquivo.")
            return
        if not force and custom_state["manual"] and rows:
            if not messagebox.askyesno(
                "Regex personalizada",
                "Esta regra tem uma regex personalizada. Reanalisar os exemplos vai "
                "substituí-la pela regex gerada automaticamente a partir da estrutura visual.\n\n"
                "Continuar?",
            ):
                return
        result = analyze_examples(examples, fabric_names=fabric_names())
        build_rows_from_analysis(result)
        custom_state["manual"] = False
        lbl_custom_notice.configure(text="")
        var_mode_label.set(MATCH_MODE_LABELS.get(result.suggested_match_mode, _MODE_LABELS[0]))
        analyzer_warnings[:] = result.warnings
        render_rows()
        update_preview()

    ttk.Button(struct_box, text="Reanalisar exemplos", command=lambda: reanalyze(force=False)).pack(
        anchor="e", pady=(8, 0)
    )

    def apply_mode_visibility():
        for w in (simple_box, ex_box, struct_box, btn_advanced, adv_box):
            w.pack_forget()
        if mode_state["advanced"]:
            ex_box.pack(fill="x", pady=(12, 0))
            struct_box.pack(fill="x", pady=(12, 0))
            btn_advanced.pack(anchor="w", pady=(10, 0))
            if adv_state["open"]:
                adv_box.pack(fill="x", pady=(12, 0))
            btn_mode.configure(text="◂ Modo simples (palavra-chave)")
        else:
            simple_box.pack(fill="x")
            btn_mode.configure(text="Modo avançado ▸ (exemplos e estrutura)")
        update_preview()

    def toggle_mode():
        going_advanced = not mode_state["advanced"]
        if going_advanced:
            kw = var_keyword.get().strip()
            if kw and not examples:
                examples.append(kw)
                refresh_examples_listbox()
            if kw and not rows:
                reanalyze(force=True)
        mode_state["advanced"] = going_advanced
        apply_mode_visibility()

    btn_mode.configure(command=toggle_mode)

    # ---- estado inicial ----
    if base_rule.get("components"):
        build_rows_from_components(base_rule["components"])
    elif examples:
        try:
            result = analyze_examples(examples, fabric_names=fabric_names())
            if not custom_state["manual"]:
                build_rows_from_analysis(result)
                analyzer_warnings[:] = result.warnings
        except Exception:
            pass
    if custom_state["manual"] and not rule:
        pass
    elif custom_state["manual"]:
        lbl_custom_notice.configure(
            text="Esta regra não tem estrutura visual (regex avançada ou migrada de uma versão antiga). "
            "Você pode informar exemplos e clicar em \"Reanalisar exemplos\" para reconstruí-la "
            "visualmente — isso vai substituir a regex atual."
        )
    render_rows()
    apply_mode_visibility()

    # ---- rodapé ----
    footer = ttk.Frame(frm)
    footer.pack(fill="x", pady=(14, 0))

    def on_save_clicked():
        name = var_name.get().strip()
        if not name:
            messagebox.showwarning("Padrão de impressão", "Informe o tipo.")
            return
        if name == FALLBACK_TYPE:
            messagebox.showwarning(
                "Padrão de impressão", f"'{FALLBACK_TYPE}' é reservado para o que não combinar com nenhuma regra."
            )
            return

        pedido_mode = _LABEL_TO_PEDIDO_MODE.get(var_pedido_mode_label.get(), PEDIDO_MODE_AUTO)
        pedido_fixed = var_pedido_fixed.get().strip()
        if pedido_mode == PEDIDO_MODE_FIXED and not pedido_fixed:
            messagebox.showwarning(
                "Padrão de impressão", 'Informe o nome fixo do pedido, ou escolha "Detectar pelo nome do arquivo".'
            )
            return

        mode = current_mode()
        if not mode_state["advanced"]:
            keyword = var_keyword.get().strip()
            if not keyword:
                messagebox.showwarning("Padrão de impressão", "Informe a palavra-chave.")
                return
            comp = Component(kind=KIND_FIXED, value=keyword)
            pattern = build_pattern([comp], mode, fabric_names=fabric_names())
            try:
                validate_pattern(pattern)
            except ValueError as e:
                messagebox.showerror("Padrão de impressão", str(e))
                return
            components_payload = components_to_list([comp])
            rule_examples = [keyword]
            is_custom = False
        elif custom_state["manual"]:
            pattern = var_regex.get().strip()
            if not pattern:
                messagebox.showwarning("Padrão de impressão", "Informe a regex (modo avançado) ou volte ao modo visual.")
                return
            try:
                validate_pattern(pattern)
            except ValueError as e:
                messagebox.showerror("Padrão de impressão", str(e))
                return
            components_payload = None
            rule_examples = list(examples)
            is_custom = True
        else:
            comps = components_from_rows()
            if not comps:
                messagebox.showwarning(
                    "Padrão de impressão", "Informe ao menos um exemplo e confirme a estrutura antes de salvar."
                )
                return
            pattern = build_pattern(comps, mode, fabric_names=fabric_names())
            try:
                validate_pattern(pattern)
            except ValueError as e:
                messagebox.showerror("Padrão de impressão", str(e))
                return
            components_payload = components_to_list(comps)
            rule_examples = list(examples)
            is_custom = False

        conflicts = detect_conflicts(rule_examples, other_rules, fabric_names=fabric_names())
        if conflicts:
            lines = [f'- "{ex}": também combina com {", ".join(names)}' for ex, names in conflicts.items()]
            if not messagebox.askyesno(
                "Possível conflito entre regras",
                "Esta regra pode entrar em conflito com outras já cadastradas:\n\n"
                + "\n".join(lines)
                + "\n\nA ordem na lista de regras decide quem tem prioridade (a de cima vence). "
                "Deseja salvar mesmo assim?",
            ):
                return

        final_rule = {
            "id": base_rule.get("id") or new_rule_id(),
            "name": name,
            "pattern": pattern,
            "match_mode": mode,
            "components": components_payload,
            "examples": rule_examples,
            "custom_regex": is_custom,
            "active": bool(base_rule.get("active", True)),
            "warn_duplicate": bool(var_warn_duplicate.get()),
            "pedido_mode": pedido_mode,
            "pedido_fixed": pedido_fixed,
        }
        on_save(final_rule)
        dlg.destroy()

    ttk.Button(footer, text="Salvar padrão", style="Accent.TButton", command=on_save_clicked).pack(side="left")
    ttk.Button(footer, text="Cancelar", command=dlg.destroy).pack(side="left", padx=(8, 0))


# ---------------------------------------------------------------------------
# Tipos de impressão
# ---------------------------------------------------------------------------
def build_print_types_section(parent: tk.Misc, on_saved: SavedCallback) -> ttk.LabelFrame:
    box = card(parent, "Tipos de impressão · identificação pelo nome do arquivo", padding=14)

    ttk.Label(
        box,
        text=(
            "Cada regra compara um padrão (regex) com o começo do nome do arquivo; a primeira "
            "que combinar define o tipo. Sem regra correspondente, o arquivo fica como "
            f"'{FALLBACK_TYPE}' e pode receber um subtipo manual na Operação (Editar tipo)."
        ),
        style="Muted.TLabel", wraplength=860, justify="left",
    ).pack(anchor="w", pady=(0, 10))

    cfg = load_operacao_cfg()
    rules: List[dict] = normalize_rules(cfg.get("print_type_rules", DEFAULT_RULES))
    subtypes: List[str] = normalize_subtypes(cfg.get("print_type_subtypes", DEFAULT_SUBTYPES))

    body = ttk.Frame(box)
    body.pack(fill="x")
    body.columnconfigure(0, weight=3)
    body.columnconfigure(1, weight=1)

    # ---- Regras ----
    rules_col = ttk.Frame(body)
    rules_col.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
    ttk.Label(
        rules_col, text="Regras automáticas (a ordem importa) · duplo clique para editar",
        style="PanelStrong.TLabel",
    ).pack(anchor="w")

    tree = ttk.Treeview(rules_col, columns=("name", "pattern", "origem", "dup", "pedido"), show="headings", height=6)
    tree.heading("name", text="Tipo")
    tree.column("name", width=120, anchor="w")
    tree.heading("pattern", text="Padrão (regex)")
    tree.column("pattern", width=220, anchor="w")
    tree.heading("origem", text="Origem")
    tree.column("origem", width=90, anchor="w")
    tree.heading("dup", text="Avisa duplicidade")
    tree.column("dup", width=100, anchor="center")
    tree.heading("pedido", text="Nome do pedido")
    tree.column("pedido", width=130, anchor="w")
    tree.pack(fill="x", pady=(6, 6))

    selected: Dict[str, Optional[int]] = {"value": None}

    def _origem_label(r: dict) -> str:
        return "Regex avançada" if (r.get("custom_regex") or not r.get("components")) else "Visual"

    def refresh_rules(select_index: Optional[int] = None) -> None:
        tree.delete(*tree.get_children())
        for i, r in enumerate(rules):
            dup_txt = "Sim" if r.get("warn_duplicate", True) else "Não"
            if r.get("pedido_mode") == PEDIDO_MODE_FIXED:
                pedido_txt = f'Fixo: "{r.get("pedido_fixed") or ""}"'
            else:
                pedido_txt = "Arquivo"
            tree.insert(
                "", "end", iid=str(i),
                values=(r["name"], r["pattern"], _origem_label(r), dup_txt, pedido_txt),
            )
        if select_index is not None and 0 <= select_index < len(rules):
            tree.selection_set(str(select_index))
            selected["value"] = select_index
        update_test()

    def on_select(_evt=None) -> None:
        sel = tree.selection()
        selected["value"] = int(sel[0]) if sel else None

    tree.bind("<<TreeviewSelect>>", on_select)

    def open_new():
        open_pattern_editor(
            rules_col,
            rule=None,
            other_rules=list(rules),
            on_save=lambda final: (rules.append(final), refresh_rules(select_index=len(rules) - 1)),
        )

    def open_edit():
        idx = selected["value"]
        if idx is None:
            messagebox.showwarning("Tipos de impressão", "Selecione uma regra na lista.")
            return
        others = [r for j, r in enumerate(rules) if j != idx]
        open_pattern_editor(
            rules_col,
            rule=rules[idx],
            other_rules=others,
            on_save=lambda final, idx=idx: (rules.__setitem__(idx, final), refresh_rules(select_index=idx)),
        )

    tree.bind("<Double-1>", lambda _e: open_edit())

    def remove() -> None:
        idx = selected["value"]
        if idx is None:
            messagebox.showwarning("Tipos de impressão", "Selecione uma regra na lista.")
            return
        del rules[idx]
        selected["value"] = None
        refresh_rules()

    def move(delta: int) -> None:
        idx = selected["value"]
        if idx is None or not 0 <= idx + delta < len(rules):
            return
        rules[idx], rules[idx + delta] = rules[idx + delta], rules[idx]
        refresh_rules(select_index=idx + delta)

    def restore_defaults() -> None:
        rules[:] = normalize_rules(DEFAULT_RULES)
        selected["value"] = None
        refresh_rules()

    rule_btns = ttk.Frame(rules_col)
    rule_btns.pack(fill="x", pady=(6, 0))
    for text, cmd in (
        ("Nova", open_new),
        ("Remover", remove),
        ("▲ Subir", lambda: move(-1)),
        ("▼ Descer", lambda: move(1)),
        ("Restaurar padrão", restore_defaults),
    ):
        ttk.Button(rule_btns, text=text, command=cmd).pack(side="left", padx=(0, 6))

    ttk.Label(
        rules_col,
        text=(
            "Clique em \"Nova\" e informe exemplos de nome de arquivo — o Nexor sugere a estrutura "
            "e gera a regex. A edição manual da regex continua disponível no modo avançado do editor.\n"
            "Padrão de fábrica — Pedido: dia-mês no início, ex. \"16-10 - Dryfit - Cliente\".  "
            "Reposição: inicial do operador + número, ex. \"N2 - Aeroready\"."
        ),
        style="Muted.TLabel", wraplength=600, justify="left",
    ).pack(anchor="w", pady=(8, 0))

    # Testador: mostra na hora qual tipo um nome de arquivo recebe — e avisa
    # quando mais de uma regra combina (a ordem decide quem vence).
    test_row = ttk.Frame(rules_col)
    test_row.pack(fill="x", pady=(10, 0))
    ttk.Label(test_row, text="Testar nome de arquivo:").pack(side="left")
    var_test = tk.StringVar(value="16-10 - Dryfit - Primos e Amigos 3 (1).jpeg")
    ttk.Entry(test_row, textvariable=var_test).pack(side="left", fill="x", expand=True, padx=6)

    var_result = tk.StringVar()
    ttk.Label(rules_col, textvariable=var_result, style="PanelStrong.TLabel", wraplength=600, justify="left").pack(
        anchor="w", pady=(4, 0)
    )

    def update_test(*_):
        detail = classify_with_detail(var_test.get(), rules)
        msg = f"→ {detail['type']}"
        if detail["also_matches"]:
            others = ", ".join(f'"{r["name"]}"' for r in detail["also_matches"])
            msg += (
                f"\nAtenção: este nome também combina com: {others}.\n"
                f"Será classificado como \"{detail['type']}\" porque está acima na prioridade."
            )
        var_result.set(msg)

    var_test.trace_add("write", update_test)

    # ---- Subtipos manuais ----
    sub_col = ttk.Frame(body)
    sub_col.grid(row=0, column=1, sticky="nsew")
    ttk.Label(sub_col, text=f"Subtipos manuais ('{FALLBACK_TYPE}')", style="PanelStrong.TLabel").pack(anchor="w")
    lb = tk.Listbox(sub_col, height=6, exportselection=False)
    lb.pack(fill="x", pady=(6, 6))

    def refresh_subtypes() -> None:
        lb.delete(0, tk.END)
        for s in subtypes:
            lb.insert(tk.END, s)

    var_sub = tk.StringVar()
    ttk.Entry(sub_col, textvariable=var_sub).pack(fill="x")

    def add_subtype() -> None:
        name = var_sub.get().strip()
        if name and name not in subtypes and name != FALLBACK_TYPE:
            subtypes.append(name)
            refresh_subtypes()
        var_sub.set("")

    def remove_subtype() -> None:
        sel = lb.curselection()
        if not sel:
            messagebox.showwarning("Tipos de impressão", "Selecione um subtipo na lista.")
            return
        del subtypes[sel[0]]
        refresh_subtypes()

    sub_btns = ttk.Frame(sub_col)
    sub_btns.pack(fill="x", pady=(6, 0))
    ttk.Button(sub_btns, text="Adicionar", command=add_subtype).pack(side="left")
    ttk.Button(sub_btns, text="Remover", command=remove_subtype).pack(side="left", padx=(6, 0))

    def save() -> bool:
        current = load_operacao_cfg()
        current["print_type_rules"] = [dict(r) for r in rules]
        current["print_type_subtypes"] = list(subtypes)
        save_operacao_cfg(current)
        on_saved("Operação")
        return True

    refresh_rules()
    refresh_subtypes()
    box.save = save
    return box


# ---------------------------------------------------------------------------
# Operação
# ---------------------------------------------------------------------------
def build_operacao_section(parent: tk.Misc, on_saved: SavedCallback) -> ttk.LabelFrame:
    box = card(parent, "Operação · padrões de exportação e arquivos de espaço", padding=14)
    cfg = load_operacao_cfg()

    grid = ttk.Frame(box)
    grid.pack(fill="x")
    collect_export = _export_defaults_rows(grid, cfg, 0)

    ttk.Label(box, text="Arquivos de espaço", style="PanelStrong.TLabel").pack(anchor="w", pady=(12, 0))
    ttk.Label(
        box,
        text=(
            "Nomes de arquivo/job que a máquina imprime como avanço entre tecidos. Ao importar, "
            "esses logs viram ESPAÇO e não entram em \"Pedidos no rolo\"; o nome de exibição "
            "aparece nas listagens."
        ),
        style="Muted.TLabel", wraplength=860, justify="left",
    ).pack(anchor="w", pady=(2, 6))

    entries: List[dict] = normalize_space_entries(cfg.get("space_filenames", []))

    space_row = ttk.Frame(box)
    space_row.pack(fill="x")
    tree = ttk.Treeview(space_row, columns=("filename", "display_name"), show="headings", height=4)
    tree.heading("filename", text="Arquivo/job")
    tree.column("filename", width=260, anchor="w")
    tree.heading("display_name", text="Nome de exibição")
    tree.column("display_name", width=180, anchor="w")
    tree.pack(side="left", fill="x", expand=True)

    form = ttk.Frame(space_row)
    form.pack(side="left", fill="y", padx=(12, 0))
    ttk.Label(form, text="Arquivo/job:").grid(row=0, column=0, sticky="w")
    var_file = tk.StringVar()
    ttk.Entry(form, textvariable=var_file, width=24).grid(row=0, column=1, padx=6, pady=2)
    ttk.Label(form, text="Exibição:").grid(row=1, column=0, sticky="w")
    var_display = tk.StringVar()
    ttk.Entry(form, textvariable=var_display, width=24).grid(row=1, column=1, padx=6, pady=2)

    selected: Dict[str, Optional[int]] = {"value": None}

    def refresh() -> None:
        tree.delete(*tree.get_children())
        for i, e in enumerate(entries):
            tree.insert("", "end", iid=str(i), values=(e["filename"], e["display_name"]))

    def clear() -> None:
        selected["value"] = None
        var_file.set("")
        var_display.set("")
        tree.selection_remove(*tree.selection())

    def on_select(_evt=None) -> None:
        sel = tree.selection()
        if sel:
            idx = int(sel[0])
            selected["value"] = idx
            var_file.set(entries[idx]["filename"])
            var_display.set(entries[idx]["display_name"])

    tree.bind("<<TreeviewSelect>>", on_select)

    def add_or_update() -> None:
        filename = var_file.get().strip()
        if not filename:
            messagebox.showwarning("Arquivo de espaço", "Informe o nome do arquivo/job.")
            return
        item = {"filename": filename, "display_name": var_display.get().strip() or "ESPAÇO"}
        if selected["value"] is None:
            entries.append(item)
        else:
            entries[selected["value"]] = item
        refresh()
        clear()

    def remove() -> None:
        if selected["value"] is None:
            messagebox.showwarning("Arquivo de espaço", "Selecione um item na lista.")
            return
        del entries[selected["value"]]
        clear()
        refresh()

    btns = ttk.Frame(form)
    btns.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Button(btns, text="Novo", command=clear).pack(side="left")
    ttk.Button(btns, text="Adicionar / Atualizar", command=add_or_update).pack(side="left", padx=6)
    ttk.Button(btns, text="Remover", command=remove).pack(side="left")

    # ---- Operadores ----
    ttk.Label(box, text="Operadores", style="PanelStrong.TLabel").pack(anchor="w", pady=(16, 0))
    ttk.Label(
        box,
        text=(
            "Nome de quem imprime, ligado ao identificador (iniciais) que aparece no nome do "
            "arquivo de reposição — ex.: \"N1 - Dryfit\" tem identificador \"N\". Aparece como "
            "Operador no PDF e no JPG (modo Completo)."
        ),
        style="Muted.TLabel", wraplength=860, justify="left",
    ).pack(anchor="w", pady=(2, 6))

    operators: List[dict] = normalize_operators(cfg.get("operators", []))

    op_row = ttk.Frame(box)
    op_row.pack(fill="x")
    tree_op = ttk.Treeview(op_row, columns=("identifier", "name"), show="headings", height=4)
    tree_op.heading("identifier", text="Identificador")
    tree_op.column("identifier", width=100, anchor="w")
    tree_op.heading("name", text="Nome")
    tree_op.column("name", width=260, anchor="w")
    tree_op.pack(side="left", fill="x", expand=True)

    op_form = ttk.Frame(op_row)
    op_form.pack(side="left", fill="y", padx=(12, 0))
    ttk.Label(op_form, text="Identificador:").grid(row=0, column=0, sticky="w")
    var_op_id = tk.StringVar()
    ttk.Entry(op_form, textvariable=var_op_id, width=10).grid(row=0, column=1, padx=6, pady=2, sticky="w")
    ttk.Label(op_form, text="Nome:").grid(row=1, column=0, sticky="w")
    var_op_name = tk.StringVar()
    ttk.Entry(op_form, textvariable=var_op_name, width=24).grid(row=1, column=1, padx=6, pady=2)

    op_selected: Dict[str, Optional[int]] = {"value": None}

    def refresh_operators() -> None:
        tree_op.delete(*tree_op.get_children())
        for i, o in enumerate(operators):
            tree_op.insert("", "end", iid=str(i), values=(o["identifier"], o["name"]))

    def clear_operator_form() -> None:
        op_selected["value"] = None
        var_op_id.set("")
        var_op_name.set("")
        tree_op.selection_remove(*tree_op.selection())

    def on_select_operator(_evt=None) -> None:
        sel = tree_op.selection()
        if sel:
            idx = int(sel[0])
            op_selected["value"] = idx
            var_op_id.set(operators[idx]["identifier"])
            var_op_name.set(operators[idx]["name"])

    tree_op.bind("<<TreeviewSelect>>", on_select_operator)

    def add_or_update_operator() -> None:
        identifier = var_op_id.get().strip()
        name = var_op_name.get().strip()
        if not identifier or not name:
            messagebox.showwarning("Operadores", "Informe o identificador e o nome.")
            return
        if not re.fullmatch(r"[A-Za-z]+", identifier):
            messagebox.showwarning("Operadores", "O identificador deve ter só letras (ex.: \"N\", \"NJ\").")
            return
        identifier = identifier.upper()
        item = {"identifier": identifier, "name": name}
        existing_idx = next(
            (i for i, o in enumerate(operators) if o["identifier"] == identifier and i != op_selected["value"]),
            None,
        )
        if existing_idx is not None:
            messagebox.showwarning("Operadores", f'Já existe um operador com o identificador "{identifier}".')
            return
        if op_selected["value"] is None:
            operators.append(item)
        else:
            operators[op_selected["value"]] = item
        refresh_operators()
        clear_operator_form()

    def remove_operator() -> None:
        if op_selected["value"] is None:
            messagebox.showwarning("Operadores", "Selecione um operador na lista.")
            return
        del operators[op_selected["value"]]
        clear_operator_form()
        refresh_operators()

    op_btns = ttk.Frame(op_form)
    op_btns.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Button(op_btns, text="Novo", command=clear_operator_form).pack(side="left")
    ttk.Button(op_btns, text="Adicionar / Atualizar", command=add_or_update_operator).pack(side="left", padx=6)
    ttk.Button(op_btns, text="Remover", command=remove_operator).pack(side="left")

    def save() -> bool:
        try:
            export = collect_export()
        except ValueError as e:
            messagebox.showerror("Operação", str(e))
            return False
        current = load_operacao_cfg()
        current.update(export)
        current["space_filenames"] = list(entries)
        current["operators"] = list(operators)
        save_operacao_cfg(current)
        on_saved("Operação")
        return True

    refresh()
    refresh_operators()
    box.save = save
    return box


# ---------------------------------------------------------------------------
# Planejador
# ---------------------------------------------------------------------------
def build_planejador_section(parent: tk.Misc, on_saved: SavedCallback) -> ttk.LabelFrame:
    box = card(parent, "Planejador · valores padrão de cálculo e exportação", padding=14)
    ttk.Label(
        box,
        text=(
            "Valores usados ao abrir o Planejador e ao clicar em Limpar. A impressora e a "
            "velocidade vêm do cadastro de Impressoras."
        ),
        style="Muted.TLabel", wraplength=860, justify="left",
    ).pack(anchor="w", pady=(0, 10))

    cfg = load_planner_cfg()
    grid = ttk.Frame(box)
    grid.pack(fill="x")
    for col in range(4):
        grid.columnconfigure(col, weight=1)

    vars_: Dict[str, tk.StringVar] = {}
    numeric = [
        ("dpi", "DPI global", 1, None),
        ("setup_min", "Setup (min/job)", 0, None),
        ("gap_between", "Gap entre tecidos (m)", 0, None),
        ("gap_endroll", "Gap antes do fim do rolo (m)", 0, None),
        ("gap_files", "Gap entre arquivos (m)", 0, None),
        ("roll_other", "Rolo p/ tecido sem metragem (m)", 1, None),
        ("scrap_bleed_cm", "Sangria dos pedaços (cm)", 0, 100),
    ]
    for i, (key, label, _mn, _mx) in enumerate(numeric):
        r, c = divmod(i, 4)
        ttk.Label(grid, text=label).grid(row=r * 2, column=c, sticky="w", padx=(0, 12))
        var = tk.StringVar(value=_fmt(cfg.get(key, PLANNER_DEFAULTS[key])))
        ttk.Entry(grid, textvariable=var, width=10).grid(
            row=r * 2 + 1, column=c, sticky="ew", padx=(0, 12), pady=(2, 8)
        )
        vars_[key] = var

    ttk.Label(grid, text="Eixo do comprimento").grid(row=2, column=3, sticky="w")
    var_axis = tk.StringVar(value=str(cfg.get("axis", "altura")))
    ttk.Combobox(grid, values=["altura", "largura", "maior"], state="readonly",
                 textvariable=var_axis, width=10).grid(row=3, column=3, sticky="ew", pady=(2, 8))

    ttk.Label(grid, text="Modo da fila").grid(row=4, column=0, sticky="w")
    var_mode = tk.StringVar(value=str(cfg.get("mode", "tecido")))
    ttk.Combobox(grid, values=["tecido", "original"], state="readonly",
                 textvariable=var_mode, width=10).grid(row=5, column=0, sticky="ew", padx=(0, 12), pady=(2, 8))

    var_auto = tk.BooleanVar(value=bool(cfg.get("auto_fabric_order", True)))
    ttk.Checkbutton(grid, text="Ordem automática dos tecidos (menores no fim)",
                    variable=var_auto).grid(row=5, column=1, columnspan=3, sticky="w")

    export_grid = ttk.Frame(box)
    export_grid.pack(fill="x", pady=(4, 0))
    collect_export = _export_defaults_rows(export_grid, cfg, 0)

    def save() -> bool:
        try:
            values = {
                key: _num(vars_[key].get(), label, minimum=mn, maximum=mx)
                for key, label, mn, mx in numeric
            }
            values.update(collect_export())
        except ValueError as e:
            messagebox.showerror("Planejador", str(e))
            return False
        values["axis"] = var_axis.get()
        values["mode"] = var_mode.get()
        values["auto_fabric_order"] = bool(var_auto.get())
        current = load_planner_cfg()
        current.update(values)
        save_planner_cfg(current)
        on_saved("Planejador")
        return True

    box.save = save
    return box


# ---------------------------------------------------------------------------
# Registros
# ---------------------------------------------------------------------------
def build_registros_section(parent: tk.Misc, on_saved: SavedCallback) -> ttk.LabelFrame:
    box = card(parent, "Registros · manutenção dos tipos salvos", padding=14)
    ttk.Label(
        box,
        text=(
            f"Reaplica as regras de tipo de impressão aos pedidos já gravados como "
            f"'{FALLBACK_TYPE}'. Tipos escolhidos à mão (Teste, Terceirizado...) não mudam."
        ),
        style="Muted.TLabel", wraplength=860, justify="left",
    ).pack(anchor="w", pady=(0, 10))

    def run() -> None:
        from core.printlogs_db import reclassify_unmatched_orders

        rules = normalize_rules(load_operacao_cfg().get("print_type_rules", DEFAULT_RULES))
        try:
            changed = reclassify_unmatched_orders(lambda doc: classify_document(doc, rules))
        except Exception as e:  # noqa: BLE001 — banco pode estar em pasta de rede
            messagebox.showerror("Registros", f"Não foi possível atualizar o banco.\n\n{type(e).__name__}: {e}")
            return
        on_saved("Registros")
        messagebox.showinfo("Registros", f"{changed} pedido(s) reclassificado(s).")

    ttk.Button(box, text=f"Reclassificar registros '{FALLBACK_TYPE}'", command=run).pack(anchor="w")
    return box
