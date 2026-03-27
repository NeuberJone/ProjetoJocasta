from .ui import PXPrintLogsUI

def build_ui(parent):
    return PXPrintLogsUI(parent)

__all__ = ["build_ui", "PXPrintLogsUI"]