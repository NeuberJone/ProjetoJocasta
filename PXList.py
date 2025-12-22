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


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).upper()


def parse_line(line: str):
    parts = [p.strip() for p in line.split(",")]
    parts = [p for p in parts if p]

    if not parts:
        return None

    name = parts[0]
    number = ""
    size = ""

    if len(parts) >= 2:
        # tenta decidir se o segundo é número ou tamanho
        if parts[1].isdigit():
            number = parts[1]
            if len(parts) >= 3:
                size = parts[2]
        else:
            size = parts[1]
            if len(parts) >= 3 and parts[2].isdigit():
                number = parts[2]

    return normalize_name(name), number, size.strip().upper()


def build_json_from_text(text: str) -> dict:
    orders = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = parse_line(line)
        if not parsed:
            continue
        name, number, size = parsed
        orders.append({
            "Name": name,
            "Nickname": "",
            "Number": number,
            "BloodType": "",
            "Gender": "",
            "ShortSleeve": size,
            "LongSleeve": "",
            "Short": "",
            "Pants": "",
            "Tanktop": "",
            "Vest": ""
        })

    data = {
        "title": "List",
        "order_number": 0,
        "client_name": "",
        "orders": orders
    }
    return data


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
        out = output_dir_var.get().strip()
        if not out:
            out = DEFAULT_OUTPUT_DIR
            output_dir_var.set(out)
        os.makedirs(out, exist_ok=True)
        return out

    def export_json(data: dict, out_dir: str, base_name: str = "List"):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = os.path.join(out_dir, f"{base_name}_{stamp}.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return fp

    def generate_from_text():
        try:
            raw = text_box.get("1.0", "end").strip()
            if not raw:
                messagebox.showwarning(APP_NAME, "Cole uma lista antes de gerar.")
                return
            data = build_json_from_text(raw)
            out_dir = ensure_output_dir()
            fp = export_json(data, out_dir, base_name="PXList")
            status_var.set(f"✅ Exportado: {fp}")
            messagebox.showinfo(APP_NAME, f"Arquivo gerado:\n{fp}")
        except Exception as e:
            status_var.set(f"❌ Erro: {e}")
            messagebox.showerror(APP_NAME, str(e))

    def on_drop(event):
        try:
            raw_path = event.data.strip()
            raw_path = raw_path.strip("{}").strip('"')
            p = Path(raw_path)
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

    tk.Label(frame, text="PXList — cole a lista ou solte um .txt", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    tk.Button(frame, text="Escolher pasta de saída", command=choose_output_dir).pack(anchor="w", pady=(10, 6))

    text_box = tk.Text(frame, height=12, wrap="word")
    text_box.pack(fill="x", pady=(0, 8))

    tk.Button(frame, text="Gerar JSON a partir do texto", command=generate_from_text).pack(pady=(0, 10))

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

    tk.Label(frame, textvariable=status_var, font=("Segoe UI", 9)).pack(pady=(10, 0))

    # DnD funciona dentro do Hub porque o root do Hub é TkinterDnD.Tk
    drop_area.drop_target_register(DND_FILES)
    drop_area.dnd_bind("<<Drop>>", on_drop)

    return frame


def main():
    app = TkinterDnD.Tk()
    app.title(APP_NAME)
    app.geometry("680x520")
    app.resizable(False, False)

    ui = build_ui(app)
    ui.pack(fill="both", expand=True)

    app.mainloop()


if __name__ == "__main__":
    main()
