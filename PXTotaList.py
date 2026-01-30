from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import List, Tuple


APP_NAME = "PXTotaList"

# Mesmas regras do Lite (posicional)
VALID_SIZES = {
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG",
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    "2A", "3A", "4A", "5A", "6A", "7A", "8A", "9A", "10A", "11A", "12A", "14A", "16A",
}

QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")


def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _forbid_quotes(line_no: int, tok: str) -> None:
    if tok and FORBIDDEN_QUOTE_RE.search(tok):
        raise ValueError(f"Linha {line_no}: não use aspas para vazio (\"\"), token: {tok!r}")


def _is_size_value(tok: str) -> bool:
    t = _upper(tok)
    if not t:
        return False
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    if m and _upper(m.group(2)) in VALID_SIZES:
        return True
    return False


@dataclass(frozen=True)
class Row:
    name: str
    number: str
    pieces: Tuple[str, ...]  # até 6 (posicionais)
    nickname: str
    blood: str


def parse_line_positional(line: str, line_no: int) -> Row | None:
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return None

    parts = [p for p in raw.split(",")]
    parts = [_clean_token(p) for p in parts]

    for tok in parts:
        _forbid_quotes(line_no, tok)

    while len(parts) < 2:
        parts.append("")

    name = _upper(parts[0])
    number = _clean_token(parts[1])

    piece_cols = parts[2:8]
    while len(piece_cols) < 6:
        piece_cols.append("")

    pieces_norm: List[str] = []
    for i, val in enumerate(piece_cols, start=1):
        v = _clean_token(val)
        if not v:
            pieces_norm.append("")
            continue
        if not _is_size_value(v):
            raise ValueError(f"Linha {line_no}: valor inválido na {i}ª peça: {v!r}")
        pieces_norm.append(_upper(v))

    nickname = _upper(parts[8]) if len(parts) >= 9 and parts[8] else ""
    blood = _upper(parts[9]) if len(parts) >= 10 and parts[9] else ""

    if len(parts) > 10:
        extra = ",".join(parts[10:])
        raise ValueError(f"Linha {line_no}: colunas extras não suportadas: {extra!r}")

    return Row(
        name=name,
        number=_upper(number) if number else "",
        pieces=tuple(pieces_norm),
        nickname=nickname,
        blood=blood,
    )


def build_output_dynamic(rows: List[Row]) -> str:
    if not rows:
        return ""

    k = 0
    for r in rows:
        for idx, val in enumerate(r.pieces, start=1):
            if val:
                k = max(k, idx)
    if k == 0:
        k = 1

    has_nick = any(r.nickname for r in rows)
    has_blood = any(r.blood for r in rows)

    out_lines: List[str] = []
    for r in rows:
        cols: List[str] = [r.name, r.number]
        cols.extend(list(r.pieces[:k]))
        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)
        out_lines.append(",".join(cols))

    return "\n".join(out_lines)


def process_text(text: str) -> str:
    rows: List[Row] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        row = parse_line_positional(line, i)
        if row:
            rows.append(row)

    rows.sort(key=lambda r: (r.name, r.number))
    return build_output_dynamic(rows)


# -----------------------------
# UI (Lite) + suporte a Hub
# -----------------------------
class PXTotaListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(
            top,
            text="PXTotaList — posicional (NOME, NÚMERO, 1ª..6ª peça, apelido, tipo) — saída dinâmica",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="right")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada (posicional por vírgula):").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none")
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Saída (dinâmica):").pack(anchor="w")
        self.txt_out = tk.Text(right, wrap="none")
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        self.txt_in.insert(
            "1.0",
            "GPT,10,,,,G,\n"
            "JOÃO,5,G,M,,,\n"
            "JUACA,,PP,,,,\n"
            "JÃO,10,,,PP,,\n"
            "MANEL,,PP,GG,,,\n"
        )

    def on_process(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        try:
            out = process_text(raw)
            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", out)

            # ✅ Copia automaticamente, sem mensagem
            win = self.txt_out.winfo_toplevel()
            win.clipboard_clear()
            win.clipboard_append(out)
            win.update()

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def copy_output(self) -> None:
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há saída para copiar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def clear_all(self) -> None:
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")


def build_ui(parent):
    return PXTotaListFrame(parent)


def main() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1000x600")
    root.minsize(900, 520)

    ui = build_ui(root)
    ui.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
