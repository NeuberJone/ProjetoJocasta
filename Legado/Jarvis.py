import os
import sys
import json
import requests
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import font as tkfont  # fontes seguras

# ---- Drag & Drop (opcional) ----
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

import random

# Título aleatório "zuero"
APP_TITLES = [
    "Mano Jarvis — já resolvo essas parada aí",
    "Jarvis Malandro — deixa comigo que eu arrumo",
    "Ô loco bicho, é o Jarvis arrumando seus arquivos!",
    "Jarvis — transformando txt véio em json bonitão",
    "Mano Jarvis — JSON no grau, CSV na mão",
    "Jarvis raiz — sem bug, só gambi",
    "Jarvis — clipa esse CSV e vai pro abraço",
    "Jarvis — hoje é dia de resolver treta de arquivo",
    "Jarvis — mais rápido que CTRL+C + CTRL+V",
    "Jarvis — eu sou inevitável... e formatador também",
    "Jarvis — os txt pira, os json chora",
]
APP_TITLE = random.choice(APP_TITLES)

def resource_path(rel_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.abspath("."), rel_path)

# =========================
# Conversão JSON -> linhas CSV
# =========================
FIELD_LABELS = {
    "Name": "Nome", "Number": "Número",
    "ShortSleeve": "Manga Curta", "LongSleeve": "Manga Longa",
    "Short": "Short", "Pants": "Calça",
    "Tanktop": "Regata", "Vest": "Colete",
    "Nickname": "Apelido", "BloodType": "Tipo Sanguíneo",
}
FIELD_ORDER = ["Name","Number","ShortSleeve","LongSleeve","Short","Pants","Tanktop","Vest","Nickname","BloodType"]
MANDATORY_FIELDS = {"Name","Number"}

def normalize_str(x):
    if x is None: return ""
    return str(x).replace("\r","").replace("\n"," ").strip()

def decide_effective_fields(orders):
    present = set()
    for entry in orders:
        for key in FIELD_ORDER:
            if key in MANDATORY_FIELDS: continue
            if normalize_str(entry.get(key,"")) != "": present.add(key)
    return [k for k in FIELD_ORDER if (k in MANDATORY_FIELDS) or (k in present)]

import re

def format_lines(data):
    orders = data.get("orders", [])
    if not isinstance(orders, list):
        raise ValueError("Campo 'orders' inválido (não é lista).")
    eff = decide_effective_fields(orders)

    lines = []
    for e in orders:
        row_values = [normalize_str(e.get(k,"")) for k in eff]

        # procura padrões N-VALOR nos campos
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
            # nenhum campo tinha N-VALOR, adiciona a linha normal
            expanded_rows.append(",".join(row_values))

        lines.extend(expanded_rows)
    return lines, eff

def copy_to_clipboard(root, text):
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()

def do_convert_json_data(root, data: dict, origem: str, status_widget=None):
    lines, fields = format_lines(data)
    out = "\n".join(lines)
    copy_to_clipboard(root, out)
    msg = [
        f"Origem: {origem}",
        f"Linhas geradas: {len(lines)}",
        "Colunas usadas: " + ", ".join(FIELD_LABELS.get(f,f) for f in fields),
        "✅ Texto copiado para a área de transferência."
    ]
    if status_widget:
        status_widget.config(state="normal"); status_widget.delete("1.0","end")
        status_widget.insert("end", out + "\n\n" + "\n".join(msg))
        status_widget.config(state="disabled")
    messagebox.showinfo("JSON → Clipboard", "\n".join(msg))

# =========================
# Baixar JSONs a partir de TXT
# =========================
def baixar_por_linhas(linhas, pasta_saida: str):
    headers = {"User-Agent": "Jarvis/1.0 (+https://local.app)"}
    os.makedirs(pasta_saida, exist_ok=True)
    total, erros = 0, []
    for i, linha in enumerate(linhas):
        s = linha.strip()
        if s.startswith("JSON: "):
            url = s.replace("JSON: ","").strip()
            try:
                r = requests.get(url, headers=headers, timeout=20)
                r.raise_for_status()
                try:
                    dados = r.json()
                except Exception as je:
                    raise ValueError(f"Resposta não é JSON válido: {je}")
                nome = str(dados.get("title", f"pedido_{i+1}")).replace(" ","_").upper()
                with open(os.path.join(pasta_saida, f"{nome}.json"), "w", encoding="utf-8") as fo:
                    json.dump(dados, fo, ensure_ascii=False, indent=4)
                total += 1
            except Exception as e:
                erros.append(f"{url}\n{e}")
    return total, erros

def exibir_resultado_baixa(total, erros, status_widget=None, destino="JSON"):
    msg = f"{total} arquivo(s) salvos com sucesso na pasta '{destino}'!"
    if erros:
        msg += f"\n\n{len(erros)} erro(s) ocorreram. Veja detalhes no console."
        print("Erros ao baixar JSONs:")
        for e in erros: print("-", e)
    if status_widget:
        status_widget.config(state="normal"); status_widget.delete("1.0","end")
        status_widget.insert("end", msg); status_widget.config(state="disabled")
    messagebox.showinfo("TXT → JSON", msg)

# =========================
# Roteamento de arquivo
# =========================
def _clean_drop_path(raw: str) -> Path:
    raw = raw.strip().strip("{}").strip()
    if "}" in raw and "{" in raw: raw = raw.split("} {")[0].strip("{}").strip()
    return Path(raw.strip('"'))

def handle_file(root, file_path: str, status_widget=None):
    try:
        p = _clean_drop_path(file_path)
        if not p.exists() or not p.is_file(): raise FileNotFoundError("Arquivo não encontrado.")
        ext = p.suffix.lower()
        if ext == ".json":
            with p.open("r", encoding="utf-8") as f: data = json.load(f)
            do_convert_json_data(root, data, p.name, status_widget)
        elif ext == ".txt":
            pasta = os.path.join(str(p.parent), "JSON")
            with p.open("r", encoding="utf-8") as f: linhas = f.readlines()
            total, erros = baixar_por_linhas(linhas, pasta)
            exibir_resultado_baixa(total, erros, status_widget, destino="JSON")
        else:
            raise ValueError("Formato não suportado. Use .txt ou .json.")
    except Exception as e:
        if status_widget:
            status_widget.config(state="normal"); status_widget.delete("1.0","end")
            status_widget.insert("end", f"Erro: {e}"); status_widget.config(state="disabled")
        messagebox.showerror("Erro", str(e))

def _status(widget, text):
    if widget:
        widget.config(state="normal"); widget.delete("1.0","end")
        widget.insert("end", text); widget.config(state="disabled")

# =========================
# Auto-detecção do TEXTO colado
# =========================
def auto_process_pasted(root, raw_text: str, status_widget=None):
    text = raw_text.strip()
    if not text:
        messagebox.showwarning("Aviso", "Cole algum conteúdo no campo de texto.")
        return
    if text[0] in "{[":  # JSON
        try:
            data = json.loads(text)
        except Exception as e:
            messagebox.showerror("Erro", f"Não consegui interpretar o texto como JSON:\n{e}")
            return
        do_convert_json_data(root, data, "Conteúdo colado", status_widget)
        return
    # TXT com linhas "JSON: ..."
    target_dir = filedialog.askdirectory(title="Escolha a pasta onde será criada a subpasta 'JSON'")
    if not target_dir:
        return
    pasta_saida = os.path.join(target_dir, "JSON")
    linhas = text.splitlines()
    total, erros = baixar_por_linhas(linhas, pasta_saida)
    exibir_resultado_baixa(total, erros, status_widget, destino="JSON")

# =========================
# Temas (claro/escuro) e estilo
# =========================
THEMES = {
    "dark": {
        "BG": "#0b1220", "PANEL": "#111827", "ACCENT": "#43b7ff",
        "ACCENT2": "#2563eb", "TEXT": "#e6f0ff", "MUTED": "#93a4bd",
        "BORDER": "#1f2937", "ENTRY": "#0f172a", "SEL": "#1e3a8a"
    },
    "light": {
        "BG": "#f5f7fb", "PANEL": "#ffffff", "ACCENT": "#2563eb",
        "ACCENT2": "#1d4ed8", "TEXT": "#0b1220", "MUTED": "#4b5563",
        "BORDER": "#d1d5db", "ENTRY": "#ffffff", "SEL": "#93c5fd"
    }
}
CURRENT_THEME = {"name": "dark"}  # começa no escuro

def theme_colors():
    return THEMES[CURRENT_THEME["name"]]

def apply_base_fonts(root):
    # Fonte base segura (named font)
    try:
        base_font = tkfont.Font(root, family="Segoe UI", size=10)
    except Exception:
        base_font = tkfont.nametofont("TkDefaultFont")
        base_font.configure(size=10)
    root.option_add("*Font", base_font)

def style_text_widget(w: tk.Text):
    C = theme_colors()
    w.configure(
        bg=C["ENTRY"], fg=C["TEXT"], insertbackground=C["ACCENT"],
        selectbackground=C["SEL"], selectforeground=C["TEXT"],
        relief="solid", bd=1, highlightthickness=0, padx=6, pady=6,
        wrap="word"
    )

def style_box_label(lbl: tk.Label):
    C = theme_colors()
    lbl.configure(
        bg=C["PANEL"], fg=C["TEXT"], bd=1, relief="solid",
        padx=10, pady=8, justify="center", wraplength=1200
    )

def style_button_primary(btn: tk.Button):
    C = theme_colors()
    btn.configure(bg=C["ACCENT2"], fg=theme_colors()["TEXT"], activebackground=C["ACCENT2"],
                  activeforeground=theme_colors()["TEXT"], relief="flat", padx=14, pady=6, bd=0)

def style_button_outline(btn: tk.Button):
    C = theme_colors()
    btn.configure(bg=C["PANEL"], fg=C["TEXT"], activebackground=C["PANEL"],
                  activeforeground=C["TEXT"], relief="solid", bd=1, highlightthickness=0,
                  padx=12, pady=6, highlightbackground=C["BORDER"])

def restyle_all(root, refs):
    """Reaplica tema nos widgets existentes."""
    C = theme_colors()
    root.configure(bg=C["BG"])
    refs["outer"].configure(bg=C["BG"])
    refs["bottom"].configure(bg=C["BG"])
    refs["right_btns"].configure(bg=C["BG"])

    # labels
    style_box_label(refs["instr"])
    refs["title_lbl"].configure(bg=C["BG"], fg=C["ACCENT"])

    # text widgets
    style_text_widget(refs["text_box"])
    style_text_widget(refs["status"])

    # buttons
    style_button_outline(refs["btn_clear"])
    style_button_outline(refs["btn_select"])
    style_button_primary(refs["btn_process"])

def toggle_theme(root, refs, btn_toggle):
    CURRENT_THEME["name"] = "light" if CURRENT_THEME["name"] == "dark" else "dark"
    restyle_all(root, refs)
    btn_toggle.configure(text=f"Tema: {'Claro' if CURRENT_THEME['name']=='light' else 'Escuro'}")

# =========================
# UI (redimensionável com grid)
# =========================
def build_ui():
    Root = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = Root()
    root.title(APP_TITLE)
    root.geometry("1060x760")
    root.minsize(880, 600)
    root.resizable(True, True)
    try:  # ícone
        root.iconbitmap(resource_path("jarvis.ico"))
    except Exception:
        pass

    apply_base_fonts(root)

    # Paleta inicial
    restyle_bg = THEMES[CURRENT_THEME["name"]]["BG"]
    root.configure(bg=restyle_bg)

    # ===== Outer container (grid) =====
    outer = tk.Frame(root, bg=restyle_bg)
    outer.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

    # permitir expansão
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    # linhas do outer
    outer.grid_columnconfigure(0, weight=1)
    for r, wt in [(0,0), (1,0), (2,3), (3,2), (4,0)]:  # instr, title, text_box, status, bottom
        outer.grid_rowconfigure(r, weight=wt)

    # Instruções (row 0)
    instr = tk.Label(
        outer,
        text=("Arraste e solte um arquivo .txt ou .json — ou clique em 'Selecionar arquivo…'.\n\n"
              "• TXT  → baixa os JSONs para a pasta /JSON/ ao lado do TXT (ou na pasta escolhida quando colado)\n"
              "• JSON → copia as linhas CSV para a área de transferência"),
        justify="center"
    )
    instr.grid(row=0, column=0, sticky="ew", pady=(0,8))

    # Título acima da área de colagem (row 1)
    try:
        title_font = tkfont.Font(root, family="Segoe UI Semibold", size=16)
    except Exception:
        title_font = tkfont.Font(root, family="Segoe UI", size=16, weight="bold")
    title_lbl = tk.Label(outer, text="Cole o texto aqui ↓", font=title_font)
    title_lbl.grid(row=1, column=0, sticky="w", pady=(2,4))

    # Caixa de texto (row 2)
    text_box = tk.Text(outer)
    text_box.grid(row=2, column=0, sticky="nsew", pady=(0,8))

    # Área de resultados (row 3)
    status = tk.Text(outer, state="disabled")
    status.grid(row=3, column=0, sticky="nsew", pady=(0,8))

    # Rodapé com botões (row 4)
    bottom = tk.Frame(outer)
    bottom.grid(row=4, column=0, sticky="ew")
    bottom.grid_columnconfigure(0, weight=1)  # esquerda
    bottom.grid_columnconfigure(1, weight=0)  # centro (toggle)
    bottom.grid_columnconfigure(2, weight=0)  # direita (btns)

    # Esq: Limpar
    btn_clear = tk.Button(bottom, text="Limpar área de texto",
                          command=lambda: (text_box.delete("1.0","end"), _status(status, "")))
    btn_clear.grid(row=0, column=0, sticky="w")

    # Centro: Toggle tema
    btn_toggle = tk.Button(bottom, text="Tema: Escuro")  # texto será ajustado no restyle
    btn_toggle.grid(row=0, column=1, padx=10)

    # Dir: Select + Process
    right_btns = tk.Frame(bottom)
    right_btns.grid(row=0, column=2, sticky="e")
    btn_select = tk.Button(
        right_btns, text="Selecionar arquivo...",
        command=lambda: (
            (lambda p: handle_file(root, p, status) if p else None)(
                filedialog.askopenfilename(
                    title="Selecione .txt ou .json",
                    filetypes=[("TXT/JSON","*.txt *.json"), ("TXT","*.txt"), ("JSON","*.json")]
                )
            )
        )
    )
    btn_select.pack(side="left", padx=(0,8))
    btn_process = tk.Button(
        right_btns, text="Processar",
        command=lambda: auto_process_pasted(root, text_box.get("1.0","end"), status)
    )
    btn_process.pack(side="left")

    # DnD nas instruções
    if DND_AVAILABLE:
        instr.drop_target_register(DND_FILES)
        instr.dnd_bind("<<Drop>>", lambda e: handle_file(root, e.data, status))
    else:
        _status(status, "Dica: instale 'tkinterdnd2' para arrastar-e-soltar. Use 'Selecionar arquivo…' por enquanto.")

    # Referências para re-estilizar
    refs = {
        "outer": outer, "instr": instr, "title_lbl": title_lbl,
        "text_box": text_box, "status": status,
        "bottom": bottom, "right_btns": right_btns,
        "btn_clear": btn_clear, "btn_select": btn_select, "btn_process": btn_process
    }

    # Aplicar tema inicial e ligar o toggle
    restyle_all(root, refs)
    btn_toggle.configure(
        command=lambda: toggle_theme(root, refs, btn_toggle),
        text=f"Tema: {'Escuro' if CURRENT_THEME['name']=='dark' else 'Claro'}"
    )

    return root

def main():
    root = build_ui()
    root.mainloop()

if __name__ == "__main__":
    main()
