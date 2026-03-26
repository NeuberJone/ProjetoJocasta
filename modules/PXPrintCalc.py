# modules/PXPrintCalc.py
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
    Image.MAX_IMAGE_PIXELS = None  # evita "decompression bomb"
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None
    _HAS_PIL = False


# -----------------------------
# Helpers
# -----------------------------
def _round_up_cm(m: float) -> float:
    if m <= 0:
        return 0.0
    cm = m * 100.0
    cm_up = int(cm) if abs(cm - int(cm)) < 1e-9 else int(cm) + 1
    return cm_up / 100.0


def fmt_m(m: float) -> str:
    return f"{_round_up_cm(m):.2f} m"


def fmt_min(minutes: float) -> str:
    if minutes <= 0:
        return "0 min"
    total = int(round(minutes))
    h = total // 60
    m = total % 60
    return f"{h}h {m:02d}m" if h else f"{m} min"


def px_to_m(px: int, dpi: float) -> float:
    return (px / dpi) * 0.0254 if dpi > 0 else 0.0


def safe_float(s: str, default: float) -> float:
    try:
        return float(str(s).replace(",", "."))
    except Exception:
        return default


# -----------------------------
# Tecidos (cadastro + aliases)
# -----------------------------
def _fabrics_store_path() -> Path:
    return Path(__file__).with_suffix(".fabrics.json")


def _default_fabrics() -> Dict[str, List[str]]:
    return {
        "Dryfit": ["dryfit", "dry fit", "dry-fit", "drifit"],
        "Ribana": ["ribana"],
        "Elastano": ["elastano"],
        "Poliamida": ["poliamida"],
        "Crepe": ["crepe"],
        "Malha": ["malha"],
        "Helanca": ["helanca"],
        "Tactel": ["tactel"],
        "Microfibra": ["microfibra"],
        "Aeroready": ["aeroready", "aero ready", "aero-ready"],
    }


def save_fabrics(data: Dict[str, List[str]]) -> None:
    p = _fabrics_store_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_fabrics() -> Dict[str, List[str]]:
    p = _fabrics_store_path()
    if not p.exists():
        data = _default_fabrics()
        save_fabrics(data)
        return data
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        out: Dict[str, List[str]] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, list):
                    out[k] = [str(x) for x in v if str(x).strip()]
                else:
                    out[k] = []
        return out or _default_fabrics()
    except Exception:
        data = _default_fabrics()
        save_fabrics(data)
        return data


_DASHES = ["–", "—", "-", "-"]  # en dash, em dash, hyphen, non-breaking hyphen


def _normalize_name(s: str) -> str:
    s = (s or "").lower()
    for d in _DASHES:
        s = s.replace(d, "-")
    s = s.replace("_", " ")
    s = s.replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def infer_fabric_from_filename(filename: str, fabrics_map: Dict[str, List[str]]) -> str:
    s = _normalize_name(filename)
    parts = re.split(r"[\s\-]+", s)
    tokens = [p.strip() for p in parts if p.strip()]

    alias_index: Dict[str, str] = {}
    for canonical, aliases in fabrics_map.items():
        alias_index[_normalize_name(canonical)] = canonical
        for a in aliases:
            alias_index[_normalize_name(a)] = canonical

    # token exato
    for t in tokens:
        if t in alias_index:
            return alias_index[t]

    # substring
    for alias, canonical in alias_index.items():
        if alias and alias in s:
            return canonical

    return "Outro"


def safe_image_size(path: Path) -> Tuple[int, int]:
    if not _HAS_PIL:
        raise RuntimeError("Instale pillow: pip install pillow")
    with Image.open(path) as im:
        return im.size


# -----------------------------
# Data
# -----------------------------
@dataclass
class Job:
    name: str
    path: Optional[Path]
    fabric: str
    w_px: int
    h_px: int
    dpi_override: Optional[float] = None
    length_m: float = 0.0
    time_min: float = 0.0
    is_gap: bool = False
    roll_no: int = 0


# -----------------------------
# MAIN ENTRY
# -----------------------------
def build_ui(parent: tk.Widget):
    frame = ttk.Frame(parent, padding=10)
    frame.pack(fill="both", expand=True)

    jobs: List[Job] = []
    view_rows: List[Job] = []

    fabrics_map: Dict[str, List[str]] = load_fabrics()

    manual_fabric_order: List[str] = []
    var_auto_fabric_order = tk.BooleanVar(value=True)

    var_dpi = tk.StringVar(value="150")
    var_axis = tk.StringVar(value="altura")
    var_speed = tk.StringVar(value="1.50")
    var_setup = tk.StringVar(value="2")

    # ✅ padrão: modo tecido
    var_mode = tk.StringVar(value="tecido")
    var_gap_between = tk.StringVar(value="1.00")
    var_gap_endroll = tk.StringVar(value="1.00")
    var_roll_dryfit = tk.StringVar(value="90")
    var_roll_other = tk.StringVar(value="60")

    fabric_options = sorted(set(list(fabrics_map.keys()) + ["Outro"]))
    var_fabric_pick = tk.StringVar(value="Dryfit" if "Dryfit" in fabric_options else fabric_options[0])

    # ---------------- UI TOP ----------------
    top = ttk.Frame(frame)
    top.pack(fill="x")

    ttk.Button(top, text="Importar imagens", command=lambda: import_images()).pack(side="left")
    ttk.Button(top, text="Recalcular (DPI/Vel/Setup)", command=lambda: recalc_all()).pack(side="left", padx=6)
    ttk.Button(top, text="Gerar Fila (Tecidos/Rolos)", command=lambda: generate_queue()).pack(side="left", padx=6)
    ttk.Button(top, text="Exportar CSV", command=lambda: export_csv()).pack(side="left", padx=6)

    # ✅ agora exporta somente relatório consolidado (JPG espelhado)
    ttk.Button(top, text="Exportar relatório (JPG espelhado)", command=lambda: export_consolidated_report()).pack(side="left", padx=6)

    ttk.Button(top, text="Tecidos…", command=lambda: open_fabrics_dialog()).pack(side="left", padx=6)
    ttk.Button(top, text="Ordem dos tecidos…", command=lambda: open_fabric_order_dialog()).pack(side="left", padx=6)
    ttk.Button(top, text="Limpar", command=lambda: clear_all()).pack(side="left", padx=6)

    ttk.Separator(frame).pack(fill="x", pady=10)

    # Config row
    config = ttk.Frame(frame)
    config.pack(fill="x")

    ttk.Label(config, text="DPI:").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_dpi).pack(side="left", padx=5)

    ttk.Label(config, text="Eixo:").pack(side="left")
    ttk.Combobox(
        config, width=10, values=["altura", "largura", "maior"],
        state="readonly", textvariable=var_axis
    ).pack(side="left", padx=5)

    ttk.Label(config, text="Vel (m/min):").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_speed).pack(side="left", padx=5)

    ttk.Label(config, text="Setup (min/job):").pack(side="left")
    ttk.Entry(config, width=8, textvariable=var_setup).pack(side="left", padx=5)

    # Fabric tools row
    tools = ttk.Frame(frame)
    tools.pack(fill="x", pady=(8, 0))

    ttk.Label(tools, text="Tecido:").pack(side="left")
    cb_fab = ttk.Combobox(
        tools, width=18, values=fabric_options,
        state="readonly", textvariable=var_fabric_pick
    )
    cb_fab.pack(side="left", padx=5)

    ttk.Button(
        tools,
        text="Definir tecido (selecionados)",
        command=lambda: set_fabric_selected()
    ).pack(side="left", padx=6)

    # Mode and planning row
    plan = ttk.Frame(frame)
    plan.pack(fill="x", pady=(8, 0))

    ttk.Label(plan, text="Modo:").pack(side="left")
    ttk.Combobox(
        plan, width=12, values=["original", "tecido"],
        state="readonly", textvariable=var_mode
    ).pack(side="left", padx=5)

    ttk.Checkbutton(
        plan,
        text="Ordem automática (menores no fim)",
        variable=var_auto_fabric_order
    ).pack(side="left", padx=10)

    ttk.Label(plan, text="Gap entre tecidos (m):").pack(side="left")
    ttk.Entry(plan, width=7, textvariable=var_gap_between).pack(side="left", padx=5)

    ttk.Label(plan, text="Gap antes fim rolo (m):").pack(side="left")
    ttk.Entry(plan, width=7, textvariable=var_gap_endroll).pack(side="left", padx=5)

    ttk.Label(plan, text="Rolo Dryfit (m):").pack(side="left")
    ttk.Entry(plan, width=6, textvariable=var_roll_dryfit).pack(side="left", padx=5)

    ttk.Label(plan, text="Outros (m):").pack(side="left")
    ttk.Entry(plan, width=6, textvariable=var_roll_other).pack(side="left", padx=5)

    ttk.Button(plan, text="Voltar visão base", command=lambda: show_base()).pack(side="left", padx=10)

    # ---------------- TABLE ----------------
    cols = ("roll", "fabric", "dpi", "arquivo", "w", "h", "metros", "tempo")
    tree = ttk.Treeview(frame, columns=cols, show="headings")
    tree.pack(fill="both", expand=True, pady=10)

    tree.heading("roll", text="Rolo")
    tree.heading("fabric", text="Tecido")
    tree.heading("dpi", text="DPI(item)")
    tree.heading("arquivo", text="Arquivo")
    tree.heading("w", text="Largura px")
    tree.heading("h", text="Altura px")
    tree.heading("metros", text="Comprimento")
    tree.heading("tempo", text="Tempo")

    tree.column("roll", width=70, anchor="center")
    tree.column("fabric", width=120, anchor="w")
    tree.column("dpi", width=70, anchor="e")
    tree.column("arquivo", width=420, anchor="w")
    tree.column("w", width=100, anchor="e")
    tree.column("h", width=100, anchor="e")
    tree.column("metros", width=120, anchor="e")
    tree.column("tempo", width=120, anchor="e")

    tree.bind("<Double-1>", lambda _e: on_double_click())

    # ---------------- SUMMARY ----------------
    summary = ttk.Frame(frame)
    summary.pack(fill="x")

    lbl_count = ttk.Label(summary, text="Itens: 0")
    lbl_count.pack(side="left")

    lbl_total = ttk.Label(summary, text="Total: 0.00 m")
    lbl_total.pack(side="left", padx=16)

    lbl_time = ttk.Label(summary, text="Tempo total: 0 min")
    lbl_time.pack(side="left", padx=16)

    # ---------------- INTERNALS ----------------
    def get_config() -> Tuple[float, str, float, float]:
        dpi = safe_float(var_dpi.get(), 150.0)
        axis = (var_axis.get() or "altura").strip().lower()
        speed = safe_float(var_speed.get(), 1.5)
        setup = safe_float(var_setup.get(), 2.0)

        if dpi <= 0:
            raise ValueError("DPI inválido.")
        if speed <= 0:
            raise ValueError("Velocidade inválida.")
        if setup < 0:
            raise ValueError("Setup inválido.")
        if axis not in {"altura", "largura", "maior"}:
            axis = "altura"
        return dpi, axis, speed, setup

    def job_dpi(j: Job, dpi_global: float) -> float:
        return float(j.dpi_override) if (j.dpi_override and j.dpi_override > 0) else dpi_global

    def compute_length(w: int, h: int, dpi: float, axis: str) -> float:
        if axis == "largura":
            return px_to_m(w, dpi)
        if axis == "maior":
            return px_to_m(max(w, h), dpi)
        return px_to_m(h, dpi)

    def compute_time(length_m: float, speed_m_min: float, setup_min: float, is_gap: bool) -> float:
        if is_gap:
            return (length_m / speed_m_min) if speed_m_min > 0 else 0.0
        return setup_min + (length_m / speed_m_min)

    def recompute_job(j: Job):
        dpi_global, axis, speed, setup = get_config()
        dpi_use = job_dpi(j, dpi_global)
        j.length_m = float(compute_length(j.w_px, j.h_px, dpi_use, axis))
        j.time_min = float(compute_time(j.length_m, speed, setup, is_gap=j.is_gap))

    def refresh_table(rows: List[Job]):
        tree.delete(*tree.get_children())

        total_m = 0.0
        total_time = 0.0

        for i, j in enumerate(rows):
            total_m += j.length_m
            total_time += j.time_min

            roll_txt = f"{j.roll_no}" if j.roll_no > 0 else ""
            name = "— ESPAÇO —" if (j.is_gap and j.name.upper() == "ESPAÇO") else j.name
            dpi_txt = ""
            if not j.is_gap and j.dpi_override:
                dpi_txt = f"{j.dpi_override:.0f}"

            tree.insert(
                "", "end", iid=str(i),
                values=(
                    roll_txt,
                    j.fabric,
                    dpi_txt,
                    name,
                    j.w_px if j.w_px else "",
                    j.h_px if j.h_px else "",
                    fmt_m(j.length_m),
                    fmt_min(j.time_min),
                )
            )

        lbl_count.config(text=f"Itens: {len(rows)}")
        lbl_total.config(text=f"Total: {fmt_m(total_m)}")
        lbl_time.config(text=f"Tempo total: {fmt_min(total_time)}")

    def show_base():
        nonlocal view_rows
        view_rows = list(jobs)
        refresh_table(view_rows)

    def selected_rows() -> List[Job]:
        sel = tree.selection()
        if not sel:
            return []
        picked: List[Job] = []
        for iid in sel:
            try:
                idx = int(iid)
            except Exception:
                continue
            if 0 <= idx < len(view_rows):
                r = view_rows[idx]
                if not r.is_gap:
                    picked.append(r)
        return picked

    def selected_base_jobs() -> List[Job]:
        picked_view = selected_rows()
        if not picked_view:
            return []
        out: List[Job] = []
        for row in picked_view:
            for jb in jobs:
                if jb.path == row.path and jb.name == row.name:
                    out.append(jb)
                    break
        return out

    # ---------------- Actions ----------------
    def import_images():
        if not _HAS_PIL:
            messagebox.showerror("Erro", "Instale pillow: pip install pillow")
            return

        paths = filedialog.askopenfilenames(
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff")]
        )
        if not paths:
            return

        try:
            _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        errors = []
        for p in paths:
            path = Path(p)
            try:
                w, h = safe_image_size(path)
                fabric = infer_fabric_from_filename(path.name, fabrics_map)

                j = Job(
                    name=path.name,
                    path=path,
                    fabric=fabric,
                    w_px=int(w),
                    h_px=int(h),
                    dpi_override=None,
                )
                recompute_job(j)
                jobs.append(j)

            except Exception as ex:
                errors.append(f"{path.name}: {ex}")

        # por padrão, já mostra a fila por tecido
        generate_queue()

        if errors:
            messagebox.showwarning(
                "Alguns arquivos falharam",
                "Falhas:\n\n" + "\n".join(errors[:12]) + ("\n..." if len(errors) > 12 else "")
            )

    def recalc_all():
        if not jobs:
            return
        try:
            _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        for j in jobs:
            recompute_job(j)

        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

    def clear_all():
        jobs.clear()
        show_base()

    def export_csv():
        if not view_rows:
            return

        out = filedialog.asksaveasfilename(defaultextension=".csv")
        if not out:
            return

        try:
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["rolo", "tecido", "dpi_item", "arquivo", "largura_px", "altura_px", "comprimento_m", "tempo_min", "tipo"])
                for j in view_rows:
                    w.writerow([
                        j.roll_no if j.roll_no else "",
                        j.fabric,
                        f"{j.dpi_override:.0f}" if (j.dpi_override and not j.is_gap) else "",
                        j.name,
                        j.w_px if j.w_px else "",
                        j.h_px if j.h_px else "",
                        f"{j.length_m:.6f}",
                        f"{j.time_min:.6f}",
                        "ESPACO" if j.is_gap else "JOB"
                    ])
            messagebox.showinfo("Exportado", "CSV salvo com sucesso.")
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))

    def set_fabric_selected():
        fab = var_fabric_pick.get().strip() or "Outro"
        picked = selected_base_jobs()
        if not picked:
            messagebox.showinfo("Seleção", "Selecione 1 ou mais itens (não selecione ESPAÇO).")
            return
        for j in picked:
            j.fabric = fab
        generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

    # ---------------- Double click edit ----------------
    def on_double_click():
        sel = tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        if not (0 <= idx < len(view_rows)):
            return
        row = view_rows[idx]
        if row.is_gap:
            return

        base: Optional[Job] = None
        for jb in jobs:
            if jb.path == row.path and jb.name == row.name:
                base = jb
                break
        if base is None:
            return

        open_edit_dialog(base)

    def open_edit_dialog(job: Job):
        dlg = tk.Toplevel(frame)
        dlg.title("Editar item")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Arquivo:").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, text=job.name).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Tecido:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        var_fab = tk.StringVar(value=job.fabric)
        cb = ttk.Combobox(frm, values=sorted(set(list(fabrics_map.keys()) + ["Outro"])),
                          textvariable=var_fab, state="readonly", width=22)
        cb.grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(frm, text="DPI do item (vazio = DPI global):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        var_dpi_item = tk.StringVar(value=(f"{job.dpi_override:.0f}" if job.dpi_override else ""))
        ttk.Entry(frm, textvariable=var_dpi_item, width=10).grid(row=2, column=1, sticky="w", pady=(8, 0))

        def on_save():
            job.fabric = var_fab.get().strip() or "Outro"
            dpi_txt = var_dpi_item.get().strip()
            if dpi_txt == "":
                job.dpi_override = None
            else:
                v = safe_float(dpi_txt, -1)
                if v <= 0:
                    messagebox.showerror("DPI inválido", "Informe um DPI > 0 ou deixe vazio.")
                    return
                job.dpi_override = float(v)

            try:
                recompute_job(job)
            except Exception as e:
                messagebox.showerror("Erro ao recalcular", str(e))
                return

            dlg.destroy()
            generate_queue() if var_mode.get().strip().lower() == "tecido" else show_base()

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Salvar", command=on_save).pack(side="right", padx=(0, 8))

    # ---------------- Fabric manager dialog ----------------
    def open_fabrics_dialog():
        dlg = tk.Toplevel(frame)
        dlg.title("Cadastro de Tecidos e Variações")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Tecidos cadastrados (canonical -> aliases):").pack(anchor="w")

        lb = tk.Listbox(frm, height=12, width=74)
        lb.pack(fill="both", expand=True, pady=8)

        def refresh_list():
            lb.delete(0, tk.END)
            for canonical in sorted(fabrics_map.keys()):
                aliases = fabrics_map.get(canonical, [])
                lb.insert(tk.END, f"{canonical} -> {', '.join(aliases) if aliases else '(sem aliases)'}")

        def refresh_fabric_options():
            nonlocal fabric_options
            fabric_options = sorted(set(list(fabrics_map.keys()) + ["Outro"]))
            cb_fab.config(values=fabric_options)
            # mantém valor atual válido
            if var_fabric_pick.get() not in fabric_options:
                var_fabric_pick.set("Dryfit" if "Dryfit" in fabric_options else fabric_options[0])

        refresh_list()

        form = ttk.Frame(frm)
        form.pack(fill="x", pady=(8, 0))

        ttk.Label(form, text="Novo tecido (canonical):").grid(row=0, column=0, sticky="w")
        var_new_can = tk.StringVar()
        ttk.Entry(form, textvariable=var_new_can, width=24).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(form, text="Variações (separadas por vírgula):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        var_new_alias = tk.StringVar()
        ttk.Entry(form, textvariable=var_new_alias, width=52).grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))

        def add_fabric():
            can = var_new_can.get().strip()
            if not can:
                messagebox.showerror("Erro", "Informe o nome do tecido (canonical).")
                return

            aliases_raw = var_new_alias.get().strip()
            aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()] if aliases_raw else []

            current = fabrics_map.get(can, [])
            merged = list(dict.fromkeys(current + aliases))  # unique mantendo ordem
            fabrics_map[can] = merged

            save_fabrics(fabrics_map)
            refresh_list()
            refresh_fabric_options()

            var_new_can.set("")
            var_new_alias.set("")

        ttk.Button(form, text="Adicionar / Atualizar", command=add_fabric).grid(row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Button(frm, text="Fechar", command=dlg.destroy).pack(anchor="e", pady=(10, 0))

    # ---------------- Fabric order dialog ----------------
    def open_fabric_order_dialog():
        fabrics = sorted({j.fabric for j in jobs if not j.is_gap})
        if not fabrics:
            messagebox.showinfo("Ordem dos tecidos", "Importe imagens primeiro.")
            return

        nonlocal manual_fabric_order
        if not manual_fabric_order:
            manual_fabric_order = list(fabrics)

        dlg = tk.Toplevel(frame)
        dlg.title("Ordem dos tecidos")
        dlg.transient(frame.winfo_toplevel())
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Cima imprime antes.").pack(anchor="w")

        lb = tk.Listbox(frm, height=10, width=28)
        lb.pack(fill="both", expand=True, pady=8)

        def reload_list():
            lb.delete(0, tk.END)
            for f in manual_fabric_order:
                lb.insert(tk.END, f)

        existing = set(fabrics)
        manual_fabric_order = [f for f in manual_fabric_order if f in existing]
        for f in fabrics:
            if f not in manual_fabric_order:
                manual_fabric_order.append(f)

        reload_list()

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=6)

        def move(delta: int):
            sel = lb.curselection()
            if not sel:
                return
            i = sel[0]
            j = i + delta
            if j < 0 or j >= len(manual_fabric_order):
                return
            manual_fabric_order[i], manual_fabric_order[j] = manual_fabric_order[j], manual_fabric_order[i]
            reload_list()
            lb.selection_set(j)

        ttk.Button(btns, text="Subir", command=lambda: move(-1)).pack(side="left")
        ttk.Button(btns, text="Descer", command=lambda: move(+1)).pack(side="left", padx=6)

        ttk.Checkbutton(
            frm,
            text="Usar ordem automática (menores no fim)",
            variable=var_auto_fabric_order
        ).pack(anchor="w", pady=(6, 0))

        def on_close():
            dlg.destroy()
            if var_mode.get().strip().lower() == "tecido":
                generate_queue()

        ttk.Button(frm, text="OK", command=on_close).pack(anchor="e", pady=(10, 0))

    # ---------------- Queue planner ----------------
    def roll_limit_for(fabric: str) -> float:
        f = (fabric or "").strip().lower()
        if f == "dryfit":
            return safe_float(var_roll_dryfit.get(), 90.0)
        return safe_float(var_roll_other.get(), 60.0)

    def add_gap(rows: List[Job], fabric: str, gap_m: float, speed: float):
        if gap_m <= 0:
            return
        g = Job(
            name="ESPAÇO",
            path=None,
            fabric=fabric,
            w_px=0,
            h_px=0,
            dpi_override=None,
            is_gap=True,
            roll_no=0,
        )
        g.length_m = float(gap_m)
        g.time_min = float((g.length_m / speed) if speed > 0 else 0.0)  # gap não tem setup
        rows.append(g)

    def fabric_totals(base_list: List[Job]) -> Dict[str, float]:
        tot: Dict[str, float] = {}
        for j in base_list:
            if j.is_gap:
                continue
            tot[j.fabric] = tot.get(j.fabric, 0.0) + j.length_m
        return tot

    def ordered_fabrics(base_list: List[Job]) -> List[str]:
        fabrics = sorted({j.fabric for j in base_list if not j.is_gap})
        if not fabrics:
            return []

        if var_auto_fabric_order.get():
            totals = fabric_totals(base_list)
            return sorted(fabrics, key=lambda f: totals.get(f, 0.0), reverse=True)

        nonlocal manual_fabric_order
        if not manual_fabric_order:
            manual_fabric_order = list(fabrics)

        existing = set(fabrics)
        manual_fabric_order = [f for f in manual_fabric_order if f in existing]
        for f in fabrics:
            if f not in manual_fabric_order:
                manual_fabric_order.append(f)
        return list(manual_fabric_order)

    def generate_queue():
        nonlocal view_rows

        if not jobs:
            show_base()
            return

        try:
            _, _, speed, _ = get_config()
        except Exception as e:
            messagebox.showerror("Configuração inválida", str(e))
            return

        mode = var_mode.get().strip().lower()
        gap_between = safe_float(var_gap_between.get(), 1.0)
        gap_endroll = safe_float(var_gap_endroll.get(), 1.0)

        base_list = list(jobs)

        planned: List[Job] = []
        current_fabric: Optional[str] = None
        current_roll_no = 1
        used_in_roll = 0.0

        if mode != "tecido":
            iter_list = base_list
        else:
            fabrics = ordered_fabrics(base_list)

            by_fab: Dict[str, List[Job]] = {f: [] for f in fabrics}
            for j in base_list:
                if j.is_gap:
                    continue
                by_fab.setdefault(j.fabric, []).append(j)

            iter_list = []
            for f in fabrics:
                items = list(by_fab.get(f, []))
                # ✅ bin packing simples: dentro do tecido, maiores primeiro
                items.sort(key=lambda j: j.length_m, reverse=True)
                iter_list.extend(items)

        for j in iter_list:
            fabric = j.fabric or "Outro"
            limit = roll_limit_for(fabric) or 60.0

            if current_fabric is None:
                current_fabric = fabric
                current_roll_no = 1
                used_in_roll = 0.0
            elif fabric != current_fabric:
                add_gap(planned, current_fabric, gap_between, speed)
                current_fabric = fabric
                current_roll_no = 1
                used_in_roll = 0.0

            # nunca encostar no limite (reserva gap_endroll)
            if (used_in_roll + j.length_m + gap_endroll) > limit:
                add_gap(planned, current_fabric, gap_endroll, speed)
                current_roll_no += 1
                used_in_roll = 0.0

            planned.append(Job(
                name=j.name,
                path=j.path,
                fabric=fabric,
                w_px=j.w_px,
                h_px=j.h_px,
                dpi_override=j.dpi_override,
                length_m=j.length_m,
                time_min=j.time_min,
                is_gap=False,
                roll_no=current_roll_no,
            ))
            used_in_roll += j.length_m

        # opcional: gap final (mantém)
        if current_fabric is not None and gap_endroll > 0:
            add_gap(planned, current_fabric, gap_endroll, speed)

        view_rows = planned
        refresh_table(view_rows)

    # ---------------- Consolidated report (PrintLogs-like) ----------------
    def _ensure_queue_view() -> List[Job]:
        # Para relatório, sempre gera fila (tem roll_no, gaps e blocos)
        generate_queue()
        return list(view_rows)

#    def render_text_page(lines: List[str], font) -> Image.Image:
#        line_h = 18
#        margin = 28
#        width = 1600
#        height = margin * 2 + max(80, len(lines) * line_h)

#        img = Image.new("RGB", (width, height), "white")
#        draw = ImageDraw.Draw(img)

#        y = margin
#        for ln in lines:
#            draw.text((margin, y), ln, fill="black", font=font)
#            y += line_h
#        return img

    def export_consolidated_report():
        if not _HAS_PIL:
            messagebox.showerror("Erro", "Instale pillow: pip install pillow")
            return
        if not jobs:
            messagebox.showinfo("Nada", "Importe imagens primeiro.")
            return

        out_dir = filedialog.askdirectory(title="Escolha a pasta para salvar o relatório (JPG espelhado)")
        if not out_dir:
            return
        out_dir = Path(out_dir)

        rows = _ensure_queue_view()
        try:
            out_path = export_consolidated_report_jpg(rows, out_dir, mirror=True)
            messagebox.showinfo("OK", f"Relatório gerado:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def export_consolidated_report_jpg(rows: List[Job], out_dir: Path, mirror: bool = True) -> Path:
        # fonte
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        now = datetime.now()
        stamp = now.strftime("%d/%m/%Y %H:%M:%S")

        # agrupa por rolo
        roll_order: List[int] = []
        by_roll: Dict[int, List[Job]] = {}
        for r in rows:
            if not r.roll_no:
                continue
            rn = int(r.roll_no)
            if rn not in by_roll:
                by_roll[rn] = []
                roll_order.append(rn)
            by_roll[rn].append(r)

        if not roll_order:
            raise RuntimeError("Não foi possível gerar relatório: fila vazia.")

        # calcula blocos por rolo (bloco = sequência contínua de mesmo tecido; gap quebra)
        def build_blocks(roll_rows: List[Job]) -> List[Tuple[str, float, float, int]]:
            blocks: List[Tuple[str, float, float, int]] = []
            cur_fab = ""
            cur_m = 0.0
            cur_t = 0.0
            cur_n = 0

            def flush():
                nonlocal cur_fab, cur_m, cur_t, cur_n
                if cur_n > 0:
                    blocks.append((cur_fab, cur_m, cur_t, cur_n))
                cur_fab, cur_m, cur_t, cur_n = "", 0.0, 0.0, 0

            prev_fab: Optional[str] = None
            for x in roll_rows:
                if x.is_gap:
                    flush()
                    prev_fab = None
                    continue
                if prev_fab is None or x.fabric != prev_fab:
                    flush()
                    cur_fab = x.fabric
                cur_m += x.length_m
                cur_t += x.time_min
                cur_n += 1
                prev_fab = x.fabric

            flush()
            return blocks

        # totais gerais
        total_m = sum(r.length_m for r in rows)
        total_t = sum(r.time_min for r in rows)

        # linhas do relatório consolidado
        lines: List[str] = []
        lines.append("Ordem de Impressão (prévia) — Relatório Consolidado")
        lines.append(f"Gerado: {stamp}")
        lines.append("Obs.: sem hora final (ainda não impresso).")
        lines.append("")
        lines.append("Resumo por rolo")
        lines.append("-" * 110)
        lines.append(f"{'Rolo':>4}  {'Tecido (rolo)':<14}  {'Blocos':>6}  {'Itens':>6}  {'Total (m)':>12}  {'Tempo':>12}")

        # também lista detalhada dos itens, estilo printlogs
        all_items_lines: List[str] = []
        all_items_lines.append("")
        all_items_lines.append("Pedidos (lista da fila)")
        all_items_lines.append("-" * 110)
        all_items_lines.append(f"{'#':>4}  {'Rolo':>4}  {'Tecido':<12}  {'Arquivo':<58}  {'Tamanho':>10}  {'Tempo':>10}")

        idx_global = 1
        for rn in roll_order:
            rr = by_roll[rn]
            jobs_only = [x for x in rr if not x.is_gap]
            gaps_only = [x for x in rr if x.is_gap]

            roll_m = sum(x.length_m for x in rr)
            roll_t = sum(x.time_min for x in rr)
            blocks = build_blocks(rr)

            # tecido principal do rolo (mais comum)
            fab_count: Dict[str, int] = {}
            for x in jobs_only:
                fab_count[x.fabric] = fab_count.get(x.fabric, 0) + 1
            main_fab = max(fab_count.items(), key=lambda kv: kv[1])[0] if fab_count else "—"

            lines.append(
                f"{rn:>4}  {main_fab:<14}  {len(blocks):>6}  {len(jobs_only):>6}  {fmt_m(roll_m):>12}  {fmt_min(roll_t):>12}"
            )

            # blocos do rolo
            lines.append(f"      Blocos do rolo {rn:02d}")
            lines.append(f"      {'#':>3}  {'Tecido':<12}  {'Itens':>5}  {'Total (m)':>12}  {'Tempo':>12}")
            for bi, (fab, bm, bt, bn) in enumerate(blocks, start=1):
                lines.append(f"      {bi:>3}  {fab:<12}  {bn:>5}  {fmt_m(bm):>12}  {fmt_min(bt):>12}")

            if gaps_only:
                gm = sum(g.length_m for g in gaps_only)
                gt = sum(g.time_min for g in gaps_only)
                lines.append(f"      Gaps: {fmt_m(gm)} | {fmt_min(gt)}")

            lines.append("")

            # lista de itens do rolo
            for x in jobs_only:
                name = x.name
                if len(name) > 58:
                    name = name[:57] + "…"
                all_items_lines.append(
                    f"{idx_global:>4}  {rn:>4}  {x.fabric:<12}  {name:<58}  {fmt_m(x.length_m):>10}  {fmt_min(x.time_min):>10}"
                )
                idx_global += 1

        lines.append("-" * 110)
        lines.append(f"Total geral: {fmt_m(total_m)}   |   Tempo total: {fmt_min(total_t)}")

        # junta tudo
        lines.extend(all_items_lines)

#        img = render_text_page(lines, font=font)
        if mirror:
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        out_path = out_dir / f"REL_CONSOLIDADO_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
        img.save(out_path, format="JPEG", quality=95, optimize=True)
        return out_path

    # init: já inicia em modo tecido com fila
    generate_queue()
    return frame