import json
import os
import re
import tkinter as tk
import sys
from tkinter import filedialog, messagebox
from datetime import datetime
from pathlib import Path

from tkinterdnd2 import DND_FILES, TkinterDnD


# =========================
# PXList - Config
# =========================
APP_NAME = "PXList"

DEFAULT_OUTPUT_DIR = r"C:\Listas"
def get_config_file() -> str:
    # Ex: C:\Users\SeuUsuario\AppData\Roaming\PXList\config.json
    appdata = os.getenv("APPDATA")
    base_dir = Path(appdata) if appdata else Path.home()
    cfg_dir = base_dir / APP_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "config.json")


CONFIG_FILE = get_config_file()


BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": ""
}

# Ex: 3m, 20p, 4g, 2blg
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*([A-Za-z]+)\s*$")          # ex: 3M, 2BLG
QTY_DASH_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z]+)\s*$") # ex: 3-G

# Tamanhos permitidos (PP ao XXGG)
ALLOWED_SIZES = {"PP", "P", "M", "G", "GG", "XGG", "XXGG"}


# =========================
# Helpers
# =========================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_output_dir() -> str:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        out_dir = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
        return out_dir or DEFAULT_OUTPUT_DIR
    except Exception:
        return DEFAULT_OUTPUT_DIR


def save_output_dir(path: str) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"output_dir": path}, f, ensure_ascii=False, indent=4)


def extract_paths_from_drop(data: str) -> list[str]:
    # Pode vir: "{C:\a\b.txt}" ou "C:\a\b.txt" ou múltiplos
    files = re.findall(r"\{([^}]*)\}|(\S+)", (data or "").strip())
    paths = []
    for a, b in files:
        paths.append(a or b)
    return paths


def normalize_number(number_raw: str) -> str:
    """
    Número pode ser vazio.
    Se vier, mantém só dígitos e faz zfill(2).
    """
    digits = re.sub(r"\D+", "", (number_raw or ""))
    return digits.zfill(2) if digits else ""


def is_size_token(token: str) -> bool:
    """
    Tamanho válido se:
      - estiver em ALLOWED_SIZES (PP ao XXGG)
      - OU for Babylook: "BL" + tamanho permitido (ex: BLP, BLM, BLGG, BLXXGG)
    """
    t = (token or "").strip().upper()
    if not t:
        return False

    # somente letras
    if not re.fullmatch(r"[A-Z]+", t):
        return False

    if t in ALLOWED_SIZES:
        return True

    if t.startswith("BL"):
        suffix = t[2:]
        return suffix in ALLOWED_SIZES

    return False


def tokenize_line(line: str) -> list[str]:
    """
    Quebra a linha por vírgula e espaços, preservando tokens como '3-G'.
    """
    raw = line.strip().replace("\ufeff", "")
    if not raw:
        return []
    tokens = re.split(r"[,\s]+", raw)
    return [t for t in tokens if t.strip()]


def extract_qty_and_size(tokens: list[str]) -> tuple[int, str, list[str]]:
    """
    Procura o primeiro tamanho (obrigatório) em qualquer posição.
    Aceita:
      - 20P, 3M, 2BLG
      - 3-G
      - 2 BLP  (qty separado do tamanho)
      - BLP, GG, M (qty = 1)
    Retorna (qty, size, tokens_restantes_sem_os_usados)
    """
    used = [False] * len(tokens)

    # Passo 1: prioridade para tamanho explícito (BLP, GG, M...) OU qty+tamanho grudado (3M/2BLG/3-G)
    for i, tok in enumerate(tokens):
        t = tok.strip().upper()

        m = QTY_DASH_SIZE_RE.match(t)  # 3-G
        if m:
            qty = int(m.group(1))
            size = m.group(2).upper()
            if is_size_token(size):
                used[i] = True
                rest = [tokens[j] for j in range(len(tokens)) if not used[j]]
                return qty, size, rest

        m = QTY_SIZE_RE.match(t)  # 3M / 2BLG
        if m:
            qty = int(m.group(1))
            size = m.group(2).upper()
            if is_size_token(size):
                used[i] = True
                rest = [tokens[j] for j in range(len(tokens)) if not used[j]]
                return qty, size, rest

        if is_size_token(t):  # BLP / GG / M
            qty = 1
            size = t
            used[i] = True
            rest = [tokens[j] for j in range(len(tokens)) if not used[j]]
            return qty, size, rest

    # Passo 2: só se não achou tamanho explícito, tenta "2 BLP"
    for i, tok in enumerate(tokens):
        t = tok.strip().upper()
        if t.isdigit() and i + 1 < len(tokens):
            next_t = tokens[i + 1].strip().upper()
            if is_size_token(next_t):
                qty = int(t)
                size = next_t
                used[i] = True
                used[i + 1] = True
                rest = [tokens[j] for j in range(len(tokens)) if not used[j]]
                return qty, size, rest

    raise ValueError("Tamanho não encontrado.")


def extract_number(tokens: list[str]) -> tuple[str, list[str]]:
    """
    Procura o primeiro token que contenha dígitos e usa como Number (opcional).
    Retorna (number_formatado_ou_vazio, tokens_restantes_sem_o_usado)
    """
    for i, tok in enumerate(tokens):
        if re.search(r"\d", tok):
            number = normalize_number(tok)
            rest = tokens[:i] + tokens[i + 1:]
            return number, rest
    return "", tokens


def parse_line_smart(line: str) -> tuple[str, str, int, str]:
    """
    Estratégia:
      1) Se a linha estiver no formato COM VÍRGULAS: Nome, Número, Tamanho
         - força Number = campo 2
         - força Size = campo 3
         - Qty = 1
      2) Caso contrário, usa modo ordem livre:
         - tamanho obrigatório em qualquer lugar
         - número opcional (primeiro token com dígitos)
         - nome = resto
    Retorna (name, number, qty, size)
    """
    raw = line.strip().replace("\ufeff", "")
    if not raw:
        raise ValueError("Linha vazia.")

    # 1) Prioridade para padrão "Nome, Número, Tamanho"
    comma_parts = [p.strip() for p in raw.split(",")]
    if len(comma_parts) >= 3:
        name = comma_parts[0]
        number_raw = comma_parts[1]
        size_raw = comma_parts[2]

        size_candidate = (size_raw or "").strip().upper()
        if is_size_token(size_candidate):
            return (name or "").upper(), normalize_number(number_raw), 1, size_candidate

        # também aceita caso o tamanho venha como "3BLM" / "3-G" no 3º campo
        m = QTY_DASH_SIZE_RE.match(size_candidate)
        if m and is_size_token(m.group(2).upper()):
            return (name or "").upper(), normalize_number(number_raw), int(m.group(1)), m.group(2).upper()

        m = QTY_SIZE_RE.match(size_candidate)
        if m and is_size_token(m.group(2).upper()):
            return (name or "").upper(), normalize_number(number_raw), int(m.group(1)), m.group(2).upper()

        # se não reconhecer, cai no modo livre

    # 2) Modo ordem livre
    tokens = tokenize_line(raw)
    if not tokens:
        raise ValueError("Linha vazia.")

    qty, size, rest = extract_qty_and_size(tokens)
    number, rest2 = extract_number(rest)
    name = " ".join(rest2).strip().upper()

    return name, number, qty, size.upper()


def make_order(name: str, number: str, qty: int, size: str) -> dict:
    gender = "FE" if "BL" in size.upper() else "MA"

    return {
        "Name": (name or "").upper(),
        "Nickname": "",
        "Number": number,
        "BloodType": "",
        "Gender": gender,
        "ShortSleeve": f"{qty}-{size.upper()}",
        "LongSleeve": "",
        "Short": "",
        "Pants": "",
        "Tanktop": "",
        "Vest": ""
    }


def write_json(orders: list[dict], output_dir: str) -> str:
    out = dict(BASE_JSON)
    out["orders"] = orders

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    out_filename = f"List-{timestamp}.json"
    out_path = os.path.join(output_dir, out_filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)

    return out_path


def convert_txt_to_json(txt_path: str, output_dir: str) -> tuple[str, int, int]:
    if not os.path.isfile(txt_path):
        raise FileNotFoundError("Arquivo não encontrado.")

    ensure_dir(output_dir)

    with open(txt_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    orders = []
    skipped = 0

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        try:
            name, number, qty, size = parse_line_smart(raw)
        except ValueError:
            skipped += 1
            continue

        orders.append(make_order(name, number, qty, size))

    out_path = write_json(orders, output_dir)
    return out_path, skipped, len(orders)


def convert_text_to_json(text: str, output_dir: str) -> tuple[str, int, int]:
    ensure_dir(output_dir)

    lines = text.splitlines()

    orders = []
    skipped = 0

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        try:
            name, number, qty, size = parse_line_smart(raw)
        except ValueError:
            skipped += 1
            continue

        orders.append(make_order(name, number, qty, size))

    out_path = write_json(orders, output_dir)
    return out_path, skipped, len(orders)


# =========================
# UI
# =========================
def pick_output_folder():
    folder = filedialog.askdirectory(title="PXList - Escolha a pasta para salvar o JSON")
    if folder:
        output_dir_var.set(folder)
        save_output_dir(folder)
        status_var.set(f"📁 Pasta de saída: {folder}")


def generate_from_text():
    content = text_box.get("1.0", "end").strip()
    if not content:
        messagebox.showwarning("PXList", "A lista em texto está vazia.")
        return

    try:
        out_path, skipped, total = convert_text_to_json(content, output_dir_var.get())
        msg = f"JSON gerado:\n{out_path}\n\nRegistros gerados: {total}"
        if skipped:
            msg += f"\nLinhas ignoradas (sem tamanho válido): {skipped}"
        messagebox.showinfo("PXList", msg)
        status_var.set(f"✅ Gerado: {out_path} | Registros: {total} | Ignoradas: {skipped}")
    except Exception as e:
        messagebox.showerror("PXList - Erro", str(e))
        status_var.set(f"❌ Erro: {e}")


def on_drop(event):
    paths = extract_paths_from_drop(event.data)
    if not paths:
        return

    txt_path = paths[0]

    if not txt_path.lower().endswith(".txt"):
        messagebox.showwarning("PXList", "Arraste um arquivo .txt")
        return

    try:
        out_path, skipped, total = convert_txt_to_json(txt_path, output_dir_var.get())
        msg = f"JSON gerado:\n{out_path}\n\nRegistros gerados: {total}"
        if skipped:
            msg += f"\nLinhas ignoradas (sem tamanho válido): {skipped}"
        messagebox.showinfo("PXList", msg)
        status_var.set(f"✅ Gerado: {out_path} | Registros: {total} | Ignoradas: {skipped}")
    except Exception as e:
        messagebox.showerror("PXList - Erro", str(e))
        status_var.set(f"❌ Erro: {e}")


app = TkinterDnD.Tk()
app.title(APP_NAME)
app.geometry("680x520")
app.resizable(False, False)

frame = tk.Frame(app, padx=14, pady=14)
frame.pack(fill="both", expand=True)

tk.Label(frame, text="PXList — arraste o arquivo .txt aqui", font=("Segoe UI", 14, "bold")).pack(pady=(6, 4))

tk.Label(
    frame,
    text="Formato por linha:\n"
         "- Preferido com vírgulas: Nome, Número, Tamanho\n"
         "- Ordem livre também funciona: tamanho obrigatório (PP..XXGG / BLP..BLXXGG), número opcional, nome opcional.\n"
         "- Quantidade pode vir como: 3M, 2 BLP, 3-G\n",
    font=("Segoe UI", 9)
).pack(pady=(0, 10))

output_dir_var = tk.StringVar(value=load_output_dir())
ensure_dir(output_dir_var.get())

row = tk.Frame(frame)
row.pack(fill="x", pady=(0, 8))

tk.Label(row, text="Pasta de saída:", font=("Segoe UI", 10, "bold")).pack(side="left")
tk.Label(row, textvariable=output_dir_var, font=("Segoe UI", 10)).pack(side="left", padx=8)

tk.Button(row, text="Alterar pasta...", command=pick_output_folder).pack(side="right")

# ===== Entrada manual =====
tk.Label(
    frame,
    text="Ou cole a lista abaixo (uma pessoa por linha):",
    font=("Segoe UI", 10, "bold")
).pack(anchor="w", pady=(10, 4))

text_box = tk.Text(frame, height=8, font=("Consolas", 10))
text_box.pack(fill="x", pady=(0, 8))

tk.Button(frame, text="Gerar JSON a partir do texto", command=generate_from_text).pack(pady=(0, 10))

# ===== Drag & Drop =====
drop_area = tk.Label(
    frame,
    text="SOLTE AQUI",
    font=("Segoe UI", 18, "bold"),
    relief="ridge",
    bd=2,
    width=30,
    height=3
)
drop_area.pack(pady=6)

status_var = tk.StringVar(value=f"📁 Pasta de saída: {output_dir_var.get()}")
tk.Label(frame, textvariable=status_var, font=("Segoe UI", 9)).pack(pady=(10, 0))

drop_area.drop_target_register(DND_FILES)
drop_area.dnd_bind("<<Drop>>", on_drop)

app.mainloop()
