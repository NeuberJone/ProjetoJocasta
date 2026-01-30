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

    if is_adult_size(t) or is_child_size(t) or is_babylook_size(t):
        return True

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

    size = t
    if not (is_adult_size(size) or is_child_size(size) or is_babylook_size(size)):
        raise ValueError(f"Linha {line_no}: tamanho inválido em {tok!r}.")
    return f"1-{size}"


def detect_gender_from_sizes(sizes_normalized: list[str], line_no: int) -> str:
    """
    Gender:
      - C se existir qualquer tamanho infantil (2A..12A)
      - FE se existir qualquer tamanho com BL
      - MA caso contrário
    Erro:
      - Se existir infantil e BL ao mesmo tempo (divergência)
    """
    has_child = False
    has_bl = False

    for s in sizes_normalized:
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
        raise ValueError(f"Linha {line_no}: divergência (infantil + babylook na mesma linha).")

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
      - Primeiro token que tem dígito vira Number (mantém)
      - Tokens que parecem tamanho viram lista de tamanhos (até 6)
      - Outras strings restantes viram: Nickname (primeira) e BloodType (segunda)
    """
    raw = line.strip().replace("\ufeff", "")
    if not raw:
        raise ValueError(f"Linha {line_no}: vazia.")

    parts = [clean_token(p) for p in raw.split(",")]
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

        if (not number) and any(ch.isdigit() for ch in tok):
            number = normalize_spaces(tok)  # mantém como veio
            continue

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
# UI - Checkboxes com ordem + limite
# =========================
class OrderedCheckboxes(tk.Frame):
    """
    Lista de checkboxes onde a ordem de marcação define a sequência.
    Suporta limite de seleção (ex.: precisa marcar exatamente N).
    """
    def __init__(self, parent):
        super().__init__(parent)

        self._selected_keys: list[str] = []
        self._vars: dict[str, tk.IntVar] = {}
        self._labels: dict[str, tk.StringVar] = {}
        self._limit: int | None = None

        title = tk.Label(
            self,
            text="Selecione as peças (a ORDEM que marcar define o mapeamento):",
            font=("Segoe UI", 10, "bold")
        )
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
            text="Dica: a ordem (1)(2)(3) define: TAM1→(1), TAM2→(2), TAM3→(3), ...",
            font=("Segoe UI", 9),
            fg="#444"
        )
        note.pack(anchor="w", pady=(8, 0))

    def set_limit(self, limit: int | None):
        self._limit = limit

    def _relabel(self):
        order_map = {k: i + 1 for i, k in enumerate(self._selected_keys)}
        for key, pt_name in GARMENTS:
            if key in order_map:
                self._labels[key].set(f"{pt_name} ({order_map[key]})")
            else:
                self._labels[key].set(pt_name)

    def _on_toggle(self, key: str):
        checked = bool(self._vars[key].get())

        if checked:
            if self._limit is not None and len(self._selected_keys) >= self._limit:
                # desfaz e avisa
                self._vars[key].set(0)
                messagebox.showerror(APP_NAME, f"Todas as peças necessárias já foram selecionadas ({self._limit}).")
                return

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
# HUB Frame (build_ui)
# =========================
class PXListPlusFrame(tk.Frame):
    """
    Frame para rodar dentro do Hub (Projeto Jocasta).
    O Hub chama build_ui(parent) e coloca o Frame dentro de uma aba.
    """
    def __init__(self, parent):
        super().__init__(parent)

        self.cfg = load_config()
        self.required_count: int | None = None
        self.input_dirty = False

        root = tk.Frame(self, padx=14, pady=14)
        root.pack(fill="both", expand=True)

        tk.Label(
            root,
            text="PXListPlus — gera JSON com mapeamento por ordem de seleção",
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w")

        tk.Label(
            root,
            text=(
                "Entrada (dinâmica, por vírgulas): Nome, Número, TAMs..., Apelido(opcional), Tipo Sanguíneo(opcional)\n"
                "Tamanho: QTY-TAMANHO (ex: 3-G, 5-12A, 2-BLP) ou TAMANHO sozinho (ex: G, 12A, BLP => vira 1-TAM).\n"
                "Fluxo recomendado: 1) Verificar  2) Marcar as peças (na ordem)  3) Gerar JSON.\n"
                "Validação: 0 peças marcadas = erro. TAMs por linha deve ser IGUAL ao nº de peças marcadas (mais ou menos = erro).\n"
                "Qualquer erro bloqueia a geração (não cria arquivo)."
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
        self.ck.pack(fill="x", pady=(0, 8))

        # Mapeamento (ordem atual)
        self.mapping_var = tk.StringVar(value="Mapeamento: — (marque as peças para ver a ordem)")
        tk.Label(root, textvariable=self.mapping_var, font=("Segoe UI", 9), fg="#333").pack(anchor="w", pady=(0, 10))

        # Entrada
        tk.Label(root, text="Cole a lista abaixo (uma pessoa por linha):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.txt_in = tk.Text(root, height=10, wrap="none", font=("Consolas", 10))
        self.txt_in.pack(fill="x", pady=(6, 8))
        self.txt_in.bind("<KeyRelease>", self.on_input_changed)

        # Botões
        btn_row = tk.Frame(root)
        btn_row.pack(fill="x", pady=(0, 10))

        tk.Button(btn_row, text="Verificar", command=self.verify_input).pack(side="right")
        tk.Button(btn_row, text="Gerar JSON", command=self.generate_json).pack(side="right", padx=6)
        tk.Button(btn_row, text="Limpar seleção", command=self.clear_selection).pack(side="right", padx=6)
        tk.Button(btn_row, text="Limpar tudo", command=self.clear_all).pack(side="right", padx=6)

        # Prévia
        self.preview_var = tk.StringVar(value="🔎 Clique em 'Verificar' para analisar a entrada.")
        tk.Label(root, textvariable=self.preview_var, font=("Segoe UI", 9), fg="#333").pack(anchor="w", pady=(0, 6))

        self.txt_preview = tk.Text(root, height=6, wrap="none", font=("Consolas", 9))
        self.txt_preview.pack(fill="x", pady=(0, 10))

        # Erros (copiável)
        err_head = tk.Frame(root)
        err_head.pack(fill="x", pady=(0, 6))

        tk.Label(err_head, text="Erros / avisos:", font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(err_head, text="Copiar erros", command=self.copy_errors).pack(side="right")

        self.txt_errors = tk.Text(root, height=5, wrap="word", font=("Consolas", 9))
        self.txt_errors.pack(fill="both", expand=False, pady=(0, 10))

        # Drag & Drop
        self.drop_area = tk.Label(
            root,
            text="SOLTE AQUI (.txt)",
            font=("Segoe UI", 18, "bold"),
            relief="ridge",
            bd=2,
            width=32,
            height=2
        )
        self.drop_area.pack(pady=6)

        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<Drop>>", self.on_drop)

        # Atualiza mapeamento periodicamente (porque checkbox callback não chama frame diretamente)
        self.after(150, self.refresh_mapping_label)

    # ---------- UI Helpers ----------
    def refresh_mapping_label(self):
        sel = self.ck.get_selected_in_order()
        if not sel:
            self.mapping_var.set("Mapeamento: — (marque as peças para ver a ordem)")
        else:
            # 1→NomePT | 2→NomePT ...
            pt_map = {k: pt for k, pt in GARMENTS}
            parts = [f"{i+1}→{pt_map[k]}" for i, k in enumerate(sel)]
            self.mapping_var.set("Mapeamento: " + " | ".join(parts))

        self.after(150, self.refresh_mapping_label)

    def set_errors_text(self, text: str):
        self.txt_errors.delete("1.0", "end")
        self.txt_errors.insert("1.0", text or "")

    def copy_errors(self):
        text = self.txt_errors.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há erros para copiar.")
            return
        win = self.winfo_toplevel()
        win.clipboard_clear()
        win.clipboard_append(text)
        win.update()

    def mark_dirty(self):
        # invalida verificação anterior
        self.input_dirty = True
        self.required_count = None
        self.ck.set_limit(None)
        self.preview_var.set("⚠️ Entrada alterada. Clique em 'Verificar' novamente.")
        # não apaga prévia automaticamente (ajuda o usuário comparar), mas você pode apagar se quiser:
        # self.txt_preview.delete("1.0", "end")

    def on_input_changed(self, _evt=None):
        # Só marca sujo quando tem alteração real (evento é frequente; simples e suficiente)
        if not self.input_dirty:
            self.mark_dirty()

    # ---------- Actions ----------
    def pick_output_folder(self):
        folder = filedialog.askdirectory(title=f"{APP_NAME} - Escolha a pasta para salvar o JSON")
        if not folder:
            return
        self.output_dir_var.set(folder)
        self.cfg["output_dir"] = folder
        save_config(self.cfg)
        self.status_var.set(f"📁 Pasta de saída: {folder}")

    def clear_selection(self):
        self.ck.clear()
        # seleção limpa não muda a entrada, então não marca dirty
        self.mapping_var.set("Mapeamento: — (marque as peças para ver a ordem)")

    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.ck.clear()
        self.txt_preview.delete("1.0", "end")
        self.set_errors_text("")
        self.preview_var.set("🔎 Clique em 'Verificar' para analisar a entrada.")
        self.required_count = None
        self.ck.set_limit(None)
        self.input_dirty = False

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

            # Entrada mudou => marca dirty e auto-verifica
            self.mark_dirty()
            self.verify_input(auto=True)

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            self.status_var.set(f"❌ Erro: {e}")

    def verify_input(self, auto: bool = False):
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            if not auto:
                messagebox.showwarning(APP_NAME, "Cole uma lista na entrada (ou solte um .txt).")
            self.preview_var.set("⚠️ Sem entrada para verificar.")
            self.txt_preview.delete("1.0", "end")
            self.set_errors_text("")
            self.required_count = None
            self.ck.set_limit(None)
            self.input_dirty = False
            return

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            if not auto:
                messagebox.showwarning(APP_NAME, "A lista está vazia.")
            self.preview_var.set("⚠️ Lista vazia.")
            self.txt_preview.delete("1.0", "end")
            self.set_errors_text("")
            self.required_count = None
            self.ck.set_limit(None)
            self.input_dirty = False
            return

        errors = []
        parsed = []  # (name, number, sizes, nickname, blood)

        for idx, line in enumerate(lines, start=1):
            try:
                name, number, sizes, nickname, blood = parse_line_dynamic(line, idx)

                if not sizes:
                    raise ValueError(f"Linha {idx}: nenhum tamanho encontrado.")

                if len(sizes) > 6:
                    raise ValueError(f"Linha {idx}: mais de 6 tamanhos ({len(sizes)}).")

                # valida divergência de gênero (infantil+BL) já na verificação
                _ = detect_gender_from_sizes(sizes, idx)

                parsed.append((name, number, sizes, nickname, blood))
            except Exception as e:
                errors.append(f"{e}\n  Conteúdo: {line}")

        if errors:
            self.required_count = None
            self.ck.set_limit(None)
            self.txt_preview.delete("1.0", "end")

            # escreve erros no painel + popup (quando não é auto, ou quando você quiser)
            self.set_errors_text("\n\n".join(errors))
            self.preview_var.set(f"❌ Erros: {len(errors)} | Verificação falhou")

            # popup só quando usuário clicou (auto=False)
            if not auto:
                err_text = "\n\n".join(errors[:25])
                more = ""
                if len(errors) > 25:
                    more = f"\n\n... e mais {len(errors) - 25} erro(s)."
                messagebox.showerror(APP_NAME, f"Foram encontrados erros na entrada.\n\n{err_text}{more}")

            self.input_dirty = False
            return

        # Regra do Plus: todas as linhas precisam ter o MESMO número de TAMs
        counts = sorted({len(p[2]) for p in parsed})
        if len(counts) != 1:
            self.required_count = None
            self.ck.set_limit(None)
            self.txt_preview.delete("1.0", "end")

            msg = (
                "Entrada inconsistente: existem linhas com diferentes quantidades de tamanhos.\n"
                f"Quantidades encontradas: {counts}\n\n"
                "Como o PXListPlus exige igualdade exata, corrija a lista para todas terem a mesma quantidade."
            )
            self.set_errors_text(msg)
            self.preview_var.set(f"❌ Quantidades diferentes de TAMs: {counts}")

            if not auto:
                messagebox.showerror(APP_NAME, msg)

            self.input_dirty = False
            return

        required = counts[0]
        self.required_count = required
        self.ck.set_limit(required)
        self.set_errors_text("")

        # Se já tiver mais selecionadas que required, limpa a seleção
        if len(self.ck.get_selected_in_order()) > required:
            self.ck.clear()

        # Prévia estilo Lite (nome, número, tams...)
        preview_lines = []
        for (name, number, sizes, _nickname, _blood) in parsed[:250]:
            cols = [normalize_name(name), normalize_spaces(number)]
            cols.extend(sizes)
            preview_lines.append(",".join(cols))

        self.txt_preview.delete("1.0", "end")
        self.txt_preview.insert("1.0", "\n".join(preview_lines))

        self.preview_var.set(
            f"✅ Verificado: {len(parsed)} linha(s) válida(s) | "
            f"Tamanhos por linha: {required} | "
            f"Marque exatamente: {required} peça(s)."
        )

        self.input_dirty = False

    def generate_json(self):
        # Se a entrada mudou depois da verificação, exige verificar de novo
        if self.input_dirty or self.required_count is None:
            # auto-verifica antes de bloquear
            self.verify_input(auto=True)
            if self.required_count is None:
                messagebox.showwarning(APP_NAME, "Clique em 'Verificar' e corrija a entrada antes de gerar o JSON.")
                return

        selected = self.ck.get_selected_in_order()

        # Regras de validação de seleção
        if len(selected) == 0:
            messagebox.showerror(APP_NAME, "Erro: marque pelo menos 1 peça (a ordem define o mapeamento).")
            return

        if self.required_count is not None and len(selected) != self.required_count:
            messagebox.showerror(
                APP_NAME,
                f"Erro: você deve marcar exatamente {self.required_count} peça(s). Marcadas: {len(selected)}."
            )
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

                # exige igualdade exata
                if len(sizes) != self.required_count:
                    raise ValueError(
                        f"Linha {idx}: quantidade de TAMs ({len(sizes)}) diferente do esperado ({self.required_count})."
                    )

                # gênero + divergência
                gender = detect_gender_from_sizes(sizes, idx)

                # mapa das peças conforme ordem das checkboxes
                garment_map = {k: "" for k, _ in GARMENTS}
                for i, garment_key in enumerate(selected):
                    garment_map[garment_key] = sizes[i]

                orders.append(
                    make_order(
                        normalize_name(name),
                        normalize_spaces(number),
                        gender,
                        normalize_name(nickname),
                        normalize_spaces(blood),
                        garment_map
                    )
                )

            except Exception as e:
                errors.append(f"{e}\n  Conteúdo: {line}")

        # bloqueia se tiver qualquer erro
        if errors:
            self.set_errors_text("\n\n".join(errors))
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
        self.set_errors_text("")
        messagebox.showinfo(APP_NAME, f"JSON gerado:\n{out_path}\n\nRegistros: {len(orders)}")
        self.status_var.set(f"✅ Gerado: {out_path} | Registros: {len(orders)}")


# =========================
# Função exigida pelo Hub
# =========================
def build_ui(parent):
    return PXListPlusFrame(parent)


# =========================
# Execução standalone
# =========================
def main():
    app = TkinterDnD.Tk()
    app.title(APP_NAME)
    app.geometry("860x740")
    app.resizable(False, False)

    try:
        app.iconbitmap(resource_path("pxlist.ico"))
    except Exception:
        pass

    frame = PXListPlusFrame(app)
    frame.pack(fill="both", expand=True)

    app.mainloop()


if __name__ == "__main__":
    main()
