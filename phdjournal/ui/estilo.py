"""Piezas visuales compartidas por la ficha del feed y la de documentos locales."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

# Los trabajos propios (T1, T2...) rotan colores: son definidos por el usuario
# y pueden ser cuantos quiera.
COLORES_TRABAJO = ["#2e7d32", "#1565c0", "#6a1b9a", "#c62828", "#00838f", "#ef6c00"]


def color_trabajo(clave: str | None) -> str:
    if not clave:
        return "#555"
    digitos = "".join(c for c in clave if c.isdigit())
    i = (int(digitos) - 1) if digitos else 0
    return COLORES_TRABAJO[i % len(COLORES_TRABAJO)]


# Los temas de núcleo se ven; los de soporte, más apagados.
COLOR_D = {
    "D1": "#00695c", "D2": "#00695c", "D3": "#00695c", "D10": "#00695c",
    "D4": "#4527a0", "D5": "#4527a0",
    "D6": "#78909c", "D7": "#78909c", "D8": "#78909c", "D9": "#78909c",
}
COLOR_VEREDICTO = {
    "leer completo": "#2e7d32",
    "hojear": "#ef6c00",
    "solo el abstract": "#757575",
}


def _tarjeta(texto: str, color: str = "#eef2f7", borde: str = "#c8d4e3") -> QLabel:
    lbl = QLabel(texto)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setStyleSheet(
        f"background:{color}; border:1px solid {borde}; border-radius:6px;"
        "padding:10px; font-size:13px;"
    )
    return lbl
