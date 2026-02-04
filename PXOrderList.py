from __future__ import annotations

import json
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, filedialog
from typing import List, Tuple


APP_NAME = "PXOrderList"
DEFAULT_OUTPUT_DIR = r"C:\Listas"

# -----------------------------
# JSON base (igual ao PXFlow)
# -----------------------------
BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": ""
}

# -----------------------------
# Regras de identificação
# -----------------------------
VALID_SIZES = {
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG",
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)


# -----------------------------
# Helpers
# -----------------------------
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def parse_qty_and_size(tok: str) -> Tuple[int, str]:
    t = tok.strip().upper()
    m = QTY_SIZE_RE.match(t)
    if m:
        return int(m.group(1)), m.group(2)
    return 1, t


def gender_from_size(size: str) -> str:
    s = size.upper()
    if "BL" in s:
        return "FE"
    if s.endswith("A"):
        return "C"
    return "MA"


def build_json_preview(orders: List[dict]) -> str:
    data = dict(BASE_JSON)
    data["orders"] = orders
    return json.dumps(data, ensure_ascii=False, indent=4)


def export_json(orders: List[dict], out_dir: str) -> str:
    ensure_dir(out_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = os.path.join(out_dir, f"List-{stamp}.json")

    data = dict(BASE_JSON)
    data["orders"] = orders

    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return fp


# -----------------------------
# Parser
# -----------------------------
@dataclass(frozen=True)
class ParsedRow:
    name: str
    number: str
    tams: Tuple[str, ...]
    s2: str
    s3: str


def parse_line(line: str) -> ParsedRow | None:
    raw = line.strip()
    if not raw:
        return None

    parts = [p.strip() for p in raw.split(",")]

    name = ""
    number = ""
    tams: List[str] = []
    extra: List[str] = []

    for tok in parts:
        if not tok:
            continue
        up = tok.upper()

        if up in VALID_SIZES or QTY_SIZE_RE.match(up):
            tams.append(up)
            continue

        if tok.isdigit() and not number:
            number = tok
            continue

        if not name:
            name = up
        else:
            extra.append(up)

    if not tams:
        raise ValueError("Nenhum TAM encontrado.")

    return ParsedRow(
        name=name,
        number=number,
        tams=tuple(tams[:4]),
        s2=extra[0] if len(extra) >= 1 else "",
        s3=extra[1] if len(extra) >= 2 else "",
    )


def process_text(text: str) -> Tuple[str, List[ParsedRow]]:
    rows: List[ParsedRow] = []

    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            r = parse_line(line)
            if r:
                rows.append(r)
        except Exception as e:
            raise ValueError(f"Linha {i}: {e}") from None

    rows.sort(key=lambda r: (r.name, r.number))

    max_tams = max(len(r.tams) for r in rows)
    has_s2 = any(r.s2 for r in rows)
    has_s3 = any(r.s3 for r in rows)

    out_lines: List[str] = []
    for r in rows:
        cols = [r.name, r.number]
        cols.extend(list(r.tams) + [""] * (max_tams - len(r.tams)))
        if has_s2:
            cols.append(r.s2)
        if has_s3:
            cols.append(r.s3)
        out_lines.append(",".join(cols))

    return "\n".join(out_lines), rows


# -----------------------------
# UI
# -----------------------------
class PXOrderListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        self._rows: List[ParsedRow] = []
        self._last_orders: List[dict] = []
        self.output_dir = DEFAULT_OUTPUT_DIR

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(top, text="PXOrderList — Organiza Lista", font=("Segoe UI", 12, "bold")).pack(side="left")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(btns, text="Gerar JSON", command=self.generate_json).pack(side="right", padx=6)
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="right")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada:").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none")
        self.txt_in.pack(fill="both", expand=True)

        tk.Label(right, text="Saída:").pack(anchor="w")
        self.txt_out = tk.Text(right, wrap="none")
        self.txt_out.pack(fill="both", expand=True)

    def on_process(self):
        raw = self.txt_in.get("1.0", "end")
        out, rows = process_text(raw)
        self.txt_out.delete("1.0", "end")
        self.txt_out.insert("1.0", out)
        self._rows = rows
        self._last_orders = []

    def generate_json(self):
        if not self._rows:
            messagebox.showwarning(APP_NAME, "Processe a lista antes.")
            return

        orders: List[dict] = []

        for r in self._rows:
            for tam in r.tams:
                qty, size = parse_qty_and_size(tam)
                gender = gender_from_size(size)

                orders.append({
                    "Name": r.name,
                    "Nickname": r.s2,
                    "Number": r.number,
                    "BloodType": r.s3,
                    "Gender": gender,
                    "ShortSleeve": f"{qty}-{size}",
                    "LongSleeve": "",
                    "Short": "",
                    "Pants": "",
                    "Tanktop": "",
                    "Vest": ""
                })

        self._last_orders = orders

        folder = filedialog.askdirectory(title="Escolha a pasta para salvar o JSON")
        if not folder:
            return

        fp = export_json(orders, folder)
        messagebox.showinfo(APP_NAME, f"JSON gerado:\n{fp}\n\nRegistros: {len(orders)}")

    def copy_output(self):
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")
        self._rows = []
        self._last_orders = []


def build_ui(parent):
    return PXOrderListFrame(parent)


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1000x600")
    build_ui(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
