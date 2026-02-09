from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.version import __version__
from core.config import (
    load_config as load_pxcore_config,
    save_config as save_pxcore_config,
    verify_dev_password,
    set_dev_password,
)

# Root precisa ser TkinterDnD.Tk para drag & drop
try:
    from tkinterdnd2 import TkinterDnD  # type: ignore
    RootBase = TkinterDnD.Tk
except Exception:
    RootBase = tk.Tk


APP_NAME = "JocastaHub"


# =========================
# Hub config (prefs do Hub)
# =========================
def get_hub_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.json"
    return Path.home() / ".config" / APP_NAME / "config.json"


def load_hub_config() -> dict:
    path = get_hub_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_hub_config(cfg: dict) -> None:
    path = get_hub_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _safe_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception as e:
        return e


# =========================
# Main App
# =========================
class JocastaHub(RootBase):
    def __init__(self) -> None:
        # PXCore config (cria dirs e config automaticamente)
        try:
            self.px_cfg = load_pxcore_config()
        except Exception as e:
            self.px_cfg = None
            messagebox.showwarning(
                "PXCore",
                f"Falha ao carregar configurações do PXCore.\n\n{type(e).__name__}: {e}",
            )

        super().__init__()

        self.title(f"Projeto Jocasta v{__version__}")
        self.geometry("1100x720")
        self.minsize(980, 600)

        # Hub prefs
        self.hub_cfg = load_hub_config()

        # Notebook
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # Fluxos (display_name, module_name)
        self.FLOWS: dict[str, list[tuple[str, str]]] = {
            "SISBolt": [
                ("PXFlow", "modules.PXFlow"),
                ("PXComposer", "modules.PXComposer"),
            ],
            "Power Duplicate": [
                ("PXDupe", "modules.PXDupe"),
            ],
            "Impressão": [
                ("PXPrintLogs", "modules.PXPrintLogs"),
                ("PXPrint", "modules.PXPrint"),
            ],
            "Utilitários": [
                ("PXOrderList", "modules.PXOrderList"),
                ("PXBridge", "modules.PXBridge"),
            ],
            "Legado": [
                ("PXListLite", "modules.PXListLite"),
                ("PXTotaList", "modules.PXTotaList"),
                ("PXList", "modules.PXList"),
                ("PXListPlus", "modules.PXListPlus"),
                ("PXSort", "modules.PXSort"),
                ("PXSortLite", "modules.PXSortLite"),
            ],
        }

        # Menu
        self._build_menu()

        # fluxo inicial
        visible = self.get_visible_flows()
        self.current_flow = self.hub_cfg.get("default_flow", "SISBolt")
        if self.current_flow not in visible:
            self.current_flow = next(iter(visible.keys()))

        self.load_flow(self.current_flow)

    # =========================
    # Dev mode visibility
    # =========================
    def is_dev_mode(self) -> bool:
        return bool(getattr(self.px_cfg, "dev_mode_enabled", False))

    def get_visible_flows(self) -> dict[str, list[tuple[str, str]]]:
        if self.is_dev_mode():
            return self.FLOWS

        flows = dict(self.FLOWS)
        flows.pop("Legado", None)
        return flows

    # =========================
    # Menu
    # =========================
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        # Fluxos
        menu_fluxos = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fluxos de Trabalho", menu=menu_fluxos)

        for flow_name in self.get_visible_flows().keys():
            menu_fluxos.add_command(
                label=flow_name,
                command=lambda fn=flow_name: self.load_flow(fn),
            )

        menu_fluxos.add_separator()
        menu_fluxos.add_command(
            label="Definir fluxo atual como padrão",
            command=self.set_default_workflow,
        )
        menu_fluxos.add_command(
            label="Recarregar fluxo atual",
            command=self.reload_current_flow,
        )

        # Configurações
        menu_config = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Configurações", menu=menu_config)
        menu_config.add_command(label="Abrir Configurações", command=self.open_settings)
        menu_config.add_separator()
        menu_config.add_command(label="Abrir Pasta do PXCore", command=self.open_pxcore_folder)

        self.config(menu=menubar)

    # =========================
    # Settings / PXCore
    # =========================
    def open_pxcore_folder(self) -> None:
        try:
            from core.paths import open_in_explorer

            base_dir = getattr(self.px_cfg, "base_dir", None)
            if not base_dir:
                messagebox.showerror("PXCore", "Diretório base não encontrado.")
                return

            open_in_explorer(Path(str(base_dir)))
        except Exception as e:
            messagebox.showerror(
                "Configurações",
                f"Não foi possível abrir a pasta.\n\n{type(e).__name__}: {e}",
            )

    def _prompt_new_password(self) -> str | None:
        p1 = simpledialog.askstring("Modo Dev", "Defina uma senha para o Modo Dev:", show="*",parent=self)
        if not p1:
            return None
        p2 = simpledialog.askstring("Modo Dev", "Confirme a senha:", show="*",parent=self)
        if p2 != p1:
            messagebox.showerror("Modo Dev", "As senhas não coincidem.",parent=self)
            return None
        return p1

    def _enable_dev_mode_with_password(self) -> bool:
        """
        Ativa o modo dev pedindo senha.
        Se não existir senha ainda, permite criar (primeira configuração).
        """
        if self.px_cfg is None:
            messagebox.showerror("PXCore", "Config do PXCore não carregou.")
            return False

        has_hash = bool(getattr(self.px_cfg, "dev_password_hash", ""))

        if not has_hash:
            if messagebox.askyesno(
                "Modo Dev",
                "Nenhuma senha do Modo Dev foi configurada ainda.\n\nDeseja criar uma senha agora?",
            ):
                new_pass = self._prompt_new_password()
                if not new_pass:
                    return False
                set_dev_password(self.px_cfg, new_pass)
            else:
                return False

        pwd = simpledialog.askstring("Modo Dev", "Digite a senha do Modo Dev:", show="*",parent=self)
        if pwd is None:
            return False

        if not verify_dev_password(self.px_cfg, pwd):
            messagebox.showerror("Modo Dev", "Senha incorreta.")
            return False

        self.px_cfg.dev_mode_enabled = True
        save_pxcore_config(self.px_cfg)
        return True

    def open_settings(self) -> None:
        if self.px_cfg is None:
            messagebox.showerror("PXCore", "Config do PXCore não carregou.")
            return

        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("520x300")
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        # Base dir
        ttk.Label(frm, text="Diretório base do PXCore:").pack(anchor="w")
        base_var = tk.StringVar(value=str(getattr(self.px_cfg, "base_dir", "")))
        ttk.Entry(frm, textvariable=base_var, state="readonly").pack(fill="x", pady=(4, 8))

        ttk.Button(frm, text="📁 Abrir pasta", command=self.open_pxcore_folder).pack(anchor="w", pady=(0, 12))

        # Dev mode checkbox (com senha)
        dev_var = tk.BooleanVar(value=self.is_dev_mode())

        def on_toggle_dev() -> None:
            if dev_var.get():
                ok = self._enable_dev_mode_with_password()
                if not ok:
                    dev_var.set(False)
                    return
            else:
                # desativar não pede senha
                self.px_cfg.dev_mode_enabled = False
                save_pxcore_config(self.px_cfg)

            messagebox.showinfo("Modo Dev", "Reinicie o aplicativo para aplicar as alterações.")
            win.destroy()

        ttk.Checkbutton(
            frm,
            text="Ativar Modo Dev (requer senha)",
            variable=dev_var,
            command=on_toggle_dev,
        ).pack(anchor="w")

        ttk.Separator(frm).pack(fill="x", pady=12)
        ttk.Label(frm, text="(O Modo Dev libera módulos e opções avançadas.)").pack(anchor="w")

    # =========================
    # Hub prefs
    # =========================
    def set_default_workflow(self) -> None:
        self.hub_cfg["default_flow"] = self.current_flow
        save_hub_config(self.hub_cfg)
        messagebox.showinfo("Projeto Jocasta", f"Fluxo '{self.current_flow}' definido como padrão.")

    # =========================
    # Flow handling
    # =========================
    def reload_current_flow(self) -> None:
        self.load_flow(self.current_flow)

    def load_flow(self, flow_name: str) -> None:
        flows = self.get_visible_flows()
        if flow_name not in flows:
            messagebox.showerror("Projeto Jocasta", f"Fluxo desconhecido: {flow_name}")
            return

        self.current_flow = flow_name
        self._clear_tabs()

        for title, module_name in flows[flow_name]:
            self._add_tab(title, module_name)

        self.title(f"Projeto Jocasta v{__version__} — {flow_name}")

    def _clear_tabs(self) -> None:
        for tab_id in self.nb.tabs():
            self.nb.forget(tab_id)

    def _add_tab(self, title: str, module_name: str) -> None:
        tab = ttk.Frame(self.nb)
        tab.pack(fill="both", expand=True)
        self.nb.add(tab, text=title)

        mod = _safe_import(module_name)
        if isinstance(mod, Exception):
            self._render_error(tab, f"Falha ao importar {module_name}:\n\n{type(mod).__name__}: {mod}")
            return

        build_ui = getattr(mod, "build_ui", None)
        if not callable(build_ui):
            self._render_error(tab, f"O módulo {module_name} não possui build_ui(parent).")
            return

        try:
            ui = build_ui(tab)
            if isinstance(ui, tk.Widget):
                ui.pack(fill="both", expand=True)
        except Exception as e:
            self._render_error(tab, f"Falha ao montar UI de {module_name}:\n\n{type(e).__name__}: {e}")

    def _render_error(self, parent: ttk.Frame, text: str) -> None:
        t = tk.Text(parent, wrap="word")
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=10, pady=10)


def main() -> None:
    JocastaHub().mainloop()


if __name__ == "__main__":
    main()
