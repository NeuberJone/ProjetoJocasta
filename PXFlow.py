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

# Tamanhos válidos (mesma base do Lite)
VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    # Infantil
    "2A", "3A", "4A", "5A", "6A", "7A", "8A", "9A",
    "10A", "11A", "12A", "14A", "16A",
}

# QTY-TAM opcional (ex: 3-G). No Flow, se vier só TAM -> vira 1-TAM
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
      - QTY-TAM (3-G, 2-BLP, 5-12A)
      - TAM sozinho (G, BLP, 12A) -> qty=1
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


# =========================
# Detect multi-peça (para redirecionar pro PXListPlus)
# =========================
def detect_multi_piece_input(text: str) -> bool:
    """
    Se em alguma linha existirem 2 ou mais tokens que parecem tamanho
    a partir do 3º campo (ou seja, mais de 1 peça), consideramos multi-peça.
    """
    for line in (text or "").splitlines():
        raw = line.strip().replace("\ufeff", "")
        if not raw or raw.startswith("//"):
            continue

        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 1:
            continue  # "GG" sozinho => 1 peça

        size_count = 0
        for tok in parts[2:]:
            if is_size_token(tok):
                size_count += 1
                if size_count >= 2:
                    return True

    return False


def open_listplus_with_input(parent: tk.Misc, raw_text: str) -> None:
    """
    Dentro do JocastaHub: muda para a aba PXListPlus e preenche a entrada.
    Fora do Hub: abre uma janela separada do PXListPlus.
    """
    root = parent.winfo_toplevel()

    nb = getattr(root, "nb", None)
    if isinstance(nb, ttk.Notebook):
        target_tab_id = None
        for tab_id in nb.tabs():
            try:
                if nb.tab(tab_id, "text") == "PXListPlus":
                    target_tab_id = tab_id
                    break
            except Exception:
                continue

        if target_tab_id:
            nb.select(target_tab_id)
            tab_widget = root.nametowidget(target_tab_id)

            def _walk(w: tk.Widget):
                yield w
                for c in w.winfo_children():
                    yield from _walk(c)

            for w in _walk(tab_widget):
                if hasattr(w, "txt_in"):
                    txt = getattr(w, "txt_in", None)
                    if isinstance(txt, tk.Text):
                        txt.delete("1.0", "end")
                        txt.insert("1.0", raw_text)
                        txt.focus_set()
                        return

            messagebox.showwarning(
                APP_NAME,
                "Mudei para a aba PXListPlus, mas não consegui preencher a entrada automaticamente."
            )
            return

    try:
        import PXListPlus  # type: ignore
    except Exception as e:
        messagebox.showerror(
            APP_NAME,
            "Não consegui abrir o PXListPlus.\n"
            "Verifique se o arquivo 'PXListPlus.py' está na mesma pasta.\n\n"
            f"Detalhe: {e}"
        )
        return

    win = tk.Toplevel(root)
    win.title("PXListPlus")

    if hasattr(PXListPlus, "build_ui"):
        frame = PXListPlus.build_ui(win)
        frame.pack(fill="both", expand=True)

        if hasattr(frame, "txt_in"):
            txt = getattr(frame, "txt_in", None)
            if isinstance(txt, tk.Text):
                txt.delete("1.0", "end")
                txt.insert("1.0", raw_text)
                txt.focus_set()
    else:
        tk.Label(win, text="PXListPlus carregado, mas não encontrei build_ui(parent).").pack(padx=10, pady=10)


# =========================
# Parsing (modo Lite: 1 tamanho por linha)
# =========================
@dataclass(frozen=True)
class Row:
    name: str
    number: str
    size_token: str     # pode ser "G" ou "3-G"
    nickname: str
    blood: str


def parse_line_single_size(line: str, line_no: int) -> Optional[Row]:
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return None
    if raw.strip().startswith("//"):
        return None

    parts = [p.strip() for p in raw.split(",")]
    for tok in parts:
        forbid_quotes(line_no, tok)

    # Caso: só um token -> tamanho
    if len(parts) == 1:
        only = parts[0].strip()
        if only and is_size_token(only):
            qty, size = parse_qty_and_size(only)
            size_tok = f"{qty}-{size}" if qty != 1 else size
            return Row(name="", number="", size_token=size_tok, nickname="", blood="")
        raise ValueError(f"Linha {line_no}: tamanho obrigatório. Valor recebido: {only!r}")

    while len(parts) < 3:
        parts.append("")

    name = normalize_name(parts[0])
    number = normalize_text(parts[1])

    size_raw = parts[2].strip()
    if not size_raw:
        raise ValueError(f"Linha {line_no}: tamanho vazio (não permitido).")
    if not is_size_token(size_raw):
        raise ValueError(f"Linha {line_no}: tamanho inválido: {size_raw!r}")

    qty, size = parse_qty_and_size(size_raw)
    size_tok = f"{qty}-{size}" if qty != 1 else size

    extras = [p.strip() for p in parts[3:]]
    if len(extras) > 2 and any(x for x in extras[2:]):
        raise ValueError(f"Linha {line_no}: extras demais após o tamanho (máx 2: apelido e tipo).")

    nickname = normalize_name(extras[0]) if len(extras) >= 1 and extras[0] else ""
    blood = normalize_text(extras[1]) if len(extras) >= 2 and extras[1] else ""

    return Row(name=name, number=number, size_token=size_tok, nickname=nickname, blood=blood)


def process_text_single_size(text: str) -> List[Row]:
    rows: List[Row] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        if line.strip().startswith("//"):
            continue
        r = parse_line_single_size(line, i)
        if r:
            rows.append(r)

    rows.sort(key=lambda r: (r.name, r.number))
    return rows


def rows_to_output_csv(rows: List[Row]) -> str:
    has_nick = any(r.nickname for r in rows)
    has_blood = any(r.blood for r in rows)
    if has_blood:
        has_nick = True

    out_lines: List[str] = []
    for r in rows:
        cols = [r.name, r.number, r.size_token]
        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)
        out_lines.append(",".join(cols))
    return "\n".join(out_lines)


# =========================
# JSON (manga curta sempre)
# =========================
def row_to_order(r: Row) -> dict:
    qty, size = parse_qty_and_size(r.size_token)
    gender = gender_from_size(size)

    return {
        "Name": r.name,
        "Nickname": r.nickname,
        "Number": r.number,
        "BloodType": r.blood,
        "Gender": gender,
        "ShortSleeve": f"{qty}-{size}",
        "LongSleeve": "",
        "Short": "",
        "Pants": "",
        "Tanktop": "",
        "Vest": ""
    }


def build_json_preview(rows: List[Row]) -> str:
    data = dict(BASE_JSON)
    data["orders"] = [row_to_order(r) for r in rows]
    return json.dumps(data, ensure_ascii=False, indent=4)


def export_json(rows: List[Row], out_dir: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = os.path.join(out_dir, f"List-{stamp}.json")

    data = dict(BASE_JSON)
    data["orders"] = [row_to_order(r) for r in rows]

    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    return fp


# =========================
# UI
# =========================
class PXFlowFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        cfg = load_config()
        self.output_dir_var = tk.StringVar(value=cfg.get("output_dir", DEFAULT_OUTPUT_DIR))

        self._last_rows: List[Row] = []
        self._last_json_preview: str = ""

        header = tk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(header, text="PXFlow", font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Button(header, text="Info", command=self.toggle_info).pack(side="right")

        self.info_frame = tk.LabelFrame(self, text="Informações / Regras")
        self.info_visible = False
        info_txt = (
            "• Cole a lista ou solte um .txt.\n"
            "• Comentários: linhas começando com // são ignoradas (em azul).\n"
            "• Modo padrão: 1 tamanho por linha.\n"
            "  - Formatos aceitos:\n"
            "    GG\n"
            "    NOME,NUMERO,TAM\n"
            "    NOME,NUMERO,TAM,APELIDO\n"
            "    NOME,NUMERO,TAM,APELIDO,TS\n"
            "  - TAM pode ser: G, BLP, 12A, ou QTY-TAM (3-G).\n"
            "• Se detectar mais de 1 tamanho na linha (ex: JOAO,5,G,M), o PXFlow sugere abrir o PXListPlus.\n"
            "• JSON: preenche apenas ShortSleeve (manga curta)."
        )
        tk.Label(self.info_frame, text=info_txt, justify="left", font=("Segoe UI", 9)).pack(
            anchor="w", padx=10, pady=8
        )

        out_row = tk.Frame(self)
        out_row.pack(fill="x", padx=10, pady=(0, 8))

        tk.Button(out_row, text="Pasta...", command=self.pick_output_folder).pack(side="left")
        self.lbl_out = tk.Label(out_row, text=f"Pasta de saída: {self.output_dir_var.get()}", font=("Segoe UI", 9))
        self.lbl_out.pack(side="right")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada:").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none", height=16, font=("Consolas", 10))
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        tab_list = tk.Frame(self.nb)
        tab_json = tk.Frame(self.nb)

        self.nb.add(tab_list, text="Lista organizada")
        self.nb.add(tab_json, text="Prévia JSON")

        tk.Label(tab_list, text="Saída organizada (copiada automaticamente ao Processar):").pack(anchor="w")
        self.txt_out = tk.Text(tab_list, wrap="none", height=16, font=("Consolas", 10))
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(tab_json, text="Prévia do JSON (sem salvar):").pack(anchor="w")
        self.txt_json = tk.Text(tab_json, wrap="none", height=16, font=("Consolas", 10))
        self.txt_json.pack(fill="both", expand=True, pady=(6, 0))
        self._set_text_readonly(self.txt_json, True)

        self.txt_in.tag_configure("comment", foreground="#1f6fd2")
        self.txt_in.bind("<KeyRelease>", lambda e: highlight_comments(self.txt_in))
        self.txt_in.bind("<Control-v>", lambda e: self.after(1, highlight_comments, self.txt_in))

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="left")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="left", padx=6)
        tk.Button(btns, text="Copiar JSON", command=self.copy_json).pack(side="left", padx=6)

        tk.Button(btns, text="Salvar JSON", command=self.save_json).pack(side="right")
        tk.Button(btns, text="Processar", command=self.process).pack(side="right", padx=6)

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 10))

        self.txt_in.drop_target_register(DND_FILES)
        self.txt_in.dnd_bind("<<Drop>>", self.on_drop_file)

        self.txt_in.insert(
            "1.0",
            "GG\n"
            "JOÃO,5,G\n"
            "JUACA,,PP,JUSÉ\n"
            "LUCAS,21,M,,O-\n"
            "\n"
            "// Se colar multi-peça (ex: JOAO,5,G,M) o PXFlow sugere abrir o PXListPlus.\n"
        )
        highlight_comments(self.txt_in)

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
        self._set_json_preview("")
        self._last_rows = []
        self.status_var.set("")
        highlight_comments(self.txt_in)

    def copy_output(self):
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há saída para copiar.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        self.status_var.set("📋 Saída copiada.")

    def copy_json(self):
        if not self._last_json_preview.strip():
            messagebox.showwarning(APP_NAME, "Ainda não há prévia do JSON. Clique em Processar primeiro.")
            return
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(self._last_json_preview)
        root.update()
        self.status_var.set("📋 JSON copiado.")

    def process(self):
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        if detect_multi_piece_input(raw):
            resp = messagebox.askyesno(
                APP_NAME,
                "Detectei mais de uma peça/tamanho em pelo menos uma linha.\n\n"
                "O PXFlow trabalha com 1 tamanho por linha.\n"
                "Deseja abrir o PXListPlus com essa mesma entrada?"
            )
            if resp:
                open_listplus_with_input(self.winfo_toplevel(), raw)
            return

        try:
            rows = process_text_single_size(raw)
            if not rows:
                messagebox.showwarning(APP_NAME, "Nenhuma linha válida encontrada.")
                return

            out_csv = rows_to_output_csv(rows)
            preview = build_json_preview(rows)

            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", out_csv)
            self._set_json_preview(preview)

            root = self.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(out_csv)
            root.update()

            self._last_rows = rows
            self.status_var.set(f"✅ Processado: {len(rows)} registro(s) | saída copiada | prévia JSON pronta.")
            self.nb.select(0)
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def save_json(self):
        if not self._last_rows:
            self.process()
            if not self._last_rows:
                return

        try:
            out_dir = self.ensure_output_dir()
            fp = export_json(self._last_rows, out_dir)

            messagebox.showinfo(APP_NAME, f"JSON gerado:\n{fp}\n\nRegistros: {len(self._last_rows)}")
            self.status_var.set(f"✅ JSON gerado: {fp} | Registros: {len(self._last_rows)}")
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
