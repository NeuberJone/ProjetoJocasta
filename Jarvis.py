import os
import sys
import json
import re
import requests
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog

# Drag & Drop (opcional)
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False


APP_NAME = "Jarvis"
APP_TITLE = "Jarvis"
DEFAULT_JSON_SUBFOLDER = "JSON"


def resource_path(rel_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.abspath("."), rel_path)


FIELD_LABELS = {
    "Name": "Nome",
    "Number": "Número",
    "ShortSleeve": "Manga Curta",
    "LongSleeve": "Manga Longa",
    "Short": "Short",
    "Pants": "Calça",
    "Tanktop": "Regata",
    "Vest": "Colete",
    "Nickname": "Apelido",
    "BloodType": "Tipo Sanguíneo",
}
FIELD_ORDER = ["Name", "Number", "ShortSleeve", "LongSleeve", "Short", "Pants", "Tanktop", "Vest", "Nickname", "BloodType"]
MANDATORY_FIELDS = {"Name", "Number"}


def normalize_str(x):
    if x is None:
        return ""
    return str(x).replace("\r", "").replace("\n", " ").strip()


def decide_effective_fields(orders):
    present = set()
    for entry in orders:
        for key in FIELD_ORDER:
            if key in MANDATORY_FIELDS:
                continue
            if normalize_str(entry.get(key, "")) != "":
                present.add(key)
    return [k for k in FIELD_ORDER if (k in MANDATORY_FIELDS) or (k in present)]


def format_lines(data):
    orders = data.get("orders", [])
    if not isinstance(orders, list):
        raise ValueError("Campo 'orders' inválido (não é lista).")

    eff = decide_effective_fields(orders)
    lines = []

    for e in orders:
        row_values = [normalize_str(e.get(k, "")) for k in eff]

        # Expande "qtd-tamanho" (ex: 2-M)
        expanded_rows = []
        for idx, val in enumerate(row_values):
            m = re.match(r"^(\d+)-(.+)$", val)
            if m:
                qtd = int(m.group(1))
                base = m.group(2)
                for _ in range(qtd):
                    new_row = row_values.copy()
                    new_row[idx] = base
                    expanded_rows.append(",".join(new_row))
                break
        else:
            expanded_rows.append(",".join(row_values))

        lines.extend(expanded_rows)

    return lines, eff


def copy_to_clipboard(root, text):
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


def do_convert_json_data(root, data: dict, origem: str, status_setter=None):
    lines, fields = format_lines(data)
    out = "\n".join(lines)

    copy_to_clipboard(root, out)

    msg = [
        f"Origem: {origem}",
        f"Linhas geradas: {len(lines)}",
        "Colunas usadas: " + ", ".join(FIELD_LABELS.get(f, f) for f in fields),
        "✅ Texto copiado para a área de transferência."
    ]
    if status_setter:
        status_setter(out + "\n\n" + "\n".join(msg))

    messagebox.showinfo("JSON → Clipboard", "\n".join(msg))


def baixar_por_linhas(linhas, pasta_saida: str):
    headers = {"User-Agent": "Jarvis/1.0 (+local)"}
    os.makedirs(pasta_saida, exist_ok=True)

    total = 0
    erros = []

    for i, linha in enumerate(linhas):
        s = linha.strip()
        if s.startswith("JSON: "):
            url = s.replace("JSON: ", "").strip()
            try:
                r = requests.get(url, headers=headers, timeout=20)
                r.raise_for_status()
                try:
                    dados = r.json()
                except Exception as je:
                    raise ValueError(f"Resposta não é JSON válido: {je}")

                nome = str(dados.get("title", f"pedido_{i+1}")).replace(" ", "_").upper()
                out_path = os.path.join(pasta_saida, f"{nome}.json")
                with open(out_path, "w", encoding="utf-8") as fo:
                    json.dump(dados, fo, ensure_ascii=False, indent=4)

                total += 1
            except Exception as e:
                erros.append(f"{url}\n{e}")

    return total, erros


def exibir_resultado_baixa(total, erros, status_setter=None, destino="JSON"):
    msg = f"{total} arquivo(s) salvos com sucesso na pasta '{destino}'!"
    if erros:
        msg += f"\n\n{len(erros)} erro(s) ocorreram. (Detalhes no console)"
        print("Erros ao baixar JSONs:")
        for e in erros:
            print("-", e)

    if status_setter:
        status_setter(msg)

    messagebox.showinfo("TXT → JSON", msg)


def _clean_drop_path(raw: str) -> Path:
    raw = raw.strip().strip("{}").strip()
    if "}" in raw and "{" in raw:
        raw = raw.split("} {")[0].strip("{}").strip()
    return Path(raw.strip('"'))


def handle_file(root, file_path: str, status_setter=None):
    try:
        p = _clean_drop_path(file_path)
        if not p.exists() or not p.is_file():
            raise FileNotFoundError("Arquivo não encontrado.")

        ext = p.suffix.lower()

        if ext == ".json":
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            do_convert_json_data(root, data, p.name, status_setter)

        elif ext == ".txt":
            pasta = os.path.join(str(p.parent), DEFAULT_JSON_SUBFOLDER)
            with p.open("r", encoding="utf-8") as f:
                linhas = f.readlines()
            total, erros = baixar_por_linhas(linhas, pasta)
            exibir_resultado_baixa(total, erros, status_setter, destino=DEFAULT_JSON_SUBFOLDER)

        else:
            raise ValueError("Formato não suportado. Use .txt ou .json.")

    except Exception as e:
        if status_setter:
            status_setter(f"Erro: {e}")
        messagebox.showerror("Erro", str(e))


def auto_process_pasted(root, raw_text: str, status_setter=None):
    text = raw_text.strip()
    if not text:
        messagebox.showwarning(APP_NAME, "Cole algum conteúdo no campo de texto.")
        return

    # JSON colado
    if text[0] in "{[":
        try:
            data = json.loads(text)
        except Exception as e:
            messagebox.showerror("Erro", f"Não consegui interpretar o texto como JSON:\n{e}")
            return
        do_convert_json_data(root, data, "Conteúdo colado", status_setter)
        return

    # TXT colado
    target_dir = filedialog.askdirectory(title="Escolha a pasta onde será criada a subpasta 'JSON'")
    if not target_dir:
        return

    pasta_saida = os.path.join(target_dir, DEFAULT_JSON_SUBFOLDER)
    linhas = text.splitlines()
    total, erros = baixar_por_linhas(linhas, pasta_saida)
    exibir_resultado_baixa(total, erros, status_setter, destino=DEFAULT_JSON_SUBFOLDER)


def build_ui(parent):
    root = parent.winfo_toplevel()

    outer = tk.Frame(parent)
    outer.pack(fill="both", expand=True, padx=10, pady=10)

    # Topo: instrução + botões (padrão PX)
    top = tk.Frame(outer)
    top.pack(fill="x")

    tk.Label(
        top,
        text="Jarvis — cole um TXT com linhas 'JSON: <url>' ou abra um .txt/.json",
        font=("Segoe UI", 11, "bold"),
    ).pack(side="left")

    btns = tk.Frame(top)
    btns.pack(side="right")

    # Centro: entrada
    mid = tk.Frame(outer)
    mid.pack(fill="both", expand=True, pady=(10, 10))

    tk.Label(mid, text="Entrada (cole aqui) — ou selecione um arquivo:").pack(anchor="w")
    text_box = tk.Text(mid, wrap="word", height=10)
    text_box.pack(fill="both", expand=False, pady=(6, 10))

    tk.Label(mid, text="Saída / status:").pack(anchor="w")
    status = tk.Text(mid, wrap="word", height=10, state="disabled")
    status.pack(fill="both", expand=True, pady=(6, 0))

    def status_set(text: str):
        status.config(state="normal")
        status.delete("1.0", "end")
        status.insert("1.0", text)
        status.config(state="disabled")

    def select_file():
        p = filedialog.askopenfilename(
            title="Selecione .txt ou .json",
            filetypes=[("TXT/JSON", "*.txt *.json"), ("TXT", "*.txt"), ("JSON", "*.json")]
        )
        if p:
            handle_file(root, p, status_set)

    def process_paste():
        auto_process_pasted(root, text_box.get("1.0", "end"), status_set)

    def clear_all():
        text_box.delete("1.0", "end")
        status_set("")

    tk.Button(btns, text="Selecionar arquivo...", command=select_file).pack(side="left", padx=(0, 6))
    tk.Button(btns, text="Processar", command=process_paste).pack(side="left", padx=(0, 6))
    tk.Button(btns, text="Limpar", command=clear_all).pack(side="left")

    # Área DnD (opcional) — visual padrão simples
    drop = tk.Label(
        outer,
        text="SOLTE AQUI (.TXT ou .JSON)",
        relief="ridge",
        bd=2,
        height=2,
        font=("Segoe UI", 12, "bold"),
    )
    drop.pack(fill="x", pady=(10, 0))

    if DND_AVAILABLE:
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", lambda e: handle_file(root, e.data, status_set))
    else:
        # não força erro, só informa
        status_set("Dica: instale 'tkinterdnd2' para habilitar arrastar-e-soltar.")

    return outer


def main():
    Root = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = Root()
    root.title(APP_TITLE)
    root.geometry("980x680")
    root.minsize(900, 600)

    try:
        root.iconbitmap(resource_path("jarvis.ico"))
    except Exception:
        pass

    ui = build_ui(root)
    ui.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
