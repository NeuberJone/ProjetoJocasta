from __future__ import annotations

import json
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Tuple

from core.config import load_config
from core.paths import open_in_explorer

APP_NAME = "PXOrderList"

# -----------------------------
# JSON base (igual ao PXFlow)
# -----------------------------
BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": "",
}

# -----------------------------
# PXCore / pastas
# -----------------------------
MODULE_NAME = "PXOrderList"


def _pxcore_base_dir() -> Path:
    cfg = load_config()
    base_dir = getattr(cfg, "base_dir", None) or r"C:\PXCore"
    return Path(base_dir)


def _default_output_dir() -> Path:
    out = _pxcore_base_dir() / "json" / MODULE_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


# -----------------------------
# Config persistente do módulo
# -----------------------------
APP_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "ProjetoJocasta" / MODULE_NAME
APP_DIR.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP_DIR / "config.json"

DEFAULT_CFG = {
    "output_dir": str(_default_output_dir()),
}


def load_module_cfg() -> dict:
    if CFG_PATH.exists():
        try:
            raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {**DEFAULT_CFG, **raw}
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_module_cfg(cfg: dict) -> None:
    try:
        CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# -----------------------------
# Regras de identificação
# -----------------------------
VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

# aceita "2-M", "10-BLP", "3-4A" etc.
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)


# -----------------------------
# Helpers
# -----------------------------
def ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def parse_qty_and_size(tok: str) -> Tuple[int, str]:
    """
    Aceita:
    - QTY-SIZE (3-G, 2-BLP, 5-12A)
    - SIZE sozinho (G, BLP, 12A) -> qty=1

    Retorna (qty, size)
    """
    t = (tok or "").strip()
    if not t:
        raise ValueError("Tamanho vazio (não permitido).")

    t = t.upper()
    m = QTY_SIZE_RE.match(t)
    if m:
        qty = int(m.group(1))
        size = m.group(2).strip().upper()
        if qty <= 0:
            raise ValueError("Quantidade inválida (<=0).")
        if size not in VALID_SIZES:
            raise ValueError(f"Tamanho inválido: {size}")
        return qty, size

    if t not in VALID_SIZES:
        raise ValueError(f"Tamanho inválido: {t}")
    return 1, t


def display_size_token(size_token: str) -> str:
    """
    Para LISTA ORGANIZADA:
    - "1-G" -> "G"
    - "3-G" -> "3-G"
    """
    st = (size_token or "").strip()
    if not st:
        return ""
    m = QTY_SIZE_RE.match(st)
    if m:
        qty = int(m.group(1))
        size = m.group(2).strip().upper()
        return size if qty == 1 else f"{qty}-{size}"
    return st.upper()


def normalize_size_token(tok: str) -> str:
    qty, size = parse_qty_and_size(tok)
    return f"{qty}-{size}"


def gender_from_size(size: str) -> str:
    """
    Regras:
    - Infantil (termina com A): Gender = C
    - Babylook (contém BL): Gender = FE
    - Senão: Gender = MA

    Divergência:
    - BL + A => erro
    """
    s = (size or "").strip().upper()
    has_bl = "BL" in s
    ends_a = s.endswith("A")

    if has_bl and ends_a:
        raise ValueError("Divergência: tamanho contém 'BL' e termina com 'A' (infantil).")
    if ends_a:
        return "C"
    if has_bl:
        return "FE"
    return "MA"


def build_json_preview(orders: List[dict]) -> str:
    data = dict(BASE_JSON)
    data["orders"] = orders
    return json.dumps(data, ensure_ascii=False, indent=4)


def export_json(orders: List[dict], out_dir: str | Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = Path(out_dir) / f"List-{stamp}.json"

    data = dict(BASE_JSON)
    data["orders"] = orders

    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return str(fp)


# -----------------------------
# Parser (OrderList)
# -----------------------------
def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _is_number(tok: str) -> bool:
    t = _clean_token(tok)
    return t.isdigit()  # preserva "01"


def _is_size(tok: str) -> bool:
    t = _upper(tok)
    if not t:
        return False
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    return bool(m and _upper(m.group(2)) in VALID_SIZES)


@dataclass(frozen=True)
class ParsedRow:
    name: str
    number: str
    tams: Tuple[str, ...]   # TAMs encontrados (1..4)
    s2: str                 # STRING2 (opcional)
    s3: str                 # STRING3 (opcional)


def parse_line(line: str) -> ParsedRow | None:
    raw = line.strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]  # preserva vazios

    name = ""
    number = ""
    tams: List[str] = []
    extra_strings: List[str] = []

    for tok in parts:
        t = _clean_token(tok)
        if not t:
            continue

        up = _upper(t)

        if _is_size(up):
            tams.append(up)
            continue

        if _is_number(t) and not number:
            number = up
            continue

        if not name:
            name = up
        else:
            extra_strings.append(up)

    if not tams:
        raise ValueError(f"Sem TAM1 reconhecido: {raw}")

    if len(tams) > 4:
        raise ValueError(f"Mais de 4 TAMs na linha: {raw}")

    s2 = extra_strings[0] if len(extra_strings) >= 1 else ""
    s3 = extra_strings[1] if len(extra_strings) >= 2 else ""

    return ParsedRow(
        name=name,
        number=number,
        tams=tuple(tams),
        s2=s2,
        s3=s3,
    )


def build_output(rows: List[ParsedRow]) -> str:
    if not rows:
        return ""

    max_tams = max(len(r.tams) for r in rows)
    has_s2 = any(r.s2 != "" for r in rows)
    has_s3 = any(r.s3 != "" for r in rows)

    out_lines: List[str] = []

    for r in rows:
        cols: List[str] = [r.name, r.number]

        tam_list = [display_size_token(t) for t in r.tams] + [""] * (max_tams - len(r.tams))
        cols.extend(tam_list)

        if has_s2:
            cols.append(r.s2)
        if has_s3:
            cols.append(r.s3)

        out_lines.append(",".join(cols))

    return "\n".join(out_lines)


def process_text(text: str) -> List[ParsedRow]:
    parsed: List[ParsedRow] = []

    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = parse_line(line)
            if row:
                parsed.append(row)
        except ValueError as e:
            raise ValueError(f"Linha {i}: {e}") from None

    parsed.sort(key=lambda r: (r.name, r.number))
    return parsed


def build_orders_from_orderlist(rows: List[ParsedRow]) -> List[dict]:
    """
    - OrderList pode ter múltiplos TAMs por linha.
    - Cada TAM vira 1 registro (order) no JSON, preenchendo ShortSleeve.
    - Nickname <- s2, BloodType <- s3
    """
    orders: List[dict] = []

    for r in rows:
        for tam in r.tams:
            st = normalize_size_token(tam)
            qty, size = parse_qty_and_size(st)
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
                "Vest": "",
            })

    return orders


# -----------------------------
# UI
# -----------------------------
class PXOrderListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        cfg = load_module_cfg()
        self.output_dir_var = tk.StringVar(value=cfg.get("output_dir", str(_default_output_dir())))
        self._rows: List[ParsedRow] = []
        self._last_orders: List[dict] = []
        self._last_json: str = ""

        # Header
        header = tk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(header, text="PXOrderList", font=("Segoe UI", 16, "bold")).pack(side="left")

        # Output dir
        out_row = tk.Frame(self)
        out_row.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(out_row, text="Pasta...", command=self.pick_output_folder).pack(side="left")
        tk.Button(out_row, text="Abrir pasta", command=self.open_output_folder).pack(side="left", padx=(6, 0))

        self.lbl_out = tk.Label(
            out_row,
            text=f"Pasta de saída: {self.output_dir_var.get()}",
            font=("Segoe UI", 9),
        )
        self.lbl_out.pack(side="right")

        # Body
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada:").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none", font=("Consolas", 10))
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        tab_list = tk.Frame(self.nb)
        tab_json = tk.Frame(self.nb)

        self.nb.add(tab_list, text="Lista organizada")
        self.nb.add(tab_json, text="Prévia JSON")

        tk.Label(tab_list, text="Saída organizada (copiada automaticamente):").pack(anchor="w")
        self.txt_out = tk.Text(tab_list, wrap="none", font=("Consolas", 10))
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(tab_json, text="Prévia do JSON:").pack(anchor="w")
        self.txt_json = tk.Text(tab_json, wrap="none", font=("Consolas", 10))
        self.txt_json.pack(fill="both", expand=True, pady=(6, 0))
        self._set_text_readonly(self.txt_json, True)

        # Buttons
        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="left")
        tk.Button(btns, text="Copiar lista", command=self.copy_list).pack(side="left", padx=6)
        tk.Button(btns, text="Copiar JSON", command=self.copy_json).pack(side="left", padx=6)
        tk.Button(btns, text="Gerar JSON", command=self.generate_json).pack(side="right")
        tk.Button(btns, text="Processar", command=self.process_and_preview).pack(side="right", padx=6)

        # Status
        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 10))

        # Exemplo
        self.txt_in.insert(
            "1.0",
            "G,JÃO,10\n"
            "JOÃO,5,G,M\n"
            "MANEL,PP\n"
            "JUACA,JUSÉ,PP\n"
        )

    def _set_text_readonly(self, txt: tk.Text, readonly: bool) -> None:
        txt.configure(state=("disabled" if readonly else "normal"))

    def _refresh_output_label(self) -> None:
        self.lbl_out.config(text=f"Pasta de saída: {self.output_dir_var.get()}")

    def pick_output_folder(self) -> None:
        folder = filedialog.askdirectory(title="PXOrderList - Escolha a pasta para salvar o JSON")
        if folder:
            self.output_dir_var.set(folder)
            cfg = load_module_cfg()
            cfg["output_dir"] = folder
            save_module_cfg(cfg)
            self._refresh_output_label()
            self.status_var.set(f"Pasta de saída: {folder}")

    def open_output_folder(self) -> None:
        try:
            out = self.ensure_output_dir()
            open_in_explorer(Path(out))
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Não foi possível abrir a pasta.\n\n{e}")

    def ensure_output_dir(self) -> str:
        out = self.output_dir_var.get().strip() or str(_default_output_dir())
        ensure_dir(out)
        return out

    def clear_all(self) -> None:
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")

        self._set_text_readonly(self.txt_json, False)
        self.txt_json.delete("1.0", "end")
        self._set_text_readonly(self.txt_json, True)

        self._rows = []
        self._last_orders = []
        self._last_json = ""
        self.status_var.set("")

    def copy_list(self) -> None:
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há lista organizada para copiar.")
            return

        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

        self.status_var.set("Lista organizada copiada.")

    def copy_json(self) -> None:
        if not self._last_json.strip():
            messagebox.showwarning(APP_NAME, "Ainda não há prévia do JSON.\nClique em Processar.")
            return

        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(self._last_json)
        root.update()

        self.status_var.set("JSON copiado.")

    def process_and_preview(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        try:
            rows = process_text(raw)
            if not rows:
                messagebox.showwarning(APP_NAME, "Nenhuma linha válida encontrada.")
                return

            organized = build_output(rows)

            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", organized)

            # copia lista organizada sempre
            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(organized)
            root.update()

            orders = build_orders_from_orderlist(rows)
            preview = build_json_preview(orders)

            self._rows = rows
            self._last_orders = orders
            self._last_json = preview

            self._set_text_readonly(self.txt_json, False)
            self.txt_json.delete("1.0", "end")
            self.txt_json.insert("1.0", preview)
            self._set_text_readonly(self.txt_json, True)

            self.status_var.set(f"✅ Processado: {len(rows)} linha(s) | lista copiada | prévia JSON pronta.")
            self.nb.select(0)

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def generate_json(self) -> None:
        if not self._last_orders:
            self.process_and_preview()
            if not self._last_orders:
                return

        try:
            out_dir = self.ensure_output_dir()
            fp = export_json(self._last_orders, out_dir)

            messagebox.showinfo(APP_NAME, f"JSON gerado:\n{fp}\n\nRegistros: {len(self._last_orders)}")
            self.status_var.set(f"✅ JSON gerado: {fp} | Registros: {len(self._last_orders)}")
            self.nb.select(1)

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")


def build_ui(parent):
    return PXOrderListFrame(parent)


def main() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1200x720")
    root.minsize(1000, 620)

    ui = build_ui(root)
    ui.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()