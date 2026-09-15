"""Menú Ayuda: cómo se usa, qué versión es y bajo qué licencia.

El texto de la guía vive aquí y no en un archivo aparte a propósito: así viaja
con el programa y no puede quedarse desincronizado ni perderse al mover
carpetas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QTextBrowser, QVBoxLayout,
)

from .. import __version__
from .iconos import icono_app

REPO = "https://github.com/ovelazquezj/PHDjournal"
AUTOR = "Omar Francisco Velazquez Juarez"

GUIA = """
<h2>PHDjournal</h2>
<p>Un lector de novedades cientificas que busca solo, resume en tu idioma y te
lee los resumenes en voz alta.</p>

<h3>Como funciona</h3>
<p>Vive en la bandeja del sistema. Dos veces al dia, a las horas que fijes,
consulta cuatro fuentes abiertas (arXiv, OpenAlex, Semantic Scholar y
Crossref), puntua todo lo que encuentra contra tus temas, se queda con los
mejores, los resume con Claude y te avisa con una notificacion. Al hacer clic
en la notificacion se abre esta ventana.</p>

<h3>La ventana</h3>
<ul>
<li><b>Izquierda:</b> los papers de la ultima busqueda, ordenados por puntaje.
Un punto delante marca los que no has abierto.</li>
<li><b>Derecha:</b> la ficha del paper seleccionado, con su resumen dividido en
que hace, metodo, hallazgo, por que te importa y limitaciones.</li>
<li><b>Abajo:</b> los controles de voz, siempre visibles.</li>
</ul>

<h3>Botones de la barra</h3>
<ul>
<li><b>Buscar ahora:</b> lanza una busqueda sin esperar al horario. No consume
la busqueda programada.</li>
<li><b>Escuchar todos:</b> reproduce los resumenes uno tras otro, sin que
tengas que tocar nada.</li>
<li><b>Recargar (F5):</b> vuelve a leer la base. Hace falta si buscaste desde
la consola, porque eso ocurre en otro proceso.</li>
<li><b>Configuracion:</b> temas, claves, horarios, voz, Zotero y fuentes.</li>
</ul>

<h3>Acciones sobre un paper</h3>
<ul>
<li><b>Escuchar el resumen:</b> lo sintetiza y lo reproduce. Si el paper aun no
tiene resumen, el boton cambia a <i>Resumir y escuchar</i> y lo genera al
momento.</li>
<li><b>Leer completo:</b> descarga el PDF si es de acceso abierto y abre el
lector, que detecta las secciones del documento y puede resumir y leer en voz
alta cada una por separado.</li>
<li><b>Marcar util y enviar a Zotero:</b> guarda la referencia en la
subcoleccion que hayas configurado, con el resumen como nota y el PDF adjunto.
Si Zotero esta cerrado, la app lo abre minimizada.</li>
</ul>

<h3>Temas: que se busca</h3>
<p>En <b>Configuracion, pestana Temas</b> defines tus areas. Cada tema tiene un
vocabulario, un peso y una casilla que decide si ese tema, por si solo, basta
para traerte un paper.</p>
<p>Puedes crear temas nuevos describiendolos en una frase: Claude propone los
terminos y las consultas, y tu revisas la lista antes de guardar.</p>
<p>El boton <b>Probar cambios</b> te ensena que entraria y que saldria con tus
modificaciones, usando los candidatos ya descargados. No consulta la red ni
gasta en la API, asi que puedes repetirlo cuantas veces quieras.</p>

<h3>Mis trabajos</h3>
<p>Tus papers o proyectos en curso. Sirven para que la app etiquete cada
novedad con el trabajo tuyo al que toca. <b>No influyen en el puntaje ni en la
busqueda</b>, solo etiquetan, y quedarse sin etiqueta es normal.</p>

<h3>Como se ordenan los papers</h3>
<p>El puntaje combina cuatro cosas, con los pesos que tu decidas:</p>
<ul>
<li><b>Relevancia:</b> cuanto coincide con tus temas. El titulo pesa el triple
que el resumen.</li>
<li><b>Venue:</b> la calidad de la revista o congreso.</li>
<li><b>Citas:</b> velocidad de citas, no el total. Un paper de hace un mes con
tres citas va mas rapido que uno de hace cuatro anos con cuarenta.</li>
<li><b>Novedad:</b> decae con los dias.</li>
</ul>
<p>Cada ficha explica por que salio ese paper, componente por componente.</p>

<h3>Integridad academica</h3>
<p>Todo resumen se guarda marcado como generado por inteligencia artificial,
con el modelo que lo produjo. La nota que viaja a Zotero lleva un aviso
explicito de no citar ese texto y verificar contra el original.</p>

<h3>Cuando algo no va</h3>
<ul>
<li><b>No aparecen papers nuevos:</b> revisa la ventana de dias en
Configuracion, Ranking. Por defecto son 21.</li>
<li><b>Los resumenes no se generan:</b> falta la clave de Claude en
Configuracion, Claude.</li>
<li><b>Una fuente devuelve cero:</b> suele ser limite de peticiones. Espera
unos minutos entre busquedas manuales.</li>
<li><b>Cambiaste el codigo:</b> hay que reiniciar la app. F5 solo relee datos.</li>
</ul>
"""


class DialogoGuia(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cómo usar PHDjournal")
        self.setWindowIcon(icono_app())
        self.resize(760, 720)

        caja = QVBoxLayout(self)
        vista = QTextBrowser()
        vista.setOpenExternalLinks(True)
        vista.setHtml(GUIA)
        caja.addWidget(vista)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        botones.accepted.connect(self.accept)
        caja.addWidget(botones)


class DialogoAcercaDe(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Acerca de PHDjournal")
        self.setWindowIcon(icono_app())
        self.setMinimumWidth(460)

        caja = QVBoxLayout(self)
        caja.setSpacing(12)

        icono = QLabel()
        icono.setPixmap(icono_app().pixmap(64, 64))
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caja.addWidget(icono)

        texto = QLabel(
            f"<div style='text-align:center'>"
            f"<h2 style='margin:0'>PHDjournal</h2>"
            f"<p style='color:#666;margin:4px 0 14px 0'>Versión {__version__}</p>"
            f"<p>Lector diario de novedades científicas,<br>"
            f"con resúmenes y lectura en voz alta.</p>"
            f"<p style='margin-top:14px'>© 2026 {AUTOR}<br>"
            f"Licencia MIT</p>"
            f"<p><a href='{REPO}'>{REPO}</a></p>"
            f"</div>"
        )
        texto.setTextFormat(Qt.TextFormat.RichText)
        texto.setOpenExternalLinks(True)
        texto.setWordWrap(True)
        caja.addWidget(texto)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        botones.accepted.connect(self.accept)
        caja.addWidget(botones)


class DialogoLicencia(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Licencia MIT")
        self.setWindowIcon(icono_app())
        self.resize(660, 540)

        caja = QVBoxLayout(self)
        vista = QPlainTextEdit()
        vista.setReadOnly(True)
        vista.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        vista.setPlainText(_texto_licencia())
        caja.addWidget(vista)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        botones.accepted.connect(self.accept)
        caja.addWidget(botones)


def _texto_licencia() -> str:
    """Lee el LICENSE del proyecto; si falta, muestra una copia incrustada."""
    ruta = Path(__file__).resolve().parent.parent.parent / "LICENSE"
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError:
        return LICENCIA_EMBEBIDA


LICENCIA_EMBEBIDA = f"""MIT License

Copyright (c) 2026 {AUTOR}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
