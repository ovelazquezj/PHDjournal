"""Lector de PDF embebido.

Muestra el paper completo a la izquierda y, a la derecha, la lista de
secciones detectadas. Cada sección se puede resumir y escuchar por separado,
que es la forma práctica de "leer completo" un paper de veinte páginas
mientras haces otra cosa.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from .. import pdf as pdf_mod
from ..config import Config
from .workers import HiloSeccion, HiloVoz

log = logging.getLogger(__name__)


class VentanaLector(QDialog):
    def __init__(self, ruta_pdf: Path, titulo: str, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.ruta_pdf = Path(ruta_pdf)
        self.cfg = cfg
        self.secciones: list[tuple[str, str]] = []
        self._hilo_seccion: HiloSeccion | None = None
        self._hilo_voz: HiloVoz | None = None

        self.setWindowTitle(f"Lector, {titulo[:70]}")
        self.setMinimumSize(1100, 760)
        self.resize(1300, 860)

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(self._panel_pdf())
        divisor.addWidget(self._panel_secciones())
        divisor.setSizes([800, 460])

        caja = QVBoxLayout(self)
        caja.addWidget(divisor)

        self._cargar()

    # ------------------------------------------------------------------

    def _panel_pdf(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)
        caja.setContentsMargins(0, 0, 0, 0)

        self.documento = QPdfDocument(self)
        self.vista = QPdfView(self)
        self.vista.setDocument(self.documento)
        self.vista.setPageMode(QPdfView.PageMode.MultiPage)
        self.vista.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        caja.addWidget(self.vista)

        fila = QHBoxLayout()
        btn_externo = QPushButton("Abrir en el visor del sistema")
        btn_externo.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ruta_pdf)))
        )
        fila.addWidget(btn_externo)
        fila.addStretch()
        self.lbl_ruta = QLabel(str(self.ruta_pdf))
        self.lbl_ruta.setStyleSheet("color: #777; font-size: 11px;")
        fila.addWidget(self.lbl_ruta)
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)
        return w

    def _panel_secciones(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)

        caja.addWidget(QLabel("<b>Secciones detectadas</b>"))
        self.lista = QListWidget()
        self.lista.currentRowChanged.connect(self._seleccionar_seccion)
        caja.addWidget(self.lista, 1)

        caja.addWidget(QLabel("<b>Resumen de la sección</b>"))
        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setPlaceholderText(
            "Elige una sección y pulsa Resumir. El resumen se genera con Claude "
            "y se puede escuchar."
        )
        caja.addWidget(self.txt, 1)

        fila = QHBoxLayout()
        self.btn_resumir = QPushButton("Resumir sección")
        self.btn_resumir.clicked.connect(self._resumir)
        self.btn_escuchar = QPushButton("Escuchar")
        self.btn_escuchar.setEnabled(False)
        self.btn_escuchar.clicked.connect(self._escuchar)
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.setEnabled(False)
        self.btn_parar.clicked.connect(self._parar)
        fila.addWidget(self.btn_resumir)
        fila.addWidget(self.btn_escuchar)
        fila.addWidget(self.btn_parar)
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setStyleSheet("color: #666;")
        caja.addWidget(self.lbl_estado)

        self.reproductor = QMediaPlayer(self)
        self.salida = QAudioOutput(self)
        self.reproductor.setAudioOutput(self.salida)
        self.salida.setVolume(self.cfg.volumen_voz / 100.0)
        return w

    # ------------------------------------------------------------------

    def _cargar(self) -> None:
        estado = self.documento.load(str(self.ruta_pdf))
        if estado != QPdfDocument.Error.None_:
            QMessageBox.warning(self, "No se pudo abrir", f"El PDF no se pudo cargar: {estado}")
            return
        try:
            texto = pdf_mod.extraer_texto(self.ruta_pdf)
            self.secciones = pdf_mod.partir_en_secciones(texto)
        except Exception as exc:
            log.warning("No se pudo extraer texto: %s", exc)
            self.secciones = []

        self.lista.clear()
        for titulo, cuerpo in self.secciones:
            item = QListWidgetItem(f"{titulo}  ({len(cuerpo.split())} palabras)")
            self.lista.addItem(item)
        if self.secciones:
            self.lista.setCurrentRow(0)
        else:
            self.lbl_estado.setText(
                "No se pudieron detectar secciones. El PDF puede ser una imagen "
                "escaneada sin capa de texto."
            )

    def _seleccionar_seccion(self, fila: int) -> None:
        self.txt.clear()
        self.btn_escuchar.setEnabled(False)
        if 0 <= fila < len(self.secciones):
            self.lbl_estado.setText(f"Sección: {self.secciones[fila][0]}")

    def _resumir(self) -> None:
        fila = self.lista.currentRow()
        if not (0 <= fila < len(self.secciones)):
            return
        if not self.cfg.tiene_clave():
            QMessageBox.warning(
                self, "Sin clave",
                "Carga la clave de Claude en la configuración para resumir secciones.",
            )
            return

        titulo, cuerpo = self.secciones[fila]
        self.btn_resumir.setEnabled(False)
        self.lbl_estado.setText(f"Resumiendo '{titulo}'...")

        self._hilo_seccion = HiloSeccion(titulo, cuerpo, self.cfg, self)
        self._hilo_seccion.terminado.connect(self._seccion_lista)
        self._hilo_seccion.fallo.connect(self._seccion_fallo)
        self._hilo_seccion.start()

    def _seccion_lista(self, titulo: str, texto: str) -> None:
        self.txt.setPlainText(texto)
        self.btn_resumir.setEnabled(True)
        self.btn_escuchar.setEnabled(True)
        self.lbl_estado.setText(f"Resumen de '{titulo}' listo.")

    def _seccion_fallo(self, mensaje: str) -> None:
        self.btn_resumir.setEnabled(True)
        self.lbl_estado.setText(f"No se pudo resumir: {mensaje}")

    def _escuchar(self) -> None:
        texto = self.txt.toPlainText().strip()
        if not texto:
            return
        fila = self.lista.currentRow()
        clave = f"seccion|{self.ruta_pdf.stem}|{fila}"
        self.btn_escuchar.setEnabled(False)
        self.lbl_estado.setText("Sintetizando la voz...")

        self._hilo_voz = HiloVoz(texto, clave, self.cfg, self)
        self._hilo_voz.terminado.connect(self._voz_lista)
        self._hilo_voz.fallo.connect(self._voz_fallo)
        self._hilo_voz.start()

    def _voz_lista(self, ruta: str, motor: str) -> None:
        self.reproductor.setSource(QUrl.fromLocalFile(ruta))
        self.reproductor.play()
        self.btn_escuchar.setEnabled(True)
        self.btn_parar.setEnabled(True)
        self.lbl_estado.setText(f"Reproduciendo (motor {motor}).")

    def _voz_fallo(self, mensaje: str) -> None:
        self.btn_escuchar.setEnabled(True)
        self.lbl_estado.setText(f"No se pudo sintetizar: {mensaje}")

    def _parar(self) -> None:
        self.reproductor.stop()
        self.btn_parar.setEnabled(False)
        self.lbl_estado.setText("Detenido.")

    def closeEvent(self, evento) -> None:  # noqa: N802
        self.reproductor.stop()
        for hilo in (self._hilo_seccion, self._hilo_voz):
            if hilo is not None and hilo.isRunning():
                hilo.quit()
                hilo.wait(3000)
        super().closeEvent(evento)
