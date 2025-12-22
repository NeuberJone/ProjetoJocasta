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

from tkinterdnd2 import TkinterDnD, DND_FILES  # precisa: pip install tkinterdnd2


APP_NAME = "PXSort"
CONFIG_FILE = "pxsort_config.json"

SEP = "\\\\"  # duas barras

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG",
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}


@dataclass(frozen=True)
class Item:
    name: str
    number: str  # pode ser ""


# -----------------------------
# Config (igual padrão PX)
# -----------------------------
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


# -----------------------------
# Parse
# -----------------------------
def _clean_token(s: str) -> str:
    t = s.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    return t


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def _looks_like_number(token: str) -> bool:
    return token.isdigit()  # preserva "01"


def parse_line(line: str) -> Optional[Tuple[str, Item]]:
    raw = line.strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None

    # achar tamanho (qualquer posição)
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

    # número = último token numérico
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


def sort_key(item: Item) -> Tuple[str, str]:
    return (item.name, item.number)


def build_buckets(text: str) -> Tuple[Dict[str, List[Item]], List[str]]:
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

    for size in list(buckets.keys()):
        buckets[size] = sorted(buckets[size], key=sort_key)

    return buckets, ignored


def write_zip(
    buckets: Dict[str, List[Item]],
    zip_path: Path,
    include_ignored: bool,
    ignored: List[str],
) -> Dict[str, int]:
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


# -----------------------------
# App (igual estilo PXList)
# -----------------------------
class App(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title(APP_NAME)
        self.geometry("900x620")
        self.minsize(820, 520)

        self.cfg = load_config()

        default_export = self.cfg.get("export_dir") or str((Path.home() / "Documents" / "PXSort").resolve())
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

        mid = tk.Frame(self)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        tk.Label(mid, text="Cole a lista aqui ou solte um .txt (drag & drop):").pack(anchor="w")
        self.txt = tk.Text(mid, wrap="word", height=18)
        self.txt.pack(fill="both", expand=True, pady=(6, 0))

        # DnD igual ao PXList
        self.txt.drop_target_register(DND_FILES)
        self.txt.dnd_bind("<<Drop>>", self.on_drop)

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Importar TXT...", command=self.import_txt).pack(side="left")
        tk.Button(btns, text="Limpar", command=self.clear).pack(side="left", padx=6)
        tk.Button(btns, text="Gerar ZIP", command=self.export_zip).pack(side="right")

        # Exemplo
        self.txt.insert(
            "1.0",
            "M, João, 10\n"
            "Pedro, G, 01\n"
            "Maria, M\n"
            "2A, Lucas, 5\n"
            "Ana, 4A\n"
        )

    def choose_export_dir(self) -> None:
        folder = filedialog.askdirectory(title="Escolher pasta de exportação")
        if not folder:
            return
        self.export_dir_var.set(folder)
        self.cfg["export_dir"] = folder
        save_config(self.cfg)

    def open_export_dir(self) -> None:
        p = Path(self.export_dir_var.get().strip())
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def persist_options(self) -> None:
        self.cfg["include_ignored"] = bool(self.include_ignored_var.get())
        save_config(self.cfg)

    def clear(self) -> None:
        self.txt.delete("1.0", "end")

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
            filetypes=[("TXT", "*.txt"), ("Todos", "*.*")]
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

        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", content)

    def export_zip(self) -> None:
        raw = self.txt.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Cole ou importe uma lista antes de exportar.")
            return

        export_dir = Path(self.export_dir_var.get().strip())
        export_dir.mkdir(parents=True, exist_ok=True)
        self.cfg["export_dir"] = str(export_dir)
        save_config(self.cfg)

        buckets, ignored = build_buckets(raw)
        if not buckets:
            messagebox.showinfo(APP_NAME, "Nenhum tamanho reconhecido.\nVerifique se contém M, G, 2A, 4A, etc.")
            return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"PXSort_{stamp}.zip"

        zip_fp = filedialog.asksaveasfilename(
            title="Salvar ZIP",
            initialdir=str(export_dir),
            initialfile=default_name,
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
        )
        if not zip_fp:
            return

        counts = write_zip(
            buckets=buckets,
            zip_path=Path(zip_fp),
            include_ignored=self.include_ignored_var.get(),
            ignored=ignored,
        )

        msg = "ZIP gerado com sucesso!\n\n"
        msg += "\n".join([f"{size}.txt: {counts[size]} itens" for size in sorted(counts.keys())])
        if ignored and self.include_ignored_var.get():
            msg += f"\n\nIGNORADAS.txt: {len(ignored)} linhas"

        messagebox.showinfo(APP_NAME, msg)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
