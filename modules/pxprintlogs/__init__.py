from .ui import PXPrintLogsUI

def build_ui(parent, *, preload=None):
    return PXPrintLogsUI(parent, preload=preload)

__all__ = ["build_ui", "PXPrintLogsUI"]