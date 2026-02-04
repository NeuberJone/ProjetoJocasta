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
# PXFlow - Config
# =========================
APP_NAME = "PXFlow"
DEFAULT_OUTPUT_DIR = r"C:\Listas"

BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": ""
}

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG"
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG"
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

# "QTY-SIZE" (ex: 3-G, 5-12A, 2-BLP)
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")


# =========================
# Config persistente (AppData)
# =========================
def get_config_file() -> str:
    base = os.environ.get("APPDATA") or str(Path.home())
    cfg_dir = Path(base) / "PXList"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "pxflow_config.json")


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


def normalize_size_token(tok: str) -> str:
    qty, size = parse_qty_and_size(tok)
    return f"{qty}-{size}"


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


def detect_multi_piece_input(text: str) -> bool:
    """
    PXFlow aceita APENAS 1 tamanho por linha.
    Se achar 2+ tokens de tamanho na mesma linha, considera multi-peça
    e sugere ir pro PXComposer.
    """
    for line in (text or "").splitlines():
        raw = line.strip().replace("\ufeff", "")
        if not raw or raw.startswith("//"):
            continue

        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 1:
            # "GG" sozinho = ok
            continue

        # a partir do campo 3 (index 2) podem existir tamanhos
        size_count = 0
        for tok in parts[2:]:
            if is_size_token(tok):
                size_count += 1
                if size_count >= 2:
                    return True
    return False


# =========================
# Parser (1 peça por linha)
# =========================
@dataclass(frozen=True)
class Row:
    name: str
    number: str
    size_token: str  # sempre normalizado "QTY-SIZE"
    nickname: str
    blood: str


def parse_line_single_piece(line: str, line_no: int) -> Optional[Row]:
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return None
    if raw.strip().startswith("//"):
        return None

    parts = [p.strip() for p in raw.split(",")]
    for tok in parts:
        forbid_quotes(line_no, tok)

    # Caso especial: só um token (ex: "GG")
    if len(parts) == 1:
        only = parts[0].strip()
        if only and is_size_token(only):
            st = normalize_size_token(only)
            return Row(name="", number="", size_token=st, nickname="", blood="")
        raise ValueError(f"Linha {line_no}: tamanho obrigatório. Valor recebido: {only!r}")

    while len(parts) < 3:
        parts.append("")

    name = normalize_name(parts[0])
    number = normalize_text(parts[1])  # mantém como veio (7X1 etc.)
    size_raw = parts[2].strip()

    if not size_raw:
        raise ValueError(f"Linha {line_no}: tamanho vazio (não permitido).")

    # valida multi peça (se existir tamanho em outro campo)
    size_count = 0
    for tok in parts[2:]:
        if is_size_token(tok):
            size_count += 1
    if size_count >= 2:
        raise ValueError(f"Linha {line_no}: foram encontrados {size_count} tamanhos. PXFlow aceita apenas 1.")

    if not is_size_token(size_raw):
        raise ValueError(f"Linha {line_no}: tamanho inválido: {size_raw!r}")

    size_token = normalize_size_token(size_raw)

    nickname = parts[3].strip() if len(parts) > 3 else ""
    blood = parts[4].strip() if len(parts) > 4 else ""
    if len(parts) > 5:
        # permite vírgulas a mais só se forem vazias no fim
        if any(p.strip() for p in parts[5:]):
            raise ValueError(f"Linha {line_no}: campos demais após Tipo Sanguíneo.")

    nickname = normalize_name(nickname) if nickname else ""
    blood = normalize_name(blood) if blood else ""

    # valida gender (inclui divergência BL + A)
    _qty, size = parse_qty_and_size(size_token)
    _ = gender_from_size(size)

    return Row(name=name, number=number, size_token=size_token, nickname=nickname, blood=blood)


def process_text_single_piece(text: str) -> List[Row]:
    rows: List[Row] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        if line.strip().startswith("//"):
            continue
        r = parse_line_single_piece(line, i)
        if r:
            rows.append(r)

    rows.sort(key=lambda r: (r.name, r.number))
    return rows


def rows_to_organized_csv(rows: List[Row]) -> str:
    has_nick = any(r.nickname for r in rows)
    has_blood = any(r.blood for r in rows)
    if has_blood:
        has_nick = True  # se existir TS, mantém coluna apelido

    out_lines: List[str] = []
    for r in rows:
        cols = [r.name, r.number, display_size_token(r.size_token)]
        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)
        out_lines.append(",".join(cols))
    return "\n".join(out_lines)


def build_orders(rows: List[Row]) -> List[dict]:
    orders: List[dict] = []
    for r in rows:
        qty, size = parse_qty_and_size(r.size_token)
        gender = gender_from_size(size)

        orders.append({
            "Name": r.name,
            "Nickname": r.nickname,
            "Number": r.number,
            "BloodType": r.blood,
            "Gender": gender,
            "ShortSleeve": f"{qty}-{size}",  # sempre normalizado no JSON
            "LongSleeve": "",
            "Short": "",
            "Pants": "",
            "Tanktop": "",
            "Vest": ""
        })
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
# Hub redirect -> PXComposer
# =========================
def open_composer_with_input(parent: tk.Misc, raw_text: str) -> None:
    root = parent.winfo_toplevel()

    # 1) Tenta usar a aba do Hub
    nb = getattr(root, "nb", None)
    if isinstance(nb, ttk.Notebook):
        target_tab_id = None
        for tab_id in nb.tabs():
            try:
                if nb.tab(tab_id, "text") == "PXComposer":
                    target_tab_id = tab_id
                    break
            except Exception:
                continue

        if target_tab_id:
            nb.select(target_tab_id)
            tab_widget = root.nametowidget(target_tab_id)

            def walk(w: tk.Widget):
                yield w
                for c in w.winfo_children():
                    yield from walk(c)

            for w in walk(tab_widget):
                if hasattr(w, "txt_in"):
                    try:
                        txt = getattr(w, "txt_in")
                        if isinstance(txt, tk.Text):
                            txt.delete("1.0", "end")
                            txt.insert("1.0", raw_text)
                            txt.focus_set()
                            return
                    except Exception:
                        pass

            messagebox.showwarning(
                APP_NAME,
                "Mudei para a aba PXComposer, mas não consegui preencher a entrada automaticamente."
            )
            return

    # 2) Fallback: abre janela do Composer (fora do Hub)
    try:
        import PXComposer  # type: ignore
    except Exception as e:
        messagebox.showerror(
            APP_NAME,
            "Não consegui abrir o PXComposer.\n"
            "Verifique se o arquivo 'PXComposer.py' está na mesma pasta.\n\n"
            f"Detalhe: {e}"
        )
        return

    win = tk.Toplevel(root)
    win.title("PXComposer")

    if hasattr(PXComposer, "build_ui"):
        frame = PXComposer.build_ui(win)
        frame.pack(fill="both", expand=True)

        if hasattr(frame, "txt_in"):
            try:
                frame.txt_in.delete("1.0", "end")
                frame.txt_in.insert("1.0", raw_text)
                frame.txt_in.focus_set()
            except Exception:
                pass
    else:
        tk.Label(win, text="PXComposer carregado, mas não encontrei build_ui(parent).").pack(padx=10, pady=10)


# =========================
# UI
# =========================
class PXFlowFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        cfg = load_config()
        self.output_dir_var = tk.StringVar(value=cfg.get("output_dir", DEFAULT_OUTPUT_DIR))

        self._rows: List[Row] = []
        self._last_orders: List[dict] = []
        self._last_json: str = ""

        # Header
        header = tk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(header, text="PXFlow", font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Button(header, text="Info", command=self.toggle_info).pack(side="right")

        # Info (hidden)
        self.info_frame = tk.LabelFrame(self, text="Informações / Regras")
        self.info_visible = False
        info_txt = (
            "• PXFlow = (Lite + List) em um módulo.\n"
            "• Aceita 1 peça por linha e gera JSON preenchendo ShortSleeve.\n"
            "• Se detectar multi-peça (2+ tamanhos na mesma linha), encaminha para PXComposer.\n"
            "• Comentários: linhas começando com // são ignoradas.\n"
            "• Gender: Infantil (*A) = C | BL = FE | senão = MA | BL + A = erro.\n"
        )
        tk.Label(self.info_frame, text=info_txt, justify="left", font=("Segoe UI", 9)).pack(
            anchor="w", padx=10, pady=8
        )

        # Output dir row
        out_row = tk.Frame(self)
        out_row.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(out_row, text="Pasta...", command=self.pick_output_folder).pack(side="left")
        self.lbl_out = tk.Label(out_row, text=f"Pasta de saída: {self.output_dir_var.get()}", font=("Segoe UI", 9))
        self.lbl_out.pack(side="right")

        # Body
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada: Nome, Número, Tamanho, (Apelido), (Tipo)").pack(anchor="w")
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

        # Comentários azuis
        self.txt_in.tag_configure("comment", foreground="#1f6fd2")
        self.txt_in.bind("<KeyRelease>", lambda e: highlight_comments(self.txt_in))
        self.txt_in.bind("<Control-v>", lambda e: self.after(1, highlight_comments, self.txt_in))

        # Drag & Drop .txt
        self.txt_in.drop_target_register(DND_FILES)
        self.txt_in.dnd_bind("<<Drop>>", self.on_drop_file)

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
            "// 1 peça por linha (PXFlow)\n"
            "GG\n"
            "JOÃO,5,G\n"
            "JUACA,,PP,JUSÉ\n"
            "LUCAS,21,M,,O-\n"
            "\n"
            "// Se colar multi-peça (ex: JOAO,5,G,M) o PXFlow vai sugerir abrir o PXComposer.\n"
        )
        highlight_comments(self.txt_in)

    def _set_text_readonly(self, txt: tk.Text, readonly: bool) -> None:
        txt.configure(state=("disabled" if readonly else "normal"))

    def toggle_info(self):
        if self.info_visible:
            self.info_frame.pack_forget()
            self.info_visible = False
        else:
            self.info_frame.pack(fill="x", padx=10, pady=(0, 8))
            self.info_visible = True

    def pick_output_folder(self):
        folder = filedialog.askdirectory(title="PXFlow - Escolha a pasta para salvar o JSON")
        if folder:
            self.output_dir_var.set(folder)
            cfg = load_config()
            cfg["output_dir"] = folder
            save_config(cfg)
            self.lbl_out.config(text=f"Pasta de saída: {folder}")
            self.status_var.set(f"📁 Pasta de saída: {folder}")

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
            self.status_var.set(f"📄 TXT carregado: {p.name}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")
        self._set_text_readonly(self.txt_json, False)
        self.txt_json.delete("1.0", "end")
        self._set_text_readonly(self.txt_json, True)
        self._rows = []
        self._last_orders = []
        self._last_json = ""
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
        self.status_var.set("📋 Lista organizada copiada.")

    def copy_json(self):
        if not self._last_json.strip():
            messagebox.showwarning(APP_NAME, "Ainda não há prévia do JSON. Clique em Processar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(self._last_json)
        root.update()
        self.status_var.set("📋 JSON copiado.")

    def process_and_preview(self):
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        # ✅ Se detectar multi-peça, encaminha para PXComposer
        if detect_multi_piece_input(raw):
            resp = messagebox.askyesno(
                APP_NAME,
                "Detectei mais de uma peça/tamanho em pelo menos uma linha.\n\n"
                "O PXFlow trabalha com APENAS 1 peça por linha.\n"
                "Deseja abrir o PXComposer com essa mesma entrada?"
            )
            if resp:
                open_composer_with_input(self.winfo_toplevel(), raw)
            return

        try:
            rows = process_text_single_piece(raw)
            if not rows:
                messagebox.showwarning(APP_NAME, "Nenhuma linha válida encontrada.")
                return

            organized = rows_to_organized_csv(rows)
            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", organized)

            # ✅ copia lista organizada sempre
            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(organized)
            root.update()

            orders = build_orders(rows)
            preview = build_json_preview(orders)

            self._rows = rows
            self._last_orders = orders
            self._last_json = preview

            self._set_text_readonly(self.txt_json, False)
            self.txt_json.delete("1.0", "end")
            self.txt_json.insert("1.0", preview)
            self._set_text_readonly(self.txt_json, True)

            self.status_var.set(f"✅ Processado: {len(rows)} registro(s) | lista copiada | prévia JSON pronta.")
            self.nb.select(0)

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def generate_json(self):
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
    return PXFlowFrame(parent)


def main() -> None:
    app = TkinterDnD.Tk()
    app.title(APP_NAME)
    app.geometry("1200x720")
    app.minsize(1000, 620)

    ui = build_ui(app)
    ui.pack(fill="both", expand=True)

    app.mainloop()


if __name__ == "__main__":
    main()
