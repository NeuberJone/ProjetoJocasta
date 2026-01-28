from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import List, Tuple


APP_NAME = "PXTotaList"

# -----------------------------
# Regras de identificação
# -----------------------------
# Adulto (PP ao XXGG) conforme seu padrão atual do PXList
ADULT_SIZES = {"PP", "P", "M", "G", "GG", "XGG", "XXGG"}

# Infantil: 2A..12A
CHILD_SIZE_RE = re.compile(r"^(?:[2-9]|1[0-2])A$", re.IGNORECASE)

# Campo com quantidade: "2-G", "10-BLP", "3-12A"
QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)

# Token proibido para "vazio"
FORBIDDEN_EMPTY = {'""', "''"}


def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _is_forbidden(tok: str) -> bool:
    t = _clean_token(tok)
    if not t:
        return False
    if t in FORBIDDEN_EMPTY:
        return True
    # se tiver aspas em qualquer lugar, a gente considera inválido (pra não aceitar "" disfarçado)
    return ('"' in t) or ("'" in t)


def _is_child_size(size: str) -> bool:
    return bool(CHILD_SIZE_RE.fullmatch(size))


def _is_adult_size(size: str) -> bool:
    return size in ADULT_SIZES


def _is_babylook_size(size: str) -> bool:
    # Babylook: BL + tamanho adulto (BLP, BLM, BLG, BLGG, BLPP, BLXGG, BLXXGG...)
    s = size.upper()
    if not s.startswith("BL"):
        return False
    suffix = s[2:]
    return suffix in ADULT_SIZES


def _is_size_token(tok: str) -> bool:
    """
    Tamanho válido se:
      - adulto: PP, P, M, G, GG, XGG, XXGG
      - infantil: 2A..12A
      - babylook: BL + (adult size)
      - qty-size: QTY-TAMANHO onde TAMANHO é válido
    """
    t = _upper(tok)
    if not t:
        return False

    # puro
    if _is_adult_size(t) or _is_child_size(t) or _is_babylook_size(t):
        return True

    # qty-size
    m = QTY_SIZE_RE.match(t)
    if not m:
        return False
    size = _upper(m.group(2))
    return _is_adult_size(size) or _is_child_size(size) or _is_babylook_size(size)


def _normalize_size_token(tok: str) -> str:
    """
    Normaliza para SEMPRE "QTY-SIZE".
    Aceita:
      - "G"      -> "1-G"
      - "BLP"    -> "1-BLP"
      - "12A"    -> "1-12A"
      - "2-G"    -> "2-G"
      - " 2 - g" -> "2-G"
    """
    t = _upper(tok)
    if not t:
        raise ValueError("Tamanho vazio.")

    # qty-size
    m = QTY_SIZE_RE.match(t)
    if m:
        qty = int(m.group(1))
        size = _upper(m.group(2))
        if qty <= 0:
            raise ValueError("Quantidade inválida (<= 0).")
        if not (_is_adult_size(size) or _is_child_size(size) or _is_babylook_size(size)):
            raise ValueError("Tamanho inválido.")
        return f"{qty}-{size}"

    # size sozinho
    size = t
    if not (_is_adult_size(size) or _is_child_size(size) or _is_babylook_size(size)):
        raise ValueError("Tamanho inválido.")
    return f"1-{size}"


def _is_number(tok: str) -> bool:
    """
    Número (para o PXTotaList) deve aceitar alfanumérico tipo 7X1.
    Regra: tem pelo menos 1 dígito.
    """
    t = _clean_token(tok)
    return bool(t) and any(ch.isdigit() for ch in t)


@dataclass(frozen=True)
class ParsedRow:
    name: str
    number: str
    tams: Tuple[str, ...]  # TAMs normalizados como QTY-SIZE (1..6)
    s2: str  # apelido (opcional)
    s3: str  # tipo sanguíneo (opcional)


def parse_line(line: str) -> ParsedRow | None:
    """
    Regra (igual a ideia do PXListLite, mas agora com até 6 TAMs):
      - separar por vírgula (preservando vazios como tokens vazios)
      - NÃO aceita token "" (aspas)
      - classificar tokens em: STRING, NÚMERO, TAM
      - 1ª STRING => NOME
      - 1º NÚMERO => NÚMERO (aceita 7X1)
      - TAMs em ordem => TAM1..TAM6 (obrigatório ter pelo menos 1)
      - demais STRINGS => STRING2, STRING3 (em ordem)
    """
    raw = line.strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]  # preserva vazios (",,")

    name = ""
    number = ""
    tams: List[str] = []
    extra_strings: List[str] = []

    for tok in parts:
        if _is_forbidden(tok):
            raise ValueError(f'Token inválido (não use aspas para vazio): {tok}')

        t = _clean_token(tok)
        if not t:
            continue  # vazios OK (",,") — apenas ignorados na classificação

        up = _upper(t)

        if _is_size_token(up):
            tams.append(_normalize_size_token(up))  # sempre QTY-SIZE
            continue

        if _is_number(t) and not number:
            # preserva como veio (apenas trim e upper)
            number = up
            continue

        # string comum
        if not name:
            name = up
        else:
            extra_strings.append(up)

    if not tams:
        raise ValueError(f"Sem TAM reconhecido: {raw}")

    if len(tams) > 6:
        raise ValueError(f"Mais de 6 TAMs na linha: {raw}")

    s2 = extra_strings[0] if len(extra_strings) >= 1 else ""
    s3 = extra_strings[1] if len(extra_strings) >= 2 else ""

    return ParsedRow(
        name=name,
        number=number,
        tams=tuple(tams),
        s2=s2,
        s3=s3,
    )


def build_output(rows: List[ParsedRow]) -> str:
    """
    Ordem final dinâmica:
      NOME,NÚMERO,TAM1..TAMk,STRING2,STRING3
    - k = maior quantidade de TAMs encontrada em qualquer linha (até 6)
    - STRING2/3 entram após o último TAM
    - Só inclui STRING2 se existir em qualquer linha
    - Só inclui STRING3 se existir em qualquer linha
    """
    if not rows:
        return ""

    max_tams = max(len(r.tams) for r in rows)
    has_s2 = any(r.s2 != "" for r in rows)
    has_s3 = any(r.s3 != "" for r in rows)

    out_lines: List[str] = []
    for r in rows:
        cols: List[str] = [r.name, r.number]

        tam_list = list(r.tams) + [""] * (max_tams - len(r.tams))
        cols.extend(tam_list)

        if has_s2:
            cols.append(r.s2)
        if has_s3:
            cols.append(r.s3)

        out_lines.append(",".join(cols))

    return "\n".join(out_lines)


def process_text(text: str) -> str:
    parsed: List[ParsedRow] = []

    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = parse_line(line)
            if row:
                parsed.append(row)
        except ValueError as e:
            raise ValueError(f"Linha {i}: {e}") from None

    # Ordena por NOME e depois por NÚMERO (ambos string)
    parsed.sort(key=lambda r: (r.name, r.number))
    return build_output(parsed)


# -----------------------------
# UI (Lite)
# -----------------------------
class PXTotaListFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        # Topo
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(
            top,
            text="PXTotaList — organiza e devolve o texto (CAIXA ALTA) — até 6 TAMs",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        # Botões
        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="right")

        # Corpo (2 colunas)
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada (separado por vírgula):").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none")
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Saída (organizada):").pack(anchor="w")
        self.txt_out = tk.Text(right, wrap="none")
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        # Exemplo
        self.txt_in.insert(
            "1.0",
            "G,JÃO,10\n"
            "JOÃO,5,G,M\n"
            "MANEL,PP\n"
            "JUACA,JUSÉ,PP,BLP,12A\n"
            "ASTROGILDA,7X1,BLG,O+,NICK\n"
        )

    def on_process(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        try:
            out = process_text(raw)
            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", out)

            # ✅ Copia automaticamente, sem mensagem
            win = self.txt_out.winfo_toplevel()
            win.clipboard_clear()
            win.clipboard_append(out)
            win.update()

        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def copy_output(self) -> None:
        text = self.txt_out.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning(APP_NAME, "Não há saída para copiar.")
            return

        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def clear_all(self) -> None:
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")


def build_ui(parent):
    """Para Hub: o Hub chama build_ui(parent) e adiciona o frame numa aba."""
    return PXTotaListFrame(parent)


def main() -> None:
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("1000x600")
    root.minsize(900, 520)

    ui = build_ui(root)
    ui.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
