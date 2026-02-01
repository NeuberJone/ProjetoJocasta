from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import List, Tuple


APP_NAME = "PXTotaList"

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    # Infantil
    "2A", "3A", "4A", "5A", "6A", "7A", "8A", "9A",
    "10A", "11A", "12A", "14A", "16A",
}

QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")


def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _forbid_quotes(line_no: int, tok: str) -> None:
    if tok and FORBIDDEN_QUOTE_RE.search(tok):
        raise ValueError(
            f"Linha {line_no}: não use aspas para vazio (\"\"), token: {tok!r}"
        )


def _is_size_value(tok: str) -> bool:
    t = _upper(tok)
    if not t:
        return False
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    return bool(m and _upper(m.group(2)) in VALID_SIZES)


def _gender_of_size(size_token: str) -> str:
    s = _upper(size_token)
    if "BL" in s:
        return "FE"
    if s.endswith("A") and s in VALID_SIZES:
        return "C"
    return "MA"


@dataclass(frozen=True)
class Row:
    name: str
    number: str
    pieces: Tuple[str, ...]  # sempre 6 internamente
    nickname: str
    blood: str


def parse_line_positional(line: str, line_no: int) -> list[Row]:
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return []

    parts = [_clean_token(p) for p in raw.split(",")]
    for tok in parts:
        _forbid_quotes(line_no, tok)

    # ✅ Caso especial: 1 token só (ex: "GG")
    if len(parts) == 1:
        only = _clean_token(parts[0])
        if only and _is_size_value(only):
            return [Row(
                name="",
                number="",
                pieces=(_upper(only), "", "", "", "", ""),
                nickname="",
                blood=""
            )]
        return [Row(
            name=_upper(only),
            number="",
            pieces=("", "", "", "", "", ""),
            nickname="",
            blood=""
        )]

    while len(parts) < 2:
        parts.append("")

    name = _upper(parts[0])
    number = _clean_token(parts[1])

    rest = parts[2:]
    while len(rest) < 6:
        rest.append("")

    # última peça válida
    last_piece_pos = 0
    for i in range(6):
        v = _clean_token(rest[i])
        if v and _is_size_value(v):
            last_piece_pos = i + 1

    pieces_norm = [""] * 6
    extras: List[str] = []

    for i in range(6):
        v = _clean_token(rest[i])
        pos = i + 1

        if pos <= last_piece_pos:
            if not v:
                pieces_norm[i] = ""
            else:
                if not _is_size_value(v):
                    raise ValueError(f"Linha {line_no}: valor inválido na {pos}ª peça: {v!r}")
                pieces_norm[i] = _upper(v)
        else:
            if v:
                extras.append(_upper(v))

    if len(rest) > 6:
        for v in rest[6:]:
            vv = _clean_token(v)
            if vv:
                extras.append(_upper(vv))

    nickname = extras[0] if len(extras) >= 1 else ""
    blood = extras[1] if len(extras) >= 2 else ""
    if len(extras) > 2:
        raise ValueError(f"Linha {line_no}: extras demais após as peças (máx 2: apelido e tipo).")

    # ✅ Separa por gênero se misturar
    filled_positions = [(idx, val) for idx, val in enumerate(pieces_norm) if val]
    if not filled_positions:
        return [Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(pieces_norm),
            nickname=nickname,
            blood=blood
        )]

    genders_present = set(_gender_of_size(val) for _, val in filled_positions)
    if len(genders_present) == 1:
        return [Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(pieces_norm),
            nickname=nickname,
            blood=blood
        )]

    out_rows: list[Row] = []
    for g in ["MA", "FE", "C"]:
        if g not in genders_present:
            continue
        p = [""] * 6
        for idx, val in filled_positions:
            if _gender_of_size(val) == g:
                p[idx] = val
        out_rows.append(Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(p),
            nickname=nickname,
            blood=blood
        ))

    return out_rows


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
        rows.extend(parse_line_positional(line, i))

    rows.sort(key=lambda r: (r.name, r.number))
    return build_output_dynamic(rows)


# =================
# UI (igual ao Lite)
# =================
class PXTotaListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(
            top,
            text="PXTotaList — posicional (NOME, NÚMERO, 1ª..6ª peça) + extras (apelido/tipo) — saída dinâmica",
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

        # exemplo (opcional)
        self.txt_in.insert(
            "1.0",
            "GG\n"
            "ANA,10,BLP,M\n"
            "JOÃO,5,G,M\n"
            "JUACA,,PP,,,JUSÉ\n"
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
