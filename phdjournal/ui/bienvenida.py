"""Asistente de primer arranque.

Aparece una sola vez, cuando no hay configuración previa. Sirve para que quien
clone el proyecto no herede el campo de investigación de otra persona sin
querer, y para que la app sea útil desde el primer minuto.

Tres caminos, y ninguno obliga a tener clave de API todavía.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QRadioButton, QVBoxLayout, QWidget,
)

from .. import temas
from ..config import Config
from .iconos import icono_app

log = logging.getLogger(__name__)


class DialogoBienvenida(QDialog):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Bienvenido a PHDjournal")
        self.setWindowIcon(icono_app())
        self.setMinimumWidth(620)

        caja = QVBoxLayout(self)
        caja.setSpacing(10)

        icono = QLabel()
        icono.setPixmap(icono_app().pixmap(56, 56))
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caja.addWidget(icono)

        intro = QLabel(
            "<div style='text-align:center'><h2 style='margin:2px'>PHDjournal</h2>"
            "<p style='color:#555'>Busca novedades científicas dos veces al día, "
            "las resume y te las lee en voz alta.</p></div>"
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        caja.addWidget(intro)

        caja.addWidget(QLabel("<b>¿De qué quieres que te traiga papers?</b>"))

        self.grupo = QButtonGroup(self)
        perfil = temas.construir({})
        n_temas = len(perfil.dominios)
        n_term = sum(len(d.terminos) for d in perfil.dominios.values())

        self.rb_ejemplo = QRadioButton(
            f"Usar el perfil de ejemplo: NLP en el borde "
            f"({n_temas} temas, {n_term} términos)"
        )
        self.rb_ejemplo.setChecked(True)
        self.rb_generar = QRadioButton(
            "Describir mi campo y que Claude arme los temas"
        )
        self.rb_vacio = QRadioButton("Empezar sin temas y configurarlos yo")
        for rb in (self.rb_ejemplo, self.rb_generar, self.rb_vacio):
            self.grupo.addButton(rb)
            caja.addWidget(rb)

        nota_ej = QLabel(
            "El perfil de ejemplo cubre procesamiento de lenguaje natural, "
            "modelos pequeños, inferencia en dispositivos limitados, habla, "
            "grafos de conocimiento y sistemas de datos. Puedes cambiarlo "
            "entero después en Configuración, pestaña Temas."
        )
        nota_ej.setWordWrap(True)
        nota_ej.setStyleSheet("color:#666; font-size:11px; padding-left:22px;")
        caja.addWidget(nota_ej)

        caja.addSpacing(8)
        caja.addWidget(QLabel("<b>Cuéntame de tu investigación</b> (opcional)"))
        self.txt_perfil = QPlainTextEdit()
        self.txt_perfil.setPlaceholderText(
            "Un párrafo: qué investigas, sobre qué trabajas, qué te interesa. "
            "Se usa para que los resúmenes respondan 'por qué te importa a ti'.\n\n"
            "Si lo dejas vacío, se arma solo con tus temas."
        )
        self.txt_perfil.setMaximumHeight(96)
        caja.addWidget(self.txt_perfil)

        self.ed_correo = QLineEdit()
        self.ed_correo.setPlaceholderText(
            "tu@correo.com, opcional: da prioridad de cola en OpenAlex y Crossref"
        )
        caja.addWidget(self.ed_correo)

        pie = QLabel(
            "Para los resúmenes hace falta una clave de la API de Claude, que se "
            "carga después en Configuración. Sin ella la app igual busca y "
            "ordena, solo que muestra los abstracts originales."
        )
        pie.setWordWrap(True)
        pie.setStyleSheet("color:#666; font-size:11px; padding-top:6px;")
        caja.addWidget(pie)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Empezar")
        botones.accepted.connect(self._aceptar)
        caja.addWidget(botones)

    def _aceptar(self) -> None:
        self.cfg.perfil_investigador = self.txt_perfil.toPlainText().strip()
        self.cfg.email_contacto = self.ed_correo.text().strip()
        self.cfg.primer_arranque_hecho = True
        self.cfg.guardar()

        if self.rb_vacio.isChecked():
            # Apagar todos los temas del ejemplo, sin borrar nada: se pueden
            # reactivar uno a uno desde la pantalla de Temas.
            overlay = temas.cargar_overlay()
            for clave in temas.profile.DOMINIOS:
                temas.fijar(overlay, clave, "activo", False)
            temas.guardar_overlay(overlay)
            QMessageBox.information(
                self, "Listo",
                "Empezaste sin temas. Ve a Configuración, pestaña Temas, para "
                "crear los tuyos o reactivar los del ejemplo.",
            )
        elif self.rb_generar.isChecked():
            self.generar_pedido = True
            QMessageBox.information(
                self, "Un paso más",
                "Se abrirá la pantalla de Temas. Usa 'Tema nuevo' y describe "
                "tu campo: Claude propondrá los términos y las consultas.\n\n"
                "Mientras tanto quedan activos los temas de ejemplo, para que "
                "la app funcione desde ya.",
            )

        self.accept()

    @property
    def quiere_generar(self) -> bool:
        return self.rb_generar.isChecked()


def hace_falta(cfg: Config) -> bool:
    return not cfg.primer_arranque_hecho
