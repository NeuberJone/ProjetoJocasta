from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox


APP_NAME = "PXSort Lite"
SEP = "\\\\"

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG"
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG"
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}


@dataclass(frozen=True)
class Item:
    name: str
    number: str


def _clean_token(s: str) -> str:
    t = s.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    return t


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def _is_number(tok: str) -> bool:
    return tok.isdigit()


def parse_line(line: str) -> Optional[Tuple[str, Item]]:
    raw = line.strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None

    size_idx = None
    size_val = None
    for i, p in enumerate(parts):
        up = p.upper()
        if up in VALID_SIZES:
            size_idx = i
            size_val = up
            break

    if size_idx is None or size_val is None:
        return None

    remaining = parts[:size_idx] + parts[size_idx + 1 :]
    if not remaining:
        return None

    number = ""
    number_idx = None
    for i in range(len(remaining) - 1, -1, -1):
        if _is_number(remaining[i]):
            number = remaining[i]
            number_idx = i
            break

    if number_idx is not None:
        name_parts = remaining[:number_idx] + remaining[number_idx + 1 :]
    else:
        name_parts = remaining

    name = _normalize(" ".join(name_parts))
    number = _normalize(number)

    if not name:
        return None

    return size_val, Item(name=name, number=number)


def sort_key(it: Item) -> tuple[str, str]:
    return (it.name, it.number)


def process_text(text: str) -> tuple[str, List[str]]:
    buckets: Dict[str, List[Item]] = {}
    ignored: List[str] = []

    for line in text.splitlines():
        parsed = parse_line(line)
        if not parsed:
            if line.strip():
                ignored.append(line)
            continue
        size, item = parsed
        buckets.setdefault(size, []).append(item)

    for s in list(buckets.keys()):
        buckets[s] = sorted(buckets[s], key=sort_key)

    out_lines: List[str] = []
    for size in sorted(buckets.keys()):
        out_lines.append(f"[{size}]")
        for it in buckets[size]:
            out_lines.append(f"{it.name}{SEP}{it.number}")
        out_lines.append("")

    return "\n".join(out_lines).strip(), ignored


class AppFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Button(top, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(top, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(top, text="Limpar", command=self.clear_all).pack(side="right")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada:").pack(anchor="w")
        self.inp = tk.Text(left, wrap="word")
        self.inp.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Saída:").pack(anchor="w")
        self.out = tk.Text(right, wrap="word")
        self.out.pack(fill="both", expand=True, pady=(6, 0))

        self.inp.insert(
            "1.0",
            "M, João, 10\n"
            "Pedro, G, 01\n"
            "Maria, M\n"
            "2A, Lucas, 5\n"
            "Ana, 4A\n"
        )

    def on_process(self) -> None:
        raw = self.inp.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        output, ignored = process_text(raw)
        self.out.delete("1.0", "end")
        self.out.insert("1.0", output)

        if ignored:
            messagebox.showinfo(APP_NAME, f"Linhas ignoradas (sem tamanho reconhecido): {len(ignored)}")

    def copy_output(self) -> None:
        text = self.out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há saída para copiar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        messagebox.showinfo(APP_NAME, "Saída copiada para a área de transferência.")

    def clear_all(self) -> None:
        self.inp.delete("1.0", "end")
        self.out.delete("1.0", "end")


def build_ui(parent):
    return AppFrame(parent)


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
