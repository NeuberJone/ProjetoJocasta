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
    if "BL" in size_token:
        return "FE"
    if size_token.endswith("A") and size_token in VALID_SIZES:
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

    # Caso especial: tamanho sozinho
    if len(parts) == 1:
        only = parts[0]
        if _is_size_value(only):
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

    last_piece_pos = 0
    for i in range(6):
        if _is_size_value(rest[i]):
            last_piece_pos = i + 1

    pieces = [""] * 6
    extras: List[str] = []

    for i in range(6):
        v = _clean_token(rest[i])
        pos = i + 1

        if pos <= last_piece_pos:
            if v:
                if not _is_size_value(v):
                    raise ValueError(
                        f"Linha {line_no}: valor inválido na {pos}ª peça: {v!r}"
                    )
                pieces[i] = _upper(v)
        else:
            if v:
                extras.append(_upper(v))

    if len(rest) > 6:
        for v in rest[6:]:
            if v:
                extras.append(_upper(v))

    nickname = extras[0] if len(extras) >= 1 else ""
    blood = extras[1] if len(extras) >= 2 else ""
    if len(extras) > 2:
        raise ValueError(
            f"Linha {line_no}: extras demais após as peças (máx 2)"
        )

    filled = [(i, v) for i, v in enumerate(pieces) if v]
    if not filled:
        return [Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(pieces),
            nickname=nickname,
            blood=blood
        )]

    genders = set(_gender_of_size(v) for _, v in filled)
    if len(genders) == 1:
        return [Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(pieces),
            nickname=nickname,
            blood=blood
        )]

    out: list[Row] = []
    for g in ("MA", "FE", "C"):
        if g not in genders:
            continue
        p = [""] * 6
        for i, v in filled:
            if _gender_of_size(v) == g:
                p[i] = v
        out.append(Row(
            name=name,
            number=_upper(number) if number else "",
            pieces=tuple(p),
            nickname=nickname,
            blood=blood
        ))

    return out


def build_output_dynamic(rows: List[Row]) -> str:
    if not rows:
        return ""

    k = max(
        (i for r in rows for i, v in enumerate(r.pieces, start=1) if v),
        default=1
    )

    has_nick = any(r.nickname for r in rows)
    has_blood = any(r.blood for r in rows)

    out = []
    for r in rows:
        cols = [r.name, r.number]
        cols.extend(r.pieces[:k])
        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)
        out.append(",".join(cols))

    return "\n".join(out)


def process_text(text: str) -> str:
    rows: List[Row] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows.extend(parse_line_positional(line, i))

    rows.sort(key=lambda r: (r.name, r.number))
    return build_output_dynamic(rows)


# ================= UI =================

class PXTotaListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        tk.Label(
            self,
            text="PXTotaList — parser posicional com separação automática de gêneros",
            font=("Segoe UI", 12, "bold")
        ).pack(pady=8)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10)

        self.txt_in = tk.Text(body, wrap="none")
        self.txt_out = tk.Text(body, wrap="none")

        self.txt_in.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.txt_out.pack(side="left", fill="both", expand=True, padx=(5, 0))

        btns = tk.Frame(self)
        btns.pack(pady=8)

        tk.Button(btns, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(
            side="right", padx=6
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

            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(out)
            root.update()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def copy_output(self) -> None:
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()


def build_ui(parent):
    return PXTotaListFrame(parent)


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1000x600")
    build_ui(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
