"""Iconos dibujados en código.

Se pintan con QPainter en vez de arrastrar archivos binarios al repositorio.
El icono es una hoja con una onda de sonido encima: papers que se escuchan.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

AZUL = QColor("#1e5aa8")
AZUL_CLARO = QColor("#4a90d9")
PAPEL = QColor("#f7f7f5")
ACENTO = QColor("#e8a33d")


def _pintar(tam: int, con_punto: bool = False) -> QPixmap:
    px = QPixmap(tam, tam)
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = tam / 32.0

    # Hoja
    hoja = QRectF(7 * u, 4 * u, 18 * u, 24 * u)
    p.setBrush(PAPEL)
    p.setPen(QPen(AZUL, 1.6 * u))
    p.drawRoundedRect(hoja, 2 * u, 2 * u)

    # Renglones
    p.setPen(QPen(AZUL_CLARO, 1.2 * u, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i, ancho in enumerate((11, 11, 7)):
        y = (10 + i * 4) * u
        p.drawLine(QPointF(10 * u, y), QPointF((10 + ancho) * u, y))

    # Onda de sonido
    p.setPen(QPen(AZUL, 2.0 * u, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    onda = QPainterPath()
    onda.moveTo(11 * u, 24 * u)
    onda.lineTo(11 * u, 24 * u)
    for x, alto in ((14, 3.5), (17, 6.0), (20, 2.5)):
        p.drawLine(QPointF(x * u, (24 - alto) * u), QPointF(x * u, (24 + alto) * u))

    if con_punto:
        p.setBrush(ACENTO)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(20 * u, 2 * u, 10 * u, 10 * u))

    p.end()
    return px


def icono_app(con_punto: bool = False) -> QIcon:
    icono = QIcon()
    for tam in (16, 24, 32, 48, 64, 128, 256):
        icono.addPixmap(_pintar(tam, con_punto))
    return icono


def guardar_ico(destino) -> None:
    """Exporta un .ico para el acceso directo del menú Inicio."""
    _pintar(256).save(str(destino), "ICO")
