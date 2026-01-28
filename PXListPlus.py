import json
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
from pathlib import Path

from tkinterdnd2 import DND_FILES, TkinterDnD


# =========================
# PXListPlus - Config
# =========================
APP_NAME = "PXListPlus"
DEFAULT_OUTPUT_DIR = r"C:\Listas"

BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": ""
}

# Adulto (PP ao XXGG)
ADULT_SIZES = {"PP", "P", "M", "G", "GG", "XGG", "XXGG"}

# Infantil: 2A..12A
CHILD_SIZE_RE = re.compile(r"^(?:[2-9]|1[0-2])A$", re.IGNORECASE)

# QTY-TAMANHO: 3-G, 5-12A, 2-BLP
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)

# Proibir aspas em campos (evita "" como vazio)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")

# =========================
# Peças do JSON (6)
# =========================
GARMENTS = [
    ("ShortSleeve", "Camiseta (manga curta)"),
    ("LongSleeve", "Camiseta (manga longa)"),
    ("Short", "Bermuda"),
    ("Pants", "Calça"),
    ("Tanktop", "Regata"),
    ("Vest", "Colete"),
]


# =========================
# Helpers - Paths / Config
# =========================
def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


def get_config_file() -> str:
    base = os.environ.get("APPDATA") or str(Path.home())
    cfg_dir = Path(base) / APP_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "pxlistplus_config.json")


def load_config() -> dict:
    cfg_path = get_config_file()
    if not os.path.exists(cfg_path):
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    cfg_path = get_config_file()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def extract_paths_from_drop(data: str) -> list[str]:
    files = re.findall(r"\{([^}]*)\}|(\S+)", (data or "").strip())
    paths = []
    for a, b in files:
        paths.append(a or b)
    return paths


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def normalize_name(s: str) -> str:
    return normalize_spaces(s).upper()


def clean_token(tok: str) -> str:
    return (tok or "").strip()


def forbid_quotes(line_no: int, tok: str) -> None:
    if tok and FORBIDDEN_QUOTE_RE.search(tok):
        raise ValueError(f"Linha {line_no}: campo contém aspas (não use \"\"), token: {tok!r}")


# =========================
# Regras de tamanho
# =========================
def is_child_size(size: str) -> bool:
    return bool(CHILD_SIZE_RE.fullmatch(size))


def is_adult_size(size: str) -> bool:
    return size in ADULT_SIZES


def is_babylook_size(size: str) -> bool:
    # Babylook: BL + tamanho adulto
    s = size.upper()
    if not s.startswith("BL"):
        return False
    suffix = s[2:]
    return suffix in ADULT_SIZES


def is_size_token(tok: str) -> bool:
    """
    Válido se:
      - TAMANHO sozinho: adulto (PP..XXGG), infantil (2A..12A), babylook (BL + adulto)
      - QTY-TAMANHO: 3-G, 2-BLP, 5-12A
    """
    t = clean_token(tok).upper()
    if not t:
        return False

    # size sozinho
    if is_adult_size(t) or is_child_size(t) or is_babylook_size(t):
        return True

    # qty-size
    m = QTY_SIZE_RE.match(t)
    if not m:
        return False
    size = m.group(2).strip().upper()
    return is_adult_size(size) or is_child_size(size) or is_babylook_size(size)


def normalize_size_token(tok: str, line_no: int) -> str:
    """
    Normaliza para sempre "QTY-SIZE".
    Aceita:
      - "G"   -> "1-G"
      - "12A" -> "1-12A"
      - "BLP" -> "1-BLP"
      - "3-G" -> "3-G"
    """
    t = clean_token(tok).upper()
    if not t:
        raise ValueError(f"Linha {line_no}: tamanho vazio.")

    m = QTY_SIZE_RE.match(t)
    if m:
        qty = int(m.group(1))
        size = m.group(2).strip().upper()
        if qty <= 0:
            raise ValueError(f"Linha {line_no}: quantidade inválida (<= 0) em {tok!r}.")
        if not (is_adult_size(size) or is_child_size(size) or is_babylook_size(size)):
            raise ValueError(f"Linha {line_no}: tamanho inválido em {tok!r}.")
        return f"{qty}-{size}"

    # tamanho sozinho => qty=1
    size = t
    if not (is_adult_size(size) or is_child_size(size) or is_babylook_size(size)):
        raise ValueError(f"Linha {line_no}: tamanho inválido em {tok!r}.")
    return f"1-{size}"


def detect_gender_from_sizes(sizes_normalized: list[str], line_no: int) -> str:
    """
    Gender:
      - C se existir qualquer tamanho infantil (..A entre 2A..12A)
      - FE se existir qualquer tamanho com BL
      - MA caso contrário
    Erro:
      - Se existir infantil e BL ao mesmo tempo (divergência)
    """
    has_child = False
    has_bl = False

    for s in sizes_normalized:
        # s no formato QTY-SIZE
        try:
            _qty, _size = s.split("-", 1)
        except ValueError:
            _size = s
        size = _size.upper()

        if size.endswith("A") and is_child_size(size):
            has_child = True
        if "BL" in size:
            has_bl = True

    if has_child and has_bl:
        raise ValueError(f"Linha {line_no}: divergência de dados (infantil + babylook na mesma linha).")

    if has_child:
        return "C"
    if has_bl:
        return "FE"
    return "MA"


# =========================
# Parsing de linha (dinâmico)
# =========================
def parse_line_dynamic(line: str, line_no: int) -> tuple[str, str, list[str], str, str]:
    """
    Linha por vírgulas (dinâmico):
      - Primeiro token STRING vira Name
      - Primeiro token que tem dígito vira Number (mantém exatamente, apenas trim)
      - Tokens que parecem tamanho viram lista de tamanhos (até 6)
      - Outras strings restantes viram: Nickname (primeira) e BloodType (segunda)
    Regras:
      - Não aceitar aspas ("" etc.)
    """
    raw = line.strip().replace("\ufeff", "")
    if not raw:
        raise ValueError(f"Linha {line_no}: vazia.")

    parts = [clean_token(p) for p in raw.split(",")]  # preserva vazios (",,")
    for tok in parts:
        forbid_quotes(line_no, tok)

    name = ""
    number = ""
    sizes: list[str] = []
    extras: list[str] = []

    for tok in parts:
        tok = clean_token(tok)
        if not tok:
            continue

        up = tok.upper()

        if is_size_token(up):
            sizes.append(normalize_size_token(up, line_no))
            continue

        # número: primeiro token que contém pelo menos 1 dígito
        if (not number) and any(ch.isdigit() for ch in tok):
            number = normalize_spaces(tok)  # mantém como veio (pode ser 7X1)
            continue

        # strings
        if not name:
            name = normalize_name(tok)
        else:
            extras.append(normalize_spaces(tok).upper())

    nickname = extras[0] if len(extras) >= 1 else ""
    blood = extras[1] if len(extras) >= 2 else ""

    return name, number, sizes, nickname, blood


# =========================
# Montagem do JSON
# =========================
def make_order(name: str, number: str, gender: str, nickname: str, blood: str, garment_map: dict) -> dict:
    base = {
        "Name": name or "",
        "Nickname": nickname or "",
        "Number": number or "",
        "BloodType": blood or "",
        "Gender": gender,
        "ShortSleeve": "",
        "LongSleeve": "",
        "Short": "",
        "Pants": "",
        "Tanktop": "",
        "Vest": "",
    }
    base.update(garment_map)
    return base


def write_json(orders: list[dict], output_dir: str) -> str:
    ensure_dir(output_dir)

    out = dict(BASE_JSON)
    out["orders"] = orders

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_path = os.path.join(output_dir, f"List-{stamp}.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)

    return out_path


# =========================
# UI - Checkboxes com ordem
# =========================
class OrderedCheckboxes(tk.Frame):
    """
    Lista de checkboxes onde a ordem de marcação define a sequência.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self._selected_keys: list[str] = []
        self._vars: dict[str, tk.IntVar] = {}
        self._labels: dict[str, tk.StringVar] = {}

        title = tk.Label(self, text="Selecione as peças (a ORDEM que marcar define o mapeamento):", font=("Segoe UI", 10, "bold"))
        title.pack(anchor="w", pady=(0, 6))

        for key, pt_name in GARMENTS:
            var = tk.IntVar(value=0)
            label_var = tk.StringVar(value=pt_name)

            row = tk.Frame(self)
            row.pack(fill="x", anchor="w")

            cb = tk.Checkbutton(
                row,
                textvariable=label_var,
                variable=var,
                command=lambda k=key: self._on_toggle(k)
            )
            cb.pack(side="left", anchor="w")

            self._vars[key] = var
            self._labels[key] = label_var

        note = tk.Label(
            self,
            text="Ex.: Se marcar (1) Calça, (2) Camiseta curta, (3) Bermuda, então TAM1→Calça, TAM2→Curta, TAM3→Bermuda.",
            font=("Segoe UI", 9),
            fg="#444"
        )
        note.pack(anchor="w", pady=(8, 0))

    def _relabel(self):
        # Atualiza textos com (ordem) quando marcado
        order_map = {k: i + 1 for i, k in enumerate(self._selected_keys)}
        for key, pt_name in GARMENTS:
            base_name = pt_name
            if key in order_map:
                self._labels[key].set(f"{base_name} ({order_map[key]})")
            else:
                self._labels[key].set(base_name)

    def _on_toggle(self, key: str):
        checked = bool(self._vars[key].get())

        if checked:
            if key not in self._selected_keys:
                self._selected_keys.append(key)
        else:
            if key in self._selected_keys:
                self._selected_keys.remove(key)

        self._relabel()

    def get_selected_in_order(self) -> list[str]:
        return list(self._selected_keys)

    def clear(self):
        self._selected_keys.clear()
        for key in self._vars:
            self._vars[key].set(0)
        self._relabel()


# =========================
# App
# =========================
class PXListPlusApp:
    def __init__(self):
        self.cfg = load_config()

        self.app = TkinterDnD.Tk()
        self.app.title(APP_NAME)
        self.app.geometry("820x640")
        self.app.resizable(False, False)

        # Ícone opcional (se existir pxlist.ico na pasta)
        try:
            self.app.iconbitmap(resource_path("pxlist.ico"))
        except Exception:
            pass

        root = tk.Frame(self.app, padx=14, pady=14)
        root.pack(fill="both", expand=True)

        tk.Label(root, text="PXListPlus — gera JSON com mapeamento por ordem de seleção", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        tk.Label(
            root,
            text=(
                "Entrada (dinâmica, por vírgulas): Nome, Número, TAMs..., Apelido(opcional), Tipo Sanguíneo(opcional)\n"
                "Tamanho aceita: QTY-TAMANHO (ex: 3-G, 5-12A, 2-BLP) ou TAMANHO sozinho (ex: G, 12A, BLP => vira 1-TAM).\n"
                "Validação: 0 peças marcadas = erro. Nº de TAMs deve ser IGUAL ao nº de peças marcadas (mais ou menos = erro).\n"
                "Qualquer erro em qualquer linha bloqueia a geração (não cria arquivo)."
            ),
            font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(6, 10))

        # Pasta saída
        top_row = tk.Frame(root)
        top_row.pack(fill="x", pady=(0, 10))

        self.output_dir_var = tk.StringVar(value=self.cfg.get("output_dir", DEFAULT_OUTPUT_DIR))
        self.status_var = tk.StringVar(value=f"📁 Pasta de saída: {self.output_dir_var.get()}")

        tk.Button(top_row, text="Escolher pasta de saída", command=self.pick_output_folder).pack(side="left")
        tk.Label(top_row, textvariable=self.status_var, font=("Segoe UI", 9)).pack(side="right")

        # Checkboxes
        self.ck = OrderedCheckboxes(root)
        self.ck.pack(fill="x", pady=(0, 10))

        # Entrada manual
        tk.Label(root, text="Cole a lista abaixo (uma pessoa por linha):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.txt_in = tk.Text(root, height=12, wrap="none", font=("Consolas", 10))
        self.txt_in.pack(fill="x", pady=(6, 10))

        btn_row = tk.Frame(root)
        btn_row.pack(fill="x", pady=(0, 10))

        tk.Button(btn_row, text="Gerar JSON", command=self.generate_json).pack(side="right")
        tk.Button(btn_row, text="Limpar", command=self.clear_all).pack(side="right", padx=6)

        # Drag & Drop
        self.drop_area = tk.Label(
            root,
            text="SOLTE AQUI (.txt)",
            font=("Segoe UI", 18, "bold"),
            relief="ridge",
            bd=2,
            width=32,
            height=3
        )
        self.drop_area.pack(pady=8)

        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<Drop>>", self.on_drop)

    def pick_output_folder(self):
        folder = filedialog.askdirectory(title=f"{APP_NAME} - Escolha a pasta para salvar o JSON")
        if not folder:
            return
        self.output_dir_var.set(folder)
        self.cfg["output_dir"] = folder
        save_config(self.cfg)
        self.status_var.set(f"📁 Pasta de saída: {folder}")

    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.ck.clear()

    def on_drop(self, event):
        try:
            paths = extract_paths_from_drop(event.data)
            if not paths:
                return

            txt_path = paths[0].strip().strip('"')
            p = Path(txt_path)
            if not p.exists():
                raise FileNotFoundError("Arquivo não encontrado.")
            if p.suffix.lower() != ".txt":
                raise ValueError("Solte um arquivo .txt.")

            content = p.read_text(encoding="utf-8", errors="replace")
            self.txt_in.delete("1.0", "end")
            self.txt_in.insert("1.0", content)
            self.status_var.set(f"📄 TXT carregado: {p.name}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def generate_json(self):
        selected = self.ck.get_selected_in_order()
        if len(selected) == 0:
            messagebox.showerror(APP_NAME, "Erro: marque pelo menos 1 peça (a ordem define o mapeamento).")
            return

        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada (ou solte um .txt).")
            return

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            messagebox.showwarning(APP_NAME, "A lista está vazia.")
            return

        orders: list[dict] = []
        errors: list[str] = []

        for idx, line in enumerate(lines, start=1):
            try:
                name, number, sizes, nickname, blood = parse_line_dynamic(line, idx)

                if not name:
                    # Nome pode ser vazio? você não proibiu no Plus.
                    # Se quiser bloquear, troque por erro.
                    name = ""

                # validação do tamanho vs seleção
                if len(sizes) != len(selected):
                    raise ValueError(
                        f"Linha {idx}: quantidade de TAMs ({len(sizes)}) diferente da quantidade de peças marcadas ({len(selected)})."
                    )

                # gênero (com validação divergência infantil + babylook)
                gender = detect_gender_from_sizes(sizes, idx)

                # mapa das peças conforme ordem das checkboxes
                garment_map = {k: "" for k, _ in GARMENTS}
                for i, garment_key in enumerate(selected):
                    garment_map[garment_key] = sizes[i]

                orders.append(make_order(normalize_name(name), normalize_spaces(number), gender, normalize_name(nickname), normalize_spaces(blood), garment_map))

            except Exception as e:
                errors.append(f"{e}\n  Conteúdo: {line}")

        # bloqueia se tiver qualquer erro
        if errors:
            err_text = "\n\n".join(errors[:25])
            more = ""
            if len(errors) > 25:
                more = f"\n\n... e mais {len(errors) - 25} erro(s)."
            messagebox.showerror(APP_NAME, f"Foram encontrados erros. Nenhum arquivo foi gerado.\n\n{err_text}{more}")
            self.status_var.set(f"❌ Erros: {len(errors)} | Nenhum arquivo gerado")
            return

        out_dir = self.output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR
        ensure_dir(out_dir)

        out_path = write_json(orders, out_dir)
        messagebox.showinfo(APP_NAME, f"JSON gerado:\n{out_path}\n\nRegistros: {len(orders)}")
        self.status_var.set(f"✅ Gerado: {out_path} | Registros: {len(orders)}")

    def run(self):
        self.app.mainloop()


if __name__ == "__main__":
    PXListPlusApp().run()
