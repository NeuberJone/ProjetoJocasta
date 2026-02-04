from __future__ import annotations

import json
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Tuple, Optional


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

# =========================
# Regras de tamanho
# =========================
VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG", "XLGG"
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG"
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

# QTY-TAM (ex: 3-G, 5-12A, 2-BLP)
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")


# =========================
# Config persistente (AppData)
# =========================
def get_config_file() -> str:
    base = os.environ.get("APPDATA") or str(Path.home())
    cfg_dir = Path(base) / "PXList"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return str(cfg_dir / "pxlistplus_config.json")


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


def is_comment_or_empty(line: str) -> bool:
    raw = (line or "").strip()
    return (not raw) or raw.startswith("//")


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
      - Infantil: termina com A => C
      - Babylook: contém BL => FE
      - Senão => MA
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


# =========================
# Comment highlighting (azul)
# =========================
def highlight_comments(text_widget: tk.Text) -> None:
    text_widget.tag_remove("comment", "1.0", "end")
    lines = text_widget.get("1.0", "end").splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("//"):
            text_widget.tag_add("comment", f"{idx}.0", f"{idx}.end")


# =========================
# Modelo de linha parseada
# =========================
@dataclass(frozen=True)
class ParsedRow:
    name: str
    number: str
    pieces: Tuple[str, ...]   # normalizados: "QTY-TAM" ou "" (posicional)
    nickname: str
    blood: str
    gender: str              # MA/FE/C


def detect_k_fast(text: str) -> int:
    """
    Detecta K (quantidade de colunas de peças) de forma rápida.
    K = maior posição (1..6) com token que parece tamanho.
    """
    k = 0
    for line in (text or "").splitlines():
        raw = line.strip().replace("\ufeff", "")
        if not raw or raw.startswith("//"):
            continue
        parts = [p.strip() for p in raw.split(",")]
        for i in range(2, min(len(parts), 2 + 6)):
            if parts[i] and is_size_token(parts[i]):
                k = max(k, (i - 1))
    return k


def parse_input_text_strict(text: str, k: int) -> List[ParsedRow]:
    """
    Parser estrito (para verificar e gerar JSON):
      - Usa K já determinado (se k<=0, calcula e usa)
      - Permite vazios nas peças
      - Não permite gênero misturado na mesma linha
      - Extras: apelido e tipo sanguíneo são posicionais após K
      - Qualquer erro em qualquer linha: ValueError
    """
    if k <= 0:
        k = detect_k_fast(text)
    if k <= 0:
        raise ValueError("Não encontrei nenhuma peça/tamanho válido na lista.")

    errors: List[str] = []
    rows: List[ParsedRow] = []

    for line_no, line in enumerate((text or "").splitlines(), start=1):
        if is_comment_or_empty(line):
            continue

        parts = [p.strip() for p in line.replace("\ufeff", "").split(",")]
        for tok in parts:
            forbid_quotes(line_no, tok)

        while len(parts) < 2 + 6:
            parts.append("")

        name = normalize_name(parts[0])
        number = normalize_text(parts[1])

        pieces_raw = parts[2:2 + k]
        pieces_norm: List[str] = []
        genders_found: set[str] = set()

        for tok in pieces_raw:
            t = tok.strip()
            if not t:
                pieces_norm.append("")
                continue
            try:
                qty, size = parse_qty_and_size(t)
                g = gender_from_size(size)
                genders_found.add(g)
                pieces_norm.append(f"{qty}-{size}")
            except Exception as e:
                errors.append(f"Linha {line_no}: {line.strip()}\n -> Peça inválida: {tok!r} ({e})")

        if not any(pieces_norm):
            errors.append(f"Linha {line_no}: {line.strip()}\n -> Nenhuma peça/tamanho encontrado.")
            continue

        if len(genders_found) > 1:
            errors.append(
                f"Linha {line_no}: {line.strip()}\n -> Gêneros diferentes na mesma linha ({sorted(genders_found)})."
            )
            continue

        gender = next(iter(genders_found)) if genders_found else "MA"

        extras = [x.strip() for x in parts[2 + k:]]
        if len(extras) > 2 and any(x for x in extras[2:]):
            errors.append(
                f"Linha {line_no}: {line.strip()}\n -> Extras demais após as peças (máx 2: apelido e tipo)."
            )
            continue

        nickname = normalize_name(extras[0]) if len(extras) >= 1 and extras[0] else ""
        blood = normalize_text(extras[1]) if len(extras) >= 2 and extras[1] else ""

        rows.append(ParsedRow(
            name=name,
            number=number,
            pieces=tuple(pieces_norm),
            nickname=nickname,
            blood=blood,
            gender=gender
        ))

    if errors:
        raise ValueError("Foram encontrados erros. Nenhum arquivo foi gerado.\n\n" + "\n\n".join(errors))

    rows.sort(key=lambda r: (r.name, r.number))
    return rows


# =========================
# JSON builder
# =========================
PIECES_FIELDS = [
    ("Camiseta (manga curta)", "ShortSleeve"),
    ("Camiseta (manga longa)", "LongSleeve"),
    ("Bermuda", "Short"),
    ("Calça", "Pants"),
    ("Regata", "Tanktop"),
    ("Colete", "Vest"),
]


def make_order(row: ParsedRow, mapping: List[str]) -> dict:
    order = {
        "Name": row.name,
        "Nickname": row.nickname,
        "Number": row.number,
        "BloodType": row.blood,
        "Gender": row.gender,
        "ShortSleeve": "",
        "LongSleeve": "",
        "Short": "",
        "Pants": "",
        "Tanktop": "",
        "Vest": ""
    }
    for i, field in enumerate(mapping):
        if i < len(row.pieces):
            order[field] = row.pieces[i]
    return order


def export_json(orders: List[dict], out_dir: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    fp = os.path.join(out_dir, f"List-{stamp}.json")
    data = dict(BASE_JSON)
    data["orders"] = orders
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return fp


def build_preview_json(orders: List[dict]) -> str:
    data = dict(BASE_JSON)
    data["orders"] = orders
    return json.dumps(data, ensure_ascii=False, indent=4)


# =========================
# UI
# =========================
class PXListPlusFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        cfg = load_config()
        self.output_dir_var = tk.StringVar(value=cfg.get("output_dir", DEFAULT_OUTPUT_DIR))

        self.selected_order: List[str] = []
        self.check_vars: List[tk.BooleanVar] = []

        self.detected_k: int = 0

        # ✅ resultado da verificação (processamento)
        self._verified_rows: Optional[List[ParsedRow]] = None
        self._verified_k: int = 0

        tk.Label(
            self,
            text="PXListPlus — gera JSON com mapeamento por ordem de seleção",
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(10, 6))

        tk.Label(
            self,
            text=("Entrada (vinda do PXTotaList): Nome, Número, peça1..peçaK, (Apelido opcional), (Tipo opcional)\n"
                  "Peças podem estar vazias em algumas linhas (isso é normal). O que não pode é misturar gêneros na mesma linha.\n"
                  "Fluxo: 1) Verificar  2) Marcar as peças na ordem  3) Gerar JSON.\n"
                  "Comentários: linhas começando com // são ignoradas."),
            font=("Segoe UI", 9)
        ).pack(anchor="w", padx=10, pady=(0, 10))

        top_row = tk.Frame(self)
        top_row.pack(fill="x", padx=10)

        tk.Button(top_row, text="Escolher pasta de saída", command=self.pick_output_folder).pack(side="left")
        self.lbl_out = tk.Label(top_row, text=f"Pasta de saída: {self.output_dir_var.get()}", font=("Segoe UI", 9))
        self.lbl_out.pack(side="right")

        box = tk.LabelFrame(self, text="Selecione as peças (a ORDEM que marcar define o mapeamento):")
        box.pack(fill="x", padx=10, pady=10)

        for label, field in PIECES_FIELDS:
            var = tk.BooleanVar(value=False)
            self.check_vars.append(var)
            cb = tk.Checkbutton(
                box,
                text=label,
                variable=var,
                command=lambda f=field, v=var: self.on_toggle_piece(f, v)
            )
            cb.pack(anchor="w")

        self.map_label = tk.Label(self, text="Mapeamento: —", font=("Segoe UI", 9, "bold"))
        self.map_label.pack(anchor="w", padx=10, pady=(0, 8))

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Cole a lista abaixo (uma pessoa por linha):").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none", height=14, font=("Consolas", 10))
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Prévia do JSON (após Verificar):").pack(anchor="w")
        self.txt_preview = tk.Text(right, wrap="none", height=14, font=("Consolas", 10))
        self.txt_preview.pack(fill="both", expand=True, pady=(6, 0))

        self.txt_in.tag_configure("comment", foreground="#1f6fd2")
        self.txt_in.bind("<KeyRelease>", lambda e: self.on_input_changed())
        self.txt_in.bind("<Control-v>", lambda e: self.after(1, self.on_input_changed))

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Limpar tudo", command=self.clear_all).pack(side="left")
        tk.Button(btns, text="Limpar seleção", command=self.clear_selection).pack(side="left", padx=6)

        tk.Button(btns, text="Gerar JSON", command=self.on_generate).pack(side="right")
        tk.Button(btns, text="Verificar", command=self.on_verify).pack(side="right", padx=6)

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(0, 10))

        self.txt_in.insert(
            "1.0",
            ",,GG\n"
            "JOÃO,5,G,M\n"
            "JUACA,,PP,,,JUSÉ\n"
            "LUCAS,21,M,,O-\n"
            "\n"
            "// Exemplo: linhas podem ter vazios nas peças.\n"
        )
        self.on_input_changed()

    # ---------------- Core behavior
    def on_input_changed(self):
        # qualquer alteração na entrada invalida a verificação
        self._verified_rows = None
        self._verified_k = 0
        self.txt_preview.delete("1.0", "end")

        raw = self.txt_in.get("1.0", "end").strip("\n")
        highlight_comments(self.txt_in)

        self.detected_k = detect_k_fast(raw)
        self.update_mapping_label()

        # se já tinha seleção e agora k diminuiu, corta e avisa
        if self.detected_k > 0 and len(self.selected_order) > self.detected_k:
            # desfaz excedentes
            keep = self.selected_order[:self.detected_k]
            remove = set(self.selected_order[self.detected_k:])
            self.selected_order = keep
            for (label, field), var in zip(PIECES_FIELDS, self.check_vars):
                if field in remove:
                    var.set(False)
            messagebox.showerror(
                APP_NAME,
                f"A lista detectou apenas {self.detected_k} peça(s). Selecione no máximo {self.detected_k}."
            )

        if self.detected_k <= 0:
            self.status_var.set("⚠️ Nenhuma peça detectada (cole a lista).")
        else:
            self.status_var.set(
                f"ℹ️ Detectadas: {self.detected_k} peça(s). Clique em Verificar para processar e gerar a prévia."
            )

    def on_toggle_piece(self, field: str, var: tk.BooleanVar):
        # invalida verificação se mexer na seleção (pra forçar consistência)
        self._verified_rows = None
        self._verified_k = 0
        self.txt_preview.delete("1.0", "end")

        # bloqueio imediato de excesso
        if var.get():
            if self.detected_k > 0 and len(self.selected_order) >= self.detected_k:
                var.set(False)
                messagebox.showerror(
                    APP_NAME,
                    f"Você já selecionou todas as {self.detected_k} peça(s) detectadas.\n"
                    "Não é permitido marcar mais do que isso."
                )
                return
            if field not in self.selected_order:
                self.selected_order.append(field)
        else:
            if field in self.selected_order:
                self.selected_order.remove(field)

        self.update_mapping_label()
        self.status_var.set("ℹ️ Seleção alterada. Clique em Verificar novamente.")

    def update_mapping_label(self):
        suffix = f" | Detectadas: {self.detected_k} peça(s)" if self.detected_k > 0 else " | Detectadas: 0 peça(s)"
        if not self.selected_order:
            self.map_label.config(text="Mapeamento: — (nenhuma peça selecionada)" + suffix)
            return

        pretty = []
        for i, field in enumerate(self.selected_order, start=1):
            label = next((lbl for lbl, f in PIECES_FIELDS if f == field), field)
            pretty.append(f"TAM{i}→{label}")

        self.map_label.config(text="Mapeamento: " + " | ".join(pretty) + suffix)

    # ---------------- Verify / Generate
    def on_verify(self):
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        if self.detected_k <= 0:
            messagebox.showerror(APP_NAME, "Não encontrei nenhuma peça/tamanho válido na lista.")
            return

        if len(self.selected_order) != self.detected_k:
            messagebox.showerror(
                APP_NAME,
                f"Seleção inválida: detectei {self.detected_k} peça(s), "
                f"mas você marcou {len(self.selected_order)}.\n"
                "Marque exatamente a mesma quantidade detectada."
            )
            return

        mapping = self.selected_order[:self.detected_k]

        try:
            rows = parse_input_text_strict(raw, self.detected_k)
            orders = [make_order(r, mapping) for r in rows]
            preview = build_preview_json(orders)

            self.txt_preview.delete("1.0", "end")
            self.txt_preview.insert("1.0", preview)

            self._verified_rows = rows
            self._verified_k = self.detected_k
            self.status_var.set(f"✅ Verificado: {len(rows)} registro(s). Agora pode gerar o JSON.")
        except Exception as e:
            self._verified_rows = None
            self._verified_k = 0
            self.status_var.set("❌ Erros encontrados. Corrija a entrada.")
            messagebox.showerror(APP_NAME, str(e))

    def on_generate(self):
        # só gera se verificado
        if not self._verified_rows or self._verified_k <= 0:
            messagebox.showerror(APP_NAME, "Você precisa clicar em Verificar e passar sem erros antes de gerar o JSON.")
            return

        # garante consistência: seleção e detectado no momento
        if self.detected_k != self._verified_k:
            messagebox.showerror(APP_NAME, "A entrada mudou após a verificação. Clique em Verificar novamente.")
            return
        if len(self.selected_order) != self._verified_k:
            messagebox.showerror(APP_NAME, "A seleção mudou após a verificação. Clique em Verificar novamente.")
            return

        mapping = self.selected_order[:self._verified_k]
        try:
            orders = [make_order(r, mapping) for r in self._verified_rows]
            out_dir = self.ensure_output_dir()
            fp = export_json(orders, out_dir)
            self.status_var.set(f"✅ JSON gerado: {fp} | Registros: {len(orders)}")
            messagebox.showinfo(APP_NAME, f"JSON gerado:\n{fp}\n\nRegistros: {len(orders)}")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    # ---------------- UI helpers
    def pick_output_folder(self):
        folder = filedialog.askdirectory(title="PXListPlus - Escolha a pasta para salvar o JSON")
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

    def clear_selection(self):
        self.selected_order.clear()
        for v in self.check_vars:
            v.set(False)
        self.update_mapping_label()
        self._verified_rows = None
        self._verified_k = 0
        self.txt_preview.delete("1.0", "end")
        self.status_var.set("ℹ️ Seleção limpa. Clique em Verificar.")

    def clear_all(self):
        self.txt_in.delete("1.0", "end")
        self.txt_preview.delete("1.0", "end")
        self.selected_order.clear()
        for v in self.check_vars:
            v.set(False)
        self.detected_k = 0
        self._verified_rows = None
        self._verified_k = 0
        self.update_mapping_label()
        self.status_var.set("")
        highlight_comments(self.txt_in)


def build_ui(parent):
    return PXListPlusFrame(parent)


def main() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1250x720")
    root.minsize(1050, 620)

    ui = build_ui(root)
    ui.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
