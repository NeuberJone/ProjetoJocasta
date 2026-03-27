from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from typing import List, Optional

from core.version import APP_VERSION
from core.format import fmt_m
from core.printlogs_db import save_export_transactional, OrderRow

from .config import load_cfg, save_cfg
from .models import Job, Block
from .parser import parse_log_txt, build_blocks
from .paths import MODULE_NAME, pdf_dir, jpg_dir, temp_dir, sanitize_filename, versioned_path
from .exporters import export_pdf, pdf_first_page_to_jpg_scaled

try:
    from tkinterdnd2 import DND_FILES  # type: ignore
    _HAS_DND = True
except Exception:
    DND_FILES = None
    _HAS_DND = False

try:
    from reportlab.pdfgen import canvas
except Exception:
    canvas = None

try:
    import fitz
    _HAS_PYMUPDF = True
except Exception:
    _HAS_PYMUPDF = False

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


class PXPrintLogsUI(ttk.Frame):
    # cola aqui a classe atual, trocando imports e chamadas
    ...