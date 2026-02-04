from __future__ import annotations

import json
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

from tkinterdnd2 import DND_FILES, TkinterDnD

# =========================
# PXComposer - Config
# =========================
APP_NAME = "PXComposer"
DEFAULT_OUTPUT_DIR = r"C:\Listas"

BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": "",
}

# Campos do JSON (peças)
PIECE_FIELDS = [
    ("Manga curta", "ShortSleeve"),
    ("Manga longa", "LongSleeve"),
    ("Short", "Short"),
    ("Calça", "Pants"),
    ("Regata", "Tanktop"),
    ("Colete", "Vest"),
]

# Tamanhos válidos (Adulto, Babylook, Infantil)
VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG"
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG"
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

# Tamanho com quantidade (QTY-TAM)
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")

# =========================
# Config persistente (AppData)
# =========================
def get_config_file() -> str:
    base = os.environ.get("APPDATA") or str(Path.home())
    cfg_dir = Path(base) / "PXList"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "pxcomposer_config.json")


def load_config() -> dict:
    fp = get_config_file()
    if not os.path.exists(fp):
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    fp = get_config_file()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# =========================
# Helpers
# =========================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def normalize_name(s: str) -> str:
    return normalize_text(s).upper()


def forbid_quotes(line_no: int, tok: str) -> None:
    if tok and FORBIDDEN_QUOTE_RE.search(tok):
        raise ValueError(f"Linha {line_no}: não use aspas para vazio (\"\"), token: {tok!r}")


def highlight_comments(text_widget: tk.Text) -> None:
    text_widget.tag_remove("comment", "1.0", "end")
    lines = text_widget.get("1.0", "end").splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("//"):
            text_widget.tag_add("comment", f"{idx}.0", f"{idx}.end")


def extract_paths_from_drop(data: str) -> list[str]:
    files = re.findall(r"\{([^}]*)\}|(\S+)", (data or "").strip())
    paths = []
    for a, b in files:
        paths.append(a or b)
    return paths


def is_size_token(tok: str) -> bool:
    t = (tok or "").strip()
    if not t:
        return False
    t = t.upper()
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    if m:
        size = m.group(2).strip().upper()
        return size in VALID_SIZES
    return False


def parse_qty_and_size(tok: str) -> Tuple[int, str]:
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


def normalize_size_token(tok: str) -> str:
    qty, size = parse_qty_and_size(tok)
    return f"{qty}-{size}"


def display_size_token(size_token: str) -> str:
    st = (size_token or "").strip()
    if not st:
        return ""
    m = QTY_SIZE_RE.match(st)
    if m:
        qty = int(m.group(1))
        size = m.group(2).strip().upper()
        if qty == 1:
            return size
        return f"{qty}-{size}"
    return st.upper()


def gender_from_size(size: str) -> str:
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


def gender_of_size_token(size_token: str) -> str:
    _, size = parse_qty_and_size(size_token)
    return gender_from_size(size)


# =========================
# Totalist phase (organizar)
# =========================
@dataclass(frozen=True)
class Row:
    name: str
    number: str
    pieces: List[str]   # ✅ agora é "slots" (preserva colunas)
    nickname: str
    blood: str


def parse_line_free(line: str, line_no: int) -> Optional[Tuple[str, str, List[str], List[str]]]:
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return None
    if raw.strip().startswith("//"):
        return None

    # split preserva vazios entre vírgulas
    parts = [p.strip() for p in raw.split(",")]
    for tok in parts:
        forbid_quotes(line_no, tok)

    while len(parts) < 2:
        parts.append("")

    name = normalize_name(parts[0])
    number = normalize_text(parts[1])
    tail = parts[2:] if len(parts) >= 3 else []

    # ✅ PRESERVAR SLOTS ATÉ COMEÇAR EXTRAS
    pieces_slots: List[str] = []
    extras: List[str] = []

    extras_started = False
    for tok in tail:
        t = tok.strip()

        if extras_started:
            if t:
                extras.append(normalize_name(t))
            continue

        # ainda estamos na parte das peças
        if not t:
            pieces_slots.append("")
            continue

        if is_size_token(t):
            pieces_slots.append(normalize_size_token(t))
            continue

        # primeiro token não-size => aqui começam extras (apelido / tipo)
        extras_started = True
        extras.append(normalize_name(t))

    # se não encontrou nenhuma peça em nenhum slot
    if not any(pieces_slots):
        # caso especial: se tiver só 1 token e ele for tamanho
        if len(parts) == 1 and is_size_token(parts[0].strip()):
            return ("", "", [normalize_size_token(parts[0].strip())], [])
        raise ValueError(f"Linha {line_no}: não encontrei nenhum tamanho válido (peça).")

    if len(extras) > 2:
        raise ValueError(
            f"Linha {line_no}: extras demais (máx 2: apelido e tipo).\nRecebido: {extras}"
        )

    return (name, number, pieces_slots, extras)


def split_row_by_gender_preserve_slots(row: Row) -> List[Row]:
    """
    Se houver mistura de gêneros nos slots, devolve várias linhas,
    mantendo a MESMA quantidade de colunas e preservando a coluna original.
    """
    # pega gêneros na ordem em que aparecem
    order: List[str] = []
    for st in row.pieces:
        if not st:
            continue
        g = gender_of_size_token(st)
        if g not in order:
            order.append(g)

    if len(order) <= 1:
        return [row]

    out: List[Row] = []
    for g in order:
        new_slots = []
        for st in row.pieces:
            if not st:
                new_slots.append("")
                continue
            if gender_of_size_token(st) == g:
                new_slots.append(st)
            else:
                new_slots.append("")
        out.append(Row(
            name=row.name,
            number=row.number,
            pieces=new_slots,
            nickname=row.nickname,
            blood=row.blood
        ))
    return out


def organize_text(text: str) -> List[Row]:
    rows: List[Row] = []

    for i, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        if line.strip().startswith("//"):
            continue

        parsed = parse_line_free(line, i)
        if not parsed:
            continue

        name, number, pieces_slots, extras = parsed
        nickname = extras[0] if len(extras) >= 1 else ""
        blood = extras[1] if len(extras) >= 2 else ""

        base = Row(name=name, number=number, pieces=pieces_slots, nickname=nickname, blood=blood)

        # ✅ separa por gênero sem perder slots
        rows.extend(split_row_by_gender_preserve_slots(base))

    rows.sort(key=lambda r: (r.name, r.number))
    return rows


def rows_to_organized_csv(rows: List[Row]) -> Tuple[str, int, bool, bool]:
    if not rows:
        return ("", 0, False, False)

    max_pieces = min(max(len(r.pieces) for r in rows), 6)
    has_nick = any(r.nickname for r in rows)
    has_blood = any(r.blood for r in rows)
    if has_blood:
        has_nick = True

    out_lines: List[str] = []
    for r in rows:
        cols = [r.name, r.number]

        for idx in range(max_pieces):
            st = r.pieces[idx] if idx < len(r.pieces) else ""
            cols.append(display_size_token(st) if st else "")

        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)

        out_lines.append(",".join(cols))

    return ("\n".join(out_lines), max_pieces, has_nick, has_blood)


# =========================
# ListPlus phase (mapear + JSON)
# =========================
def validate_gender_consistency(row: Row) -> str:
    genders: List[str] = []
    for st in row.pieces:
        if not st:
            continue
        genders.append(gender_of_size_token(st))

    if not genders:
        raise ValueError("Linha sem tamanhos (peças) após organizar.")

    if len(set(genders)) != 1:
        raise ValueError(f"Gêneros diferentes na mesma linha: {sorted(set(genders))}")

    return genders[0]


def build_orders_from_rows(
    rows: List[Row],
    max_pieces: int,
    selected_piece_fields_in_order: List[str],
) -> List[dict]:
    if max_pieces <= 0:
        raise ValueError("Não foi possível detectar a quantidade de peças.")

    if len(selected_piece_fields_in_order) != max_pieces:
        raise ValueError(
            f"Mapeamento inválido: peças detectadas = {max_pieces}, "
            f"selecionadas = {len(selected_piece_fields_in_order)}."
        )

    orders: List[dict] = []

    for r in rows:
        gender = validate_gender_consistency(r)

        item = {
            "Name": r.name,
            "Nickname": r.nickname,
            "Number": r.number,
            "BloodType": r.blood,
            "Gender": gender,
            "ShortSleeve": "",
            "LongSleeve": "",
            "Short": "",
            "Pants": "",
            "Tanktop": "",
            "Vest": "",
        }

        for idx in range(max_pieces):
            field = selected_piece_fields_in_order[idx]
            size_token = r.pieces[idx] if idx < len(r.pieces) else ""
            item[field] = size_token if size_token else ""

        orders.append(item)

    return orders


def build_json_preview(orders: List[dict]) -> str:
    data = dict(BASE_JSON)
    data["orders"] = orders
    return json.dumps(data, ensure_ascii=False, indent=4)


def export_json(orders: List[dict], out_dir: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = os.path.join(out_dir, f"List-{stamp}.json")
    data = dict(BASE_JSON)
    data["orders"] = orders
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return fp


# =========================
# UI
# =========================
class PXComposerFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        cfg = load_config()
        self.output_dir_var = tk.StringVar(value=cfg.get("output_dir", DEFAULT_OUTPUT_DIR))

        self._rows: List[Row] = []
        self._max_pieces: int = 0
        self._last_orders: List[dict] = []
        self._last_json_preview: str = ""
        self._selected_order: List[str] = []
        self._checkbox_vars: dict[str, tk.IntVar] = {}

        # ✅ snapshot para não apagar seleção ao verificar quando entrada não mudou
        self._last_input_snapshot = ""

        # Header
        header = tk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 6))
        tk.Label(header, text="PXComposer", font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Button(header, text="Info", command=self.toggle_info).pack(side="right")

        # Info panel (hidden)
        self.info_frame = tk.LabelFrame(self, text="Informações / Regras")
        self.info_visible = False
        info_txt = (
            "• Cole a lista ou solte um .txt.\n"
            "• Comentários: linhas começando com // são ignoradas (em azul).\n"
            "• Organizar: cria colunas dinâmicas até a maior linha (t1..tN).\n"
            "• Mapear: selecione exatamente N peças (na ordem marcada) para aplicar em t1..tN.\n"
            "• Se misturar gêneros (MA/FE/C) na mesma linha, o Composer separa em linhas diferentes.\n"
            "• Agora o Composer preserva a coluna original quando separa por gênero.\n"
            "• Prévia JSON é idêntica ao arquivo que será salvo."
        )
        tk.Label(self.info_frame, text=info_txt, justify="left", font=("Segoe UI", 9)).pack(
            anchor="w", padx=10, pady=8
        )

        # Output dir
        out_row = tk.Frame(self)
        out_row.pack(fill="x", padx=10, pady=(0, 8))
        tk.Button(out_row, text="Pasta...", command=self.pick_output_folder).pack(side="left")
        self.lbl_out = tk.Label(
            out_row, text=f"Pasta de saída: {self.output_dir_var.get()}", font=("Segoe UI", 9)
        )
        self.lbl_out.pack(side="right")

        # Main body
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada (livre):").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none", height=18, font=("Consolas", 10))
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        # Right: Notebook
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        tab_list = tk.Frame(self.nb)
        tab_json = tk.Frame(self.nb)
        self.nb.add(tab_list, text="Lista organizada")
        self.nb.add(tab_json, text="Prévia JSON")

        tk.Label(tab_list, text="Saída organizada (Totalist):").pack(anchor="w")
        self.txt_out = tk.Text(tab_list, wrap="none", height=18, font=("Consolas", 10))
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(tab_json, text="Prévia do JSON:").pack(anchor="w")
        self.txt_json = tk.Text(tab_json, wrap="none", height=18, font=("Consolas", 10))
        self.txt_json.pack(fill="both", expand=True, pady=(6, 0))
        self._set_text_readonly(self.txt_json, True)

        # Comentários azuis
        self.txt_in.tag_configure("comment", foreground="#1f6fd2")
        self.txt_in.bind("<KeyRelease>", lambda e: highlight_comments(self.txt_in))
        self.txt_in.bind("<ButtonRelease>", lambda e: self.after(1, highlight_comments, self.txt_in))

        # Drag & Drop
        self.txt_in.drop_target_register(DND_FILES)
        self.txt_in.dnd_bind("<<Drop>>", self.on_drop_file)

        # Mapping UI
        map_frame = tk.LabelFrame(self, text="Mapeamento de peças")
        map_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.lbl_detect = tk.Label(
            map_frame,
            text="Peças detectadas: 0 | Selecione na ordem (t1 → 1ª marcada, t2 → 2ª marcada...)",
            font=("Segoe UI", 9),
        )
        self.lbl_detect.pack(anchor="w", padx=10, pady=(6, 0))

        checks = tk.Frame(map_frame)
        checks.pack(fill="x", padx=10, pady=8)

        for label, key in PIECE_FIELDS:
            var = tk.IntVar(value=0)
            self._checkbox_vars[key] = var
            cb = tk.Checkbutton(checks, text=label, variable=var, command=lambda k=key: self.on_toggle_piece(k))
            cb.pack(side="left", padx=(0, 10))

        self.disable_mapping()

        # Buttons
        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="left")
        tk.Button(btns, text="Copiar lista", command=self.copy_list).pack(side="left", padx=6)
        tk.Button(btns, text="Copiar JSON", command=self.copy_json).pack(side="left", padx=6)
        tk.Button(btns, text="Gerar JSON", command=self.generate_json).pack(side="right")
        tk.Button(btns, text="Verificar/Mapear", command=self.verify_and_preview).pack(side="right", padx=6)
        tk.Button(btns, text="Organizar", command=lambda: self.organize(copy_to_clipboard=True, preserve_selection=False)).pack(
            side="right", padx=6
        )

        # Status
        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 10))

        # Exemplo
        self.txt_in.insert(
            "1.0",
            "// Exemplo: mistura de gêneros na mesma linha será separada em linhas\n"
            "GPT,10,G\n"
            "JOÃO,5,G,M\n"
            "JUACA,,PP,2A,BLM,JUSÉ\n"
            "MANEL,,PP,GG,,O-\n"
            "\n"
            "// Dica: marque as peças na ordem e clique Verificar/Mapear\n"
        )
        highlight_comments(self.txt_in)

    # ---------------- UI utilities
    def _set_text_readonly(self, txt: tk.Text, readonly: bool) -> None:
        txt.configure(state=("disabled" if readonly else "normal"))

    def _set_json_preview(self, content: str) -> None:
        self._last_json_preview = content
        self._set_text_readonly(self.txt_json, False)
        self.txt_json.delete("1.0", "end")
        self.txt_json.insert("1.0", content)
        self._set_text_readonly(self.txt_json, True)

    def toggle_info(self):
        if self.info_visible:
            self.info_frame.pack_forget()
            self.info_visible = False
        else:
            self.info_frame.pack(fill="x", padx=10, pady=(0, 8))
            self.info_visible = True

    def pick_output_folder(self):
        folder = filedialog.askdirectory(title="PXComposer - Escolha a pasta para salvar o JSON")
        if folder:
            self.output_dir_var.set(folder)
            cfg = load_config()
            cfg["output_dir"] = folder
            save_config(cfg)
            self.lbl_out.config(text=f"Pasta de saída: {folder}")
            self.status_var.set(f" Pasta de saída: {folder}")

    def ensure_output_dir(self) -> str:
        out = self.output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR
        ensure_dir(out)
        return out

    def on_drop_file(self, event):
        try:
            paths = extract_paths_from_drop(event.data)
            if not paths:
                return
            p = Path(paths[0].strip().strip('"'))
            if not p.exists():
                raise FileNotFoundError("Arquivo não encontrado.")
            if p.suffix.lower() != ".txt":
                raise ValueError("Solte um arquivo .txt.")
            content = p.read_text(encoding="utf-8", errors="replace")
            self.txt_in.delete("1.0", "end")
            self.txt_in.insert("1.0", content)
            highlight_comments(self.txt_in)
            self.status_var.set(f" TXT carregado: {p.name}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    # ---------------- Mapping behavior
    def disable_mapping(self):
        self._max_pieces = 0
        self._selected_order = []
        for v in self._checkbox_vars.values():
            v.set(0)
        self.lbl_detect.config(
            text="Peças detectadas: 0 | Selecione na ordem (t1 → 1ª marcada, t2 → 2ª marcada...)"
        )

    def enable_mapping(self, max_pieces: int):
        self._max_pieces = max_pieces
        self._selected_order = []
        for v in self._checkbox_vars.values():
            v.set(0)
        self.lbl_detect.config(
            text=f"Peças detectadas: {max_pieces} | Selecione na ordem (t1 → 1ª marcada, t2 → 2ª marcada...)"
        )

    def on_toggle_piece(self, key: str):
        if self._max_pieces <= 0:
            self._checkbox_vars[key].set(0)
            messagebox.showwarning(APP_NAME, "Primeiro clique em Verificar/Mapear (ele organiza automaticamente).")
            return

        is_checked = self._checkbox_vars[key].get() == 1
        if is_checked:
            if key in self._selected_order:
                return
            if len(self._selected_order) >= self._max_pieces:
                self._checkbox_vars[key].set(0)
                messagebox.showwarning(
                    APP_NAME,
                    "Todas as peças já foram selecionadas.\n" f"Peças detectadas: {self._max_pieces}.",
                )
                return
            self._selected_order.append(key)
        else:
            if key in self._selected_order:
                self._selected_order.remove(key)

    # ---------------- Actions
    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")
        self._set_json_preview("")
        self._rows = []
        self._last_orders = []
        self.disable_mapping()
        self._last_input_snapshot = ""
        self.status_var.set("")
        highlight_comments(self.txt_in)

    def copy_list(self):
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há lista organizada para copiar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        self.status_var.set(" Lista organizada copiada.")

    def copy_json(self):
        if not self._last_json_preview.strip():
            messagebox.showwarning(APP_NAME, "Ainda não há prévia do JSON.\nClique em Verificar/Mapear.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(self._last_json_preview)
        root.update()
        self.status_var.set(" JSON copiado.")

    def organize(self, copy_to_clipboard: bool = True, preserve_selection: bool = True) -> bool:
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return False

        # Se não mudou e já temos lista organizada, só copia e não reseta seleção
        if preserve_selection and self._rows and raw == self._last_input_snapshot:
            organized_csv = self.txt_out.get("1.0", "end").strip()
            if copy_to_clipboard and organized_csv:
                root = self.winfo_toplevel()
                root.clipboard_clear()
                root.clipboard_append(organized_csv)
                root.update()
                self.status_var.set(" Lista organizada copiada (entrada não mudou).")
            return True

        try:
            rows = organize_text(raw)
            if not rows:
                messagebox.showwarning(APP_NAME, "Nenhuma linha válida encontrada.")
                return False

            organized_csv, max_pieces, has_nick, has_blood = rows_to_organized_csv(rows)

            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", organized_csv)

            self._set_json_preview("")
            self._last_orders = []
            self._rows = rows
            self._last_input_snapshot = raw

            # entrada mudou -> reseta seleção
            self.enable_mapping(max_pieces)

            if copy_to_clipboard:
                root = self.winfo_toplevel()
                root.clipboard_clear()
                root.clipboard_append(organized_csv)
                root.update()
                self.status_var.set(
                    f"✅ Organizado: {len(rows)} linha(s) | peças detectadas: {max_pieces} | "
                    f"apelido: {'sim' if has_nick else 'não'} | TS: {'sim' if has_blood else 'não'} | lista copiada"
                )
            self.nb.select(0)
            return True

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")
            return False

    def verify_and_preview(self):
        ok = self.organize(copy_to_clipboard=True, preserve_selection=True)
        if not ok:
            return

        if self._max_pieces <= 0:
            messagebox.showwarning(APP_NAME, "Não foi possível detectar a quantidade de peças.")
            return

        if len(self._selected_order) == 0:
            messagebox.showerror(APP_NAME, "Marque as peças na ordem antes de verificar.")
            return

        if len(self._selected_order) != self._max_pieces:
            messagebox.showerror(
                APP_NAME,
                f"Você deve marcar exatamente {self._max_pieces} peça(s).\n"
                f"Marcadas: {len(self._selected_order)}.",
            )
            return

        try:
            orders = build_orders_from_rows(
                rows=self._rows,
                max_pieces=self._max_pieces,
                selected_piece_fields_in_order=self._selected_order,
            )
            preview = build_json_preview(orders)
            self._last_orders = orders
            self._set_json_preview(preview)
            self.status_var.set(f"✅ Verificado: {len(orders)} registro(s) | lista copiada | prévia JSON pronta.")
            self.nb.select(1)
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def generate_json(self):
        if not self._last_orders:
            self.verify_and_preview()
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
    return PXComposerFrame(parent)


def main() -> None:
    app = TkinterDnD.Tk()
    app.title(APP_NAME)
    app.geometry("1200x780")
    app.minsize(1000, 650)
    ui = build_ui(app)
    ui.pack(fill="both", expand=True)
    app.mainloop()


if __name__ == "__main__":
    main()
