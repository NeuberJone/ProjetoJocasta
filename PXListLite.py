from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import List, Tuple


APP_NAME = "PXListLite"

# -----------------------------
# Regras de identificação
# -----------------------------
VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG",
    # Infantil com A
    "2A", "4A", "6A", "8A", "10A", "12A", "14A", "16A",
}

# aceita "2-M", "10-BLP", "3-4A" etc.
QTY_SIZE_RE = re.compile(r"^\s*\d+\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)


def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _is_number(tok: str) -> bool:
    t = _clean_token(tok)
    return t.isdigit()  # preserva "01"


def _is_size(tok: str) -> bool:
    t = _upper(tok)
    if not t:
        return False
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    return bool(m and _upper(m.group(1)) in VALID_SIZES)


@dataclass(frozen=True)
class ParsedRow:
    name: str
    number: str
    tams: Tuple[str, ...]     # TAMs encontrados (1..4)
    s2: str                  # STRING2 (opcional)
    s3: str                  # STRING3 (opcional)


def parse_line(line: str) -> ParsedRow | None:
    """
    Regra:
    - separar por vírgula (preservando vazios como tokens vazios)
    - classificar tokens em: STRING, NÚMERO, TAM
    - 1ª STRING => NOME
    - 1º NÚMERO => NÚMERO
    - TAMs em ordem => TAM1..TAM4 (obrigatório ter pelo menos 1)
    - demais STRINGS (que não são NOME) => STRING2, STRING3 em ordem
    """
    raw = line.strip()
    if not raw:
        return None

    parts = [_clean_token(p) for p in raw.split(",")]  # preserva vazios (",,")
    # remove espaços, mas NÃO remove tokens vazios (importante pra estrutura)
    # porém, para classificação, tokens vazios são ignorados.

    name = ""
    number = ""
    tams: List[str] = []
    extra_strings: List[str] = []

    for tok in parts:
        t = _clean_token(tok)
        if not t:
            continue

        up = _upper(t)

        if _is_size(up):
            # mantém o formato original em caixa alta
            tams.append(up)
            continue

        if _is_number(t) and not number:
            number = up
            continue

        # string comum
        if not name:
            name = up
        else:
            extra_strings.append(up)

    # obrigatórios: NOME, NÚMERO e TAM1 "existem", mas valor pode ser vazio.
    # Aqui, seguindo sua regra mais recente: NOME pode vir vazio na lista, mas a coluna existe.
    # Se não apareceu nenhuma STRING (name), aceitamos name="".
    # Se não apareceu número, aceitamos number="".
    if not tams:
        raise ValueError(f"Sem TAM1 reconhecido: {raw}")

    # limita a 4 TAMs
    if len(tams) > 4:
        raise ValueError(f"Mais de 4 TAMs na linha: {raw}")

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
    - k = maior quantidade de TAMs encontrada em qualquer linha
    - STRING2/3 entram logo após o último TAM existente (k)
    - Só inclui coluna STRING2 se existir em qualquer linha
    - Só inclui coluna STRING3 se existir em qualquer linha
    """
    if not rows:
        return ""

    max_tams = max(len(r.tams) for r in rows)
    has_s2 = any(r.s2 != "" for r in rows)
    has_s3 = any(r.s3 != "" for r in rows)

    # cabeçalho (opcional) – deixo fácil habilitar no futuro
    # headers = ["NOME", "NÚMERO"] + [f"TAM{i}" for i in range(1, max_tams + 1)]
    # if has_s2: headers.append("STRING2")
    # if has_s3: headers.append("STRING3")

    out_lines: List[str] = []

    for r in rows:
        cols: List[str] = [r.name, r.number]

        # TAMs (preenche vazios para bater com max_tams)
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
            # Erro com contexto de linha (mais amigável)
            raise ValueError(f"Linha {i}: {e}") from None

    # Ordena por NOME e depois por NÚMERO (ambos string)
    parsed.sort(key=lambda r: (r.name, r.number))
    return build_output(parsed)


# -----------------------------
# UI (Lite) + suporte a Hub
# -----------------------------
class PXListLiteFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        # Topo
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(
            top,
            text="PXList Lite — organiza e devolve o texto (CAIXA ALTA)",
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
            "JUACA,JUSÉ,PP\n"
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
            #messagebox.showinfo(APP_NAME, "OK! Lista organizada.")

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
        #messagebox.showinfo(APP_NAME, "Saída copiada para a área de transferência.")

    def clear_all(self) -> None:
        self.txt_in.delete("1.0", "end")
        self.txt_out.delete("1.0", "end")


def build_ui(parent):
    """
    Para o Hub:
    - o Hub chama build_ui(parent) e adiciona o frame na aba.
    """
    frame = PXListLiteFrame(parent)
    return frame


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
