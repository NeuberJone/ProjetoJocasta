from .ui import PXSearchOrdersUI


def build_ui(parent):
    return PXSearchOrdersUI(parent)


__all__ = ["build_ui", "PXSearchOrdersUI"]