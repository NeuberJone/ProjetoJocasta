from __future__ import annotations

import re
import tkinter as tk
import tkinter.ttk as ttk
from dataclasses import dataclass
from tkinter import messagebox
from typing import List

APP_NAME = "PXListLite"

VALID_SIZES = {
    # Adulto
    "PP", "P", "M", "G", "GG", "XG", "XGG", "XXGG",
    # Babylook
    "BLPP", "BLP", "BLM", "BLG", "BLGG", "BLXGG", "BLXXGG",
    # Infantil
    "2A", "3A", "4A", "5A", "6A", "7A", "8A", "9A",
    "10A", "11A", "12A", "14A", "16A",
}

QTY_SIZE_RE = re.compile(r"^\s*(\d+)\s*-\s*([A-Za-z0-9]+)\s*$", re.IGNORECASE)
FORBIDDEN_QUOTE_RE = re.compile(r"[\"']")


# =========================
# Comment highlighting
# =========================
def highlight_comments(text_widget: tk.Text) -> None:
    text_widget.tag_remove("comment", "1.0", "end")

    lines = text_widget.get("1.0", "end").splitlines()
    for idx, line in enumerate(lines, start=1):
        if line.strip().startswith("//"):
            start = f"{idx}.0"
            end = f"{idx}.end"
            text_widget.tag_add("comment", start, end)


# =========================
# Helpers
# =========================
def _clean_token(s: str) -> str:
    return (s or "").strip()


def _upper(s: str) -> str:
    return _clean_token(s).upper()


def _forbid_quotes(line_no: int, tok: str) -> None:
    if tok and FORBIDDEN_QUOTE_RE.search(tok):
        raise ValueError(
            f"Linha {line_no}: não use aspas para vazio (\"\"), token: {tok!r}"
        )


def _is_size_value(tok: str) -> bool:
    t = _upper(tok)
    if not t:
        return False
    if t in VALID_SIZES:
        return True
    m = QTY_SIZE_RE.match(t)
    return bool(m and _upper(m.group(2)) in VALID_SIZES)


def detect_multi_piece_input(text: str) -> bool:
    """
    Detecta se a entrada parece conter MAIS DE UMA peça/tamanho em alguma linha.
    Comentários (// ...) são ignorados.
    """
    for line in (text or "").splitlines():
        raw = line.strip().replace("\ufeff", "")
        if not raw or raw.startswith("//"):
            continue

        parts = [_clean_token(p) for p in raw.split(",")]
        if len(parts) == 1:
            continue

        size_count = 0
        for tok in parts[2:]:
            if _is_size_value(tok):
                size_count += 1
                if size_count >= 2:
                    return True

    return False


@dataclass(frozen=True)
class Row:
    name: str
    number: str
    size: str  # UMA peça apenas
    nickname: str
    blood: str


def parse_line_single_size(line: str, line_no: int) -> Row | None:
    """
    Modo 1 tamanho (1 peça):

    Aceita:
      1) "NOME, NUMERO, TAM"
      2) "NOME, , TAM, APELIDO, SANGUE"
      3) ", 10, G"
      4) "GG"  (tamanho sozinho) -> name="" number="" size="GG"

    Comentários:
      - Linhas começando com // são ignoradas no process_text (não chegam aqui).

    Regras:
      - TAMANHO é obrigatório
      - Se encontrar mais de 1 tamanho na mesma linha => erro
      - "" (aspas) é proibido como vazio
      - Extras são POSICIONAIS:
          col4 = apelido (pode ser vazio)
          col5 = tipo sanguíneo (pode ser vazio)
        Qualquer coisa além disso com conteúdo => erro
    """
    raw = (line or "").rstrip("\n").replace("\ufeff", "")
    if not raw.strip():
        return None

    parts = [_clean_token(p) for p in raw.split(",")]
    for tok in parts:
        _forbid_quotes(line_no, tok)

    # Caso especial: só um token (ex: "GG")
    if len(parts) == 1:
        only = _clean_token(parts[0])
        if only and _is_size_value(only):
            return Row(name="", number="", size=_upper(only), nickname="", blood="")
        raise ValueError(f"Linha {line_no}: tamanho obrigatório. Valor recebido: {only!r}")

    # Garante pelo menos 3 colunas: nome, numero, tamanho
    while len(parts) < 3:
        parts.append("")

    name = _upper(parts[0])
    number = _clean_token(parts[1])
    size_raw = _clean_token(parts[2])

    if not size_raw:
        raise ValueError(f"Linha {line_no}: tamanho vazio (não permitido).")

    # Conta quantos tamanhos existem na linha (a partir do 3º campo em diante)
    size_count = 0
    for tok in parts[2:]:
        if _is_size_value(tok):
            size_count += 1
    if size_count >= 2:
        raise ValueError(
            f"Linha {line_no}: foram encontrados {size_count} tamanhos. No Lite é permitido apenas 1."
        )

    size = _upper(size_raw)
    if not _is_size_value(size):
        raise ValueError(f"Linha {line_no}: tamanho inválido: {size_raw!r}")

    # ✅ Extras POSICIONAIS (não ignorar vazio)
    extras_raw = parts[3:] if len(parts) > 3 else []
    extras_raw = [_clean_token(x) for x in extras_raw]

    if len(extras_raw) > 2 and any(x.strip() for x in extras_raw[2:]):
        raise ValueError(
            f"Linha {line_no}: extras demais após o tamanho (máx 2: apelido e tipo)."
        )

    e1 = extras_raw[0] if len(extras_raw) >= 1 else ""
    e2 = extras_raw[1] if len(extras_raw) >= 2 else ""

    nickname = _upper(e1) if e1 else ""
    blood = _upper(e2) if e2 else ""

    return Row(
        name=name,
        number=_upper(number) if number else "",
        size=size,
        nickname=nickname,
        blood=blood
    )


def process_text(text: str) -> str:
    rows: List[Row] = []
    for i, line in enumerate((text or "").splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("//"):
            continue
        r = parse_line_single_size(line, i)
        if r:
            rows.append(r)

    # Ordena por (nome, número)
    rows.sort(key=lambda r: (r.name, r.number))

    # Colunas de extras:
    # Se existir sangue em qualquer linha, força coluna apelido pra manter alinhamento.
    has_blood = any(r.blood for r in rows)
    has_nick = any(r.nickname for r in rows) or has_blood

    out_lines: List[str] = []
    for r in rows:
        cols = [r.name, r.number, r.size]
        if has_nick:
            cols.append(r.nickname)
        if has_blood:
            cols.append(r.blood)
        out_lines.append(",".join(cols))

    return "\n".join(out_lines)


def open_totalist_with_input(parent: tk.Misc, raw_text: str) -> None:
    """
    Dentro do Hub: seleciona a aba PXTotaList e preenche a entrada.
    Fora do Hub: fallback abre uma janela separada.
    """
    root = parent.winfo_toplevel()

    # 1) Hub: tenta achar o Notebook
    nb = getattr(root, "nb", None)
    if isinstance(nb, ttk.Notebook):
        target_tab_id = None
        for tab_id in nb.tabs():
            try:
                if nb.tab(tab_id, "text") == "PXTotaList":
                    target_tab_id = tab_id
                    break
            except Exception:
                continue

        if target_tab_id:
            nb.select(target_tab_id)

            tab_widget = root.nametowidget(target_tab_id)

            def _walk(w: tk.Widget):
                yield w
                for c in w.winfo_children():
                    yield from _walk(c)

            for w in _walk(tab_widget):
                if hasattr(w, "txt_in"):
                    txt = getattr(w, "txt_in", None)
                    if isinstance(txt, tk.Text):
                        txt.delete("1.0", "end")
                        txt.insert("1.0", raw_text)
                        txt.focus_set()
                        # aplica highlight na aba destino se tiver tag configurada lá
                        try:
                            highlight_comments(txt)
                        except Exception:
                            pass
                        return

            messagebox.showwarning(
                APP_NAME,
                "Mudei para a aba PXTotaList, mas não consegui preencher a entrada automaticamente."
            )
            return

    # 2) Fallback: abre janela fora do Hub
    try:
        import PXTotaList  # type: ignore
    except Exception as e:
        messagebox.showerror(
            APP_NAME,
            "Não consegui abrir o PXTotaList.\n"
            "Verifique se o arquivo 'PXTotaList.py' está na mesma pasta.\n\n"
            f"Detalhe: {e}"
        )
        return

    win = tk.Toplevel(root)
    win.title("PXTotaList")

    if hasattr(PXTotaList, "build_ui"):
        frame = PXTotaList.build_ui(win)
        frame.pack(fill="both", expand=True)

        if hasattr(frame, "txt_in"):
            txt = getattr(frame, "txt_in", None)
            if isinstance(txt, tk.Text):
                txt.delete("1.0", "end")
                txt.insert("1.0", raw_text)
                txt.focus_set()
    else:
        tk.Label(win, text="PXTotaList carregado, mas não encontrei build_ui(parent).").pack(padx=10, pady=10)


# -----------------------------
# UI + suporte ao Hub
# -----------------------------
class PXListLiteFrame(tk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(
            top,
            text="PXList Lite — 1 tamanho por linha (para manga curta no PXList)",
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left")

        btns = tk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(btns, text="Processar", command=self.on_process).pack(side="right")
        tk.Button(btns, text="Copiar saída", command=self.copy_output).pack(side="right", padx=6)
        tk.Button(btns, text="Limpar", command=self.clear_all).pack(side="right")

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        tk.Label(left, text="Entrada: Nome, Número, Tamanho, (Apelido), (Tipo)").pack(anchor="w")
        self.txt_in = tk.Text(left, wrap="none")
        self.txt_in.pack(fill="both", expand=True, pady=(6, 0))

        tk.Label(right, text="Saída (copiada automaticamente):").pack(anchor="w")
        self.txt_out = tk.Text(right, wrap="none")
        self.txt_out.pack(fill="both", expand=True, pady=(6, 0))

        # Tag azul para comentários
        self.txt_in.tag_configure("comment", foreground="#1f6fd2")

        # Atualiza highlight ao digitar/colar
        self.txt_in.bind("<KeyRelease>", lambda e: highlight_comments(self.txt_in))
        self.txt_in.bind("<Control-v>", lambda e: self.after(1, highlight_comments, self.txt_in))

        self.txt_in.insert(
            "1.0",
            "GG\n"
            "JOÃO,5,G\n"
            "JUACA,,PP,JUSÉ\n"
            "LUCAS,21,M,,O-\n"
            "\n"
            "// Se colar multi-peça (ex: JOAO,5,G,M) o Lite vai sugerir abrir o TotaList.\n"
        )
        highlight_comments(self.txt_in)

    def on_process(self) -> None:
        raw = self.txt_in.get("1.0", "end").strip("\n")
        if not raw.strip():
            messagebox.showwarning(APP_NAME, "Cole uma lista na entrada.")
            return

        if detect_multi_piece_input(raw):
            resp = messagebox.askyesno(
                APP_NAME,
                "Detectei mais de um tamanho/peça em pelo menos uma linha.\n\n"
                "O PXListLite trabalha com APENAS 1 tamanho por linha.\n"
                "Deseja mudar para o PXTotaList com essa mesma entrada?"
            )
            if resp:
                open_totalist_with_input(self, raw)
            return

        try:
            out = process_text(raw)
            self.txt_out.delete("1.0", "end")
            self.txt_out.insert("1.0", out)

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
        highlight_comments(self.txt_in)


def build_ui(parent):
    return PXListLiteFrame(parent)


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
