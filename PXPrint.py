from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


APP_NAME = "PXPrint"
COLUMNS = [
    "timestamp",
    "pedido",
    "lista",
    "cliente",
    "maquina",
    "tipo",
    "quantidade",
    "unidade",
    "obs",
]


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "ProjetoJocasta" / "PXPrint"
    d.mkdir(parents=True, exist_ok=True)
    return d


def csv_path() -> Path:
    return _appdata_dir() / "pxprint_log.csv"


def ensure_csv() -> None:
    fp = csv_path()
    if not fp.exists():
        with fp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()


def read_rows() -> list[dict]:
    ensure_csv()
    with csv_path().open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r)


def append_row(row: dict) -> None:
    ensure_csv()
    with csv_path().open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writerow(row)


def _safe_float(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    s = s.replace(",", ".")
    float(s)  # valida
    return s


@dataclass
class Filters:
    search: str
    maquina: str
    tipo: str


class PXPrintUI(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        ensure_csv()

        # ===== Form =====
        form = ttk.LabelFrame(self, text="Registro rápido")
        form.pack(fill="x", padx=10, pady=10)

        self.var_pedido = tk.StringVar()
        self.var_lista = tk.StringVar()
        self.var_cliente = tk.StringVar()
        self.var_maquina = tk.StringVar(value="M1")
        self.var_tipo = tk.StringVar(value="Impressão")
        self.var_qtd = tk.StringVar()
        self.var_unidade = tk.StringVar(value="m")
        self.var_obs = tk.StringVar()

        # linha 1
        ttk.Label(form, text="Pedido").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_pedido, width=22).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Lista").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_lista, width=22).grid(row=0, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Cliente").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_cliente, width=26).grid(row=0, column=5, sticky="w", padx=6, pady=4)

        # linha 2
        ttk.Label(form, text="Máquina").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        cb_m = ttk.Combobox(form, textvariable=self.var_maquina, values=["M1", "M2", "Calandra"], width=19, state="readonly")
        cb_m.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Tipo").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        cb_t = ttk.Combobox(form, textvariable=self.var_tipo, values=["Impressão", "Reimpressão"], width=19, state="readonly")
        cb_t.grid(row=1, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(form, text="Qtd").grid(row=1, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_qtd, width=10).grid(row=1, column=5, sticky="w", padx=(6, 0), pady=4)

        cb_u = ttk.Combobox(form, textvariable=self.var_unidade, values=["m", "folhas"], width=8, state="readonly")
        cb_u.grid(row=1, column=5, sticky="w", padx=(78, 6), pady=4)

        ttk.Label(form, text="Obs").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_obs, width=92).grid(row=2, column=1, columnspan=5, sticky="we", padx=6, pady=4)

        btns = ttk.Frame(form)
        btns.grid(row=3, column=0, columnspan=6, sticky="we", padx=6, pady=(6, 8))
        ttk.Button(btns, text="Salvar lançamento", command=self.on_save).pack(side="left")
        ttk.Button(btns, text="Limpar", command=self.on_clear).pack(side="left", padx=6)
        ttk.Button(btns, text="Exportar Excel", command=self.on_export_excel).pack(side="right")

        # ===== Filters =====
        filters = ttk.LabelFrame(self, text="Filtros")
        filters.pack(fill="x", padx=10, pady=(0, 10))

        self.var_search = tk.StringVar()
        self.var_f_maquina = tk.StringVar(value="(todas)")
        self.var_f_tipo = tk.StringVar(value="(todos)")

        ttk.Label(filters, text="Buscar").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        e = ttk.Entry(filters, textvariable=self.var_search, width=40)
        e.grid(row=0, column=1, sticky="w", padx=6, pady=6)
        e.bind("<KeyRelease>", lambda _e: self.refresh_table())

        ttk.Label(filters, text="Máquina").grid(row=0, column=2, sticky="w", padx=6, pady=6)
        cbfm = ttk.Combobox(filters, textvariable=self.var_f_maquina,
                            values=["(todas)", "M1", "M2", "Calandra"], width=14, state="readonly")
        cbfm.grid(row=0, column=3, sticky="w", padx=6, pady=6)
        cbfm.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        ttk.Label(filters, text="Tipo").grid(row=0, column=4, sticky="w", padx=6, pady=6)
        cbft = ttk.Combobox(filters, textvariable=self.var_f_tipo,
                            values=["(todos)", "Impressão", "Reimpressão"], width=14, state="readonly")
        cbft.grid(row=0, column=5, sticky="w", padx=6, pady=6)
        cbft.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        ttk.Button(filters, text="Atualizar", command=self.refresh_table).grid(row=0, column=6, padx=6, pady=6)

        # ===== Table =====
        table = ttk.Frame(self)
        table.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree = ttk.Treeview(table, columns=COLUMNS, show="headings", height=14)
        for col in COLUMNS:
            self.tree.heading(col, text=col)
            w = 120
            if col in ("pedido", "lista", "cliente"):
                w = 140
            if col == "obs":
                w = 320
            self.tree.column(col, width=w, anchor="w")

        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.refresh_table()

    def on_save(self):
        pedido = self.var_pedido.get().strip()
        lista = self.var_lista.get().strip()
        cliente = self.var_cliente.get().strip()
        maquina = self.var_maquina.get().strip()
        tipo = self.var_tipo.get().strip()
        unidade = self.var_unidade.get().strip()
        obs = self.var_obs.get().strip()

        try:
            qtd = _safe_float(self.var_qtd.get())
        except Exception:
            messagebox.showerror("Quantidade inválida", "Quantidade precisa ser numérica (ex: 12.5).")
            return

        if not pedido and not lista and not cliente:
            messagebox.showwarning("Faltando dados", "Preencha pelo menos Pedido, Lista ou Cliente.")
            return

        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pedido": pedido,
            "lista": lista,
            "cliente": cliente,
            "maquina": maquina,
            "tipo": tipo,
            "quantidade": qtd,
            "unidade": unidade,
            "obs": obs,
        }
        append_row(row)
        self.on_clear(keep_maquina=True, keep_tipo=True, keep_unidade=True)
        self.refresh_table()

    def on_clear(self, keep_maquina=False, keep_tipo=False, keep_unidade=False):
        self.var_pedido.set("")
        self.var_lista.set("")
        self.var_cliente.set("")
        if not keep_maquina:
            self.var_maquina.set("M1")
        if not keep_tipo:
            self.var_tipo.set("Impressão")
        self.var_qtd.set("")
        if not keep_unidade:
            self.var_unidade.set("m")
        self.var_obs.set("")

    def _filters(self) -> Filters:
        return Filters(
            search=self.var_search.get().strip().lower(),
            maquina=self.var_f_maquina.get(),
            tipo=self.var_f_tipo.get(),
        )

    def refresh_table(self):
        rows = read_rows()
        f = self._filters()

        def match(r: dict) -> bool:
            if f.maquina != "(todas)" and (r.get("maquina") != f.maquina):
                return False
            if f.tipo != "(todos)" and (r.get("tipo") != f.tipo):
                return False
            if f.search:
                blob = " ".join(str(r.get(c, "")) for c in COLUMNS).lower()
                return f.search in blob
            return True

        filtered = [r for r in rows if match(r)]
        filtered.reverse()  # mais recente em cima

        self.tree.delete(*self.tree.get_children())
        for r in filtered:
            self.tree.insert("", "end", values=[r.get(c, "") for c in COLUMNS])

    def on_export_excel(self):
        try:
            import pandas as pd  # type: ignore
        except Exception:
            messagebox.showerror("Dependência faltando", "Para exportar Excel: pip install pandas openpyxl")
            return

        rows = read_rows()
        if not rows:
            messagebox.showinfo("Nada para exportar", "Ainda não há lançamentos.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            title="Salvar como",
        )
        if not path:
            return

        df = pd.DataFrame(rows, columns=COLUMNS)
        df.to_excel(path, index=False)
        messagebox.showinfo("Exportado", f"Exportado com sucesso:\n{path}")


def build_ui(parent):
    """
    Obrigatório para rodar dentro do JocastaHub:
    o Hub chama build_ui(tab) e dá pack no retorno.
    """
    return PXPrintUI(parent)
