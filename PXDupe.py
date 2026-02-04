from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox

from tkinterdnd2 import TkinterDnD, DND_FILES  # pip install tkinterdnd2


# =========================
# PXDupe - Config
# =========================
APP_NAME = "PXDupe"
CONFIG_FILE = "pxdupe_config.json"

SEP = "\\\\"  # duas barras (Power Duplicate)

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG"
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG"
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}


# =========================
# Model
# =========================
@dataclass(frozen=True)
class Item:
    name: str
    number: str  # pode ser ""


# =========================
# Config
# =========================
def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================
# Parse / Regras (iguais ao Sort/Lite)
# =========================
def _clean_token(s: str) -> str:
    t = (s or "").strip()
    # se vier entre aspas, remove
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    return t


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text.upper()


def _looks_like_number(token: str) -> bool:
    return token.isdigit()


def parse_line(line: str) -> Optional[Tuple[str, Item]]:
    raw = (line or "").strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]
    parts = [p for p in parts if p]  # remove vazios

    if not parts:
        return None

    # tamanho: primeiro token que bate
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

    # número: último token numérico (de trás pra frente)
    number = ""
    number_idx = None
    for i in range(len(remaining) - 1, -1, -1):
        if _looks_like_number(remaining[i]):
            number = remaining[i]
            number_idx = i
            break

    if number_idx is not None:
        name_parts = remaining[:number_idx] + remaining[number_idx + 1 :]
    else:
        name_parts = remaining

    name = _normalize_text(" ".join(name_parts))
    number = _normalize_text(number)

    if not name:
        return None

    return size_val, Item(name=name, number=number)


def sort_key(it: Item) -> Tuple[str, str]:
    return (it.name, it.number)


def build_buckets(text: str) -> Tuple[Dict[str, List[Item]], List[str]]:
    buckets: Dict[str, List[Item]] = {}
    ignored: List[str] = []

    for line in (text or "").splitlines():
        parsed = parse_line(line)
        if not parsed:
            if line.strip():
                ignored.append(line)
            continue
        size, item = parsed
        buckets.setdefault(size, []).append(item)

    for s in list(buckets.keys()):
        buckets[s] = sorted(buckets[s], key=sort_key)

    return buckets, ignored


def process_text_lite_output(text: str) -> Tuple[str, List[str]]:
    """
    Saída pronta p/ colar no Power Duplicate:
      [M]
      NOME\\NUM
      ...
      (linha em branco)
      [G]
      ...
    """
    buckets, ignored = build_buckets(text)

    out_lines: List[str] = []
    for size in sorted(buckets.keys()):
        out_lines.append(f"[{size}]")
        for it in buckets[size]:
            out_lines.append(f"{it.name}{SEP}{it.number}")
        out_lines.append("")

    output_str = "\n".join(out_lines).strip()
    return output_str, ignored


def write_zip(
    buckets: Dict[str, List[Item]],
    zip_path: Path,
    include_ignored: bool,
    ignored: List[str],
) -> Dict[str, int]:
    """
    Exporta um ZIP com:
      - {SIZE}.txt: linhas NAME\\NUMBER
      - opcional IGNORADAS.txt
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Dict[str, int] = {}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for size in sorted(buckets.keys()):
            items = buckets[size]
            counts[size] = len(items)
            content = "".join([f"{it.name}{SEP}{it.number}\n" for it in items])
            zf.writestr(f"{size}.txt", content.encode("utf-8"))

        if include_ignored and ignored:
            zf.writestr("IGNORADAS.txt", ("\n".join(ignored)).encode("utf-8"))

    return counts


# =========================
# UI (Frame p/ Hub + standalone)
# =========================
class PXDupeFrame(tk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)

        self.cfg = load_config()
        default_export = self.cfg.get("export_dir") or r"C:\Dupe"

        self.export_dir_var = tk.StringVar(value=default_export)
        self.include_ignored_var = tk.BooleanVar(value=bool(self.cfg.get("include_ignored", True)))

        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(top, text="Pasta de exportação:").pack(side="left")
        tk.Entry(top, textvariable=self.export_dir_var).pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(top, text="Escolher...", command=self.choose_export_dir).pack(side="left", padx=(0, 6))
        tk.Button(top, text="Abrir pasta", command=self.open_export_dir).pack(side="left")

        opt = tk.Frame(self)
        opt.pack(fill="x", padx=10, pady=(0, 8))

        tk.Checkbutton(
            opt,
            text="Incluir IGNORADAS.txt no ZIP (linhas sem tamanho reconhecido)",
            variable=self.include_ignored_var,
            command=self.persist_options,
        ).pack(side="left")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada: (cole ou solte um .txt)").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="word", height=18)
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Saída (pronta p/ Power Duplicate):").pack(anchor="w")
        self.txt_out = tk.Text(right, wrap="word", height=18)
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        # Drag & Drop no input
        self.txt_in.drop_target_register(DND_FILES)
        self.txt_in.dnd_bind("<<Drop>>", self.on_drop)

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Importar TXT...", command=self.import_txt).pack(side="left")
        tk.Button(btns, text="Limpar", command=self.clear).pack(side="left", padx=6)

        tk.Button(btns, text="Exportar ZIP", command=self.export_zip).pack(side="right")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(btns, text="Processar", command=self.process).pack(side="right", padx=6)

        # Exemplo
        self.txt_in.insert(
            "1.0",
            "M, João, 10\n"
            "Pedro, G, 01\n"
            "Maria, M\n"
            "2A, Lucas, 5\n"
            "Ana, 4A\n"
        )

    # --------- config helpers
    def persist_options(self) -> None:
        self.cfg["export_dir"] = self.export_dir_var.get().strip()
        self.cfg["include_ignored"] = bool(self.include_ignored_var.get())
        save_config(self.cfg)

    def choose_export_dir(self) -> None:
        folder = filedialog.askdirectory(title="Escolher pasta de exportação")
        if not folder:
            return
        self.export_dir_var.set(folder)
        self.persist_options()

    def open_export_dir(self) -> None:
        p = Path(self.export_dir_var.get().strip() or r"C:\Dupe")
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    # --------- IO
    def clear(self) -> None:
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")

    def on_drop(self, event) -> None:
        data = (event.data or "").strip()
        paths = re.findall(r"\{([^}]+)\}", data) or data.split()
        if not paths:
            return

        txts = [p for p in paths if p.lower().endswith(".txt")]
        if not txts:
            messagebox.showwarning(APP_NAME, "Solte um arquivo .txt.")
            return

        self._load_file(txts[0])

    def import_txt(self) -> None:
        initial = self.cfg.get("last_import_dir") or str(Path.home())
        fp = filedialog.askopenfilename(
            title="Importar TXT",
            initialdir=initial,
            filetypes=[("TXT", "*.txt"), ("Todos", "*.*")],
        )
        if not fp:
            return
        self.cfg["last_import_dir"] = str(Path(fp).parent)
        save_config(self.cfg)
        self._load_file(fp)

    def _load_file(self, fp: str) -> None:
        p = Path(fp)
        try:
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = p.read_text(encoding="latin-1", errors="replace")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao ler arquivo:\n\n{e}")
            return

        self.txt_in.delete("1.0", "end")
        self.txt_in.insert("1.0", content)

    # --------- actions
    def process(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        output, ignored = process_text_lite_output(raw)

        self.txt_out.delete("1.0", "end")
        self.txt_out.insert("1.0", output)

        # informa ignoradas sem bloquear
        if ignored:
            messagebox.showinfo(
                APP_NAME,
                f"Processado com sucesso.\n\nLinhas ignoradas (sem tamanho reconhecido): {len(ignored)}"
            )

    def copy_output(self) -> None:
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há saída para copiar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        messagebox.showinfo(APP_NAME, "Saída copiada para a área de transferência.")

    def export_zip(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Cole ou importe uma lista antes de exportar.")
            return

        # garante pasta
        export_dir = Path(self.export_dir_var.get().strip() or r"C:\Dupe")
        export_dir.mkdir(parents=True, exist_ok=True)

        # salva config
        self.cfg["export_dir"] = str(export_dir)
        save_config(self.cfg)

        buckets, ignored = build_buckets(raw)
        if not buckets:
            messagebox.showinfo(
                APP_NAME,
                "Nenhum tamanho reconhecido.\nVerifique se contém M, G, 2A, 4A, etc."
            )
            return

        # nome automático
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        zip_path = export_dir / f"PXDupe-{stamp}.zip"

        counts = write_zip(
            buckets=buckets,
            zip_path=zip_path,
            include_ignored=self.include_ignored_var.get(),
            ignored=ignored,
        )

        msg = "ZIP exportado com sucesso!\n\n"
        msg += f"Arquivo:\n{zip_path}\n\n"
        msg += "\n".join([f"{size}.txt: {counts[size]} itens" for size in sorted(counts.keys())])

        if ignored and self.include_ignored_var.get():
            msg += f"\n\nIGNORADAS.txt: {len(ignored)} linhas"

        messagebox.showinfo(APP_NAME, msg)



# =========================
# API p/ Hub
# =========================
def build_ui(parent):
    return PXDupeFrame(parent)


# =========================
# Standalone
# =========================
class App(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x650")
        self.minsize(900, 520)

        ui = build_ui(self)
        ui.pack(fill="both", expand=True)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
