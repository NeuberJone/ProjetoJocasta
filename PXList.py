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
# PXList - Config
# =========================
APP_NAME = "PXList"
DEFAULT_OUTPUT_DIR = r"C:\Listas"

BASE_JSON = {
    "title": "List",
    "order_number": 0,
    "client_name": "",
    "orders": [],
    "unique_name_chars": "",
    "unique_nickname_chars": ""
}

# Campo 3 obrigatório: QTY-TAMANHO (ex: 1-G, 3-BLP, 5-12A)
FIELD3_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$")

# Infantil: 2A até 12A (sufixo A)
CHILD_SIZE_RE = re.compile(r"^(?:[2-9]|1[0-2])A$", re.IGNORECASE)

# Tamanhos adultos permitidos (PP ao XXGG)
ADULT_SIZES = {"PP", "P", "M", "G", "GG", "XGG", "XXGG"}


# =========================
# Windows Taskbar Icon (recomendado)
# =========================
def set_windows_app_id():
    if os.name != "nt":
        return
    try:
        import ctypes  # noqa
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PXList.Pixels.PXList")
    except Exception:
        pass


def resource_path(relative_path: str) -> str:
    """
    Caminho correto para rodar em .py e em .exe (PyInstaller).
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(__file__), relative_path)


# =========================
# Config file (persistente no AppData)
# =========================
def get_config_file() -> str:
    base = os.environ.get("APPDATA") or str(Path.home())
    cfg_dir = Path(base) / APP_NAME
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "pxlist_config.json")


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


# =========================
# Helpers
# =========================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_name(value: str) -> str:
    return normalize_text(value).upper()


def extract_paths_from_drop(data: str) -> list[str]:
    # Pode vir: "{C:\a\b.txt}" ou "C:\a\b.txt" ou múltiplos
    files = re.findall(r"\{([^}]*)\}|(\S+)", (data or "").strip())
    paths = []
    for a, b in files:
        paths.append(a or b)
    return paths


def detect_gender_from_size(size: str) -> str:
    """
    Regras:
      - Infantil: tamanho termina com A e está entre 2A..12A => Gender "C"
      - Babylook: contém BL => Gender "FE"
      - Caso contrário => "MA"
    Divergência:
      - Contém BL e termina com A => erro (não pode)
    """
    s = (size or "").strip().upper()

    has_bl = "BL" in s
    ends_a = s.endswith("A")

    if has_bl and ends_a:
        raise ValueError("Divergência: tamanho contém 'BL' e termina com 'A' (infantil).")

    if ends_a:
        if not CHILD_SIZE_RE.fullmatch(s):
            raise ValueError("Tamanho infantil inválido. Use de 2A até 12A.")
        return "C"

    if has_bl:
        return "FE"

    # Adulto: valida se está na lista
    if s not in ADULT_SIZES:
        raise ValueError(f"Tamanho adulto inválido. Permitidos: {', '.join(sorted(ADULT_SIZES))}")
    return "MA"


def parse_line_fixed(line: str, line_no: int) -> tuple[dict, list[str]]:
    """
    Formato fixo (vindo do PXListLite):
      1) Nome
      2) Número (pode ser vazio e pode conter letras, ex: 7X1)
      3) QTY-TAMANHO (obrigatório, ex: 1-G, 3-BLP, 5-12A)
      4) Apelido (opcional)
      5) Tipo sanguíneo (opcional)

    Retorna: (order_dict, warnings)
    Lança ValueError para erros que devem bloquear a geração do JSON.
    """
    raw = line.strip().replace("\ufeff", "")
    if not raw:
        raise ValueError("Linha vazia.")

    parts = [p.strip() for p in raw.split(",")]

    # Aceita até 5 campos; mais do que isso é erro (para evitar dados bagunçados)
    if len(parts) > 5:
        raise ValueError("Formato inválido: mais de 5 campos separados por vírgula.")

    # Preenche faltantes com vazio
    while len(parts) < 5:
        parts.append("")

    name_raw, number_raw, field3_raw, nick_raw, blood_raw = parts

    name = normalize_name(name_raw)
    number = normalize_text(number_raw)  # manter exatamente como veio (sem normalizar dígitos)
    nickname = normalize_name(nick_raw) if nick_raw.strip() else ""
    blood = normalize_text(blood_raw)

    # Campo 3 obrigatório e estrito
    field3 = field3_raw.strip().upper()

    # Caso 1: QTY-TAMANHO
    m = FIELD3_RE.fullmatch(field3)
    if m:
        qty = int(m.group(1))
        size = m.group(2).strip().upper()
    else:
        # Caso 2: somente TAMANHO → qty = 1
        qty = 1
        size = field3

    if qty <= 0:
        raise ValueError("Quantidade inválida no campo 3: deve ser maior que zero.")


    if qty <= 0:
        raise ValueError("Quantidade inválida no campo 3: deve ser maior que zero.")

    gender = detect_gender_from_size(size)

    order = {
        "Name": name,
        "Nickname": nickname,
        "Number": number,
        "BloodType": blood,
        "Gender": gender,
        "ShortSleeve": f"{qty}-{size}",
        "LongSleeve": "",
        "Short": "",
        "Pants": "",
        "Tanktop": "",
        "Vest": ""
    }

    return order, []


def build_json_from_text_strict(text: str) -> tuple[dict, list[str], int]:
    """
    Estrito:
      - Qualquer erro em qualquer linha -> NÃO gera arquivo.
      - Retorna: (json_data, errors, total_orders)
    """
    orders = []
    errors = []

    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        raw = line.strip()
        if not raw:
            continue

        try:
            order, _warnings = parse_line_fixed(raw, i)
            orders.append(order)
        except Exception as e:
            errors.append(f"Linha {i}: {raw}\n  -> {e}")

    data = dict(BASE_JSON)
    data["orders"] = orders
    return data, errors, len(orders)


def export_json(data: dict, out_dir: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = os.path.join(out_dir, f"List-{stamp}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return fp


# =========================
# UI
# =========================
def build_ui(parent):
    cfg = load_config()
    output_dir_default = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
    output_dir_var = tk.StringVar(value=output_dir_default)
    status_var = tk.StringVar(value=f"📁 Pasta de saída: {output_dir_var.get()}")

    frame = tk.Frame(parent, padx=14, pady=14)
    frame.pack(fill="both", expand=True)

    def choose_output_dir():
        folder = filedialog.askdirectory(title="Escolher pasta de saída")
        if not folder:
            return
        output_dir_var.set(folder)
        cfg["output_dir"] = folder
        save_config(cfg)
        status_var.set(f"📁 Pasta de saída: {output_dir_var.get()}")

    def ensure_output_dir() -> str:
        out = output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR
        output_dir_var.set(out)
        ensure_dir(out)
        return out

    def generate_from_text():
        try:
            raw = text_box.get("1.0", "end").strip()
            if not raw:
                messagebox.showwarning(APP_NAME, "Cole uma lista antes de gerar.")
                return

            data, errors, total = build_json_from_text_strict(raw)
            if errors:
                # Não gera arquivo!
                err_text = "\n\n".join(errors[:30])
                more = ""
                if len(errors) > 30:
                    more = f"\n\n... e mais {len(errors) - 30} erro(s)."
                messagebox.showerror(APP_NAME, f"Foram encontrados erros. Nenhum arquivo foi gerado.\n\n{err_text}{more}")
                status_var.set(f"❌ Erros encontrados: {len(errors)} | Nenhum arquivo gerado")
                return

            if total == 0:
                messagebox.showwarning(APP_NAME, "Nenhum registro válido encontrado (lista vazia?).")
                status_var.set("⚠️ Nenhum registro gerado")
                return

            out_dir = ensure_output_dir()
            fp = export_json(data, out_dir)

            msg = f"Arquivo gerado:\n{fp}\n\nRegistros: {total}"
            status_var.set(f"✅ Exportado: {fp} | Registros: {total}")
            messagebox.showinfo(APP_NAME, msg)

        except Exception as e:
            status_var.set(f"❌ Erro: {e}")
            messagebox.showerror(APP_NAME, str(e))

    def on_drop(event):
        try:
            # pode vir múltiplos; pega o primeiro
            paths = extract_paths_from_drop(event.data)
            if not paths:
                return

            p = Path(paths[0].strip().strip('"'))
            if not p.exists():
                raise FileNotFoundError("Arquivo não encontrado.")
            if p.suffix.lower() != ".txt":
                raise ValueError("Solte um arquivo .txt.")

            content = p.read_text(encoding="utf-8", errors="replace")
            text_box.delete("1.0", "end")
            text_box.insert("1.0", content)
            status_var.set(f"📄 TXT carregado: {p.name}")

        except Exception as e:
            status_var.set(f"❌ Erro: {e}")
            messagebox.showerror(APP_NAME, str(e))

    tk.Label(frame, text="PXList — cole a lista do PXListLite ou solte um .txt", font=("Segoe UI", 14, "bold")).pack(anchor="w")

    tk.Label(
        frame,
        text="Formato por linha (por vírgulas):\n"
             "1) Nome, 2) Número, 3) QTY-TAMANHO, 4) Apelido (opcional), 5) Tipo sanguíneo (opcional)\n"
             "Campo 3 é obrigatório e deve ser QTY-TAMANHO (ex: 1-G, 3-BLP, 5-12A).\n"
             "Gender: Infantil (2A..12A) => C | BL => FE | demais => MA.\n"
             "Qualquer erro bloqueia a geração (não cria arquivo).",
        font=("Segoe UI", 9)
    ).pack(anchor="w", pady=(6, 10))

    tk.Button(frame, text="Escolher pasta de saída", command=choose_output_dir).pack(anchor="w", pady=(0, 6))

    text_box = tk.Text(frame, height=12, wrap="word", font=("Consolas", 10))
    text_box.pack(fill="x", pady=(0, 8))

    tk.Button(frame, text="Gerar JSON a partir do texto", command=generate_from_text).pack(pady=(0, 10))

    drop_area = tk.Label(
        frame,
        text="SOLTE AQUI (.txt)",
        font=("Segoe UI", 18, "bold"),
        relief="ridge",
        bd=2,
        width=30,
        height=3
    )
    drop_area.pack(pady=6)

    tk.Label(frame, textvariable=status_var, font=("Segoe UI", 9)).pack(pady=(10, 0))

    drop_area.drop_target_register(DND_FILES)
    drop_area.dnd_bind("<<Drop>>", on_drop)

    return frame


def main():
    set_windows_app_id()

    app = TkinterDnD.Tk()
    app.title(APP_NAME)
    app.geometry("720x560")
    app.resizable(False, False)

    # Ícone da janela (e ajuda na taskbar) - opcional
    try:
        app.iconbitmap(resource_path("pxlist.ico"))
    except Exception:
        pass

    ui = build_ui(app)
    ui.pack(fill="both", expand=True)
    app.mainloop()


if __name__ == "__main__":
    main()
