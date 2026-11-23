"""Vista "Mis documentos": los PDFs que importaste de tu disco.

Vive en su propia pestaña y no comparte lista ni estado con el feed diario.
Repite la forma de la ficha del feed (para que se lea igual) pero sus datos
salen de ``documentos``, no de una corrida.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSlider, QSplitter, QVBoxLayout, QWidget,
)

from .. import db, locales, summarize
from ..config import Config
from .estilo import COLOR_D, COLOR_VEREDICTO, _tarjeta, color_trabajo
from .reader import VentanaLector
from .workers import (
    HiloDOI, HiloImportacion, HiloResumenDocumento, HiloVoz, HiloZotero,
)

log = logging.getLogger(__name__)


def _insignia(texto: str, fondo: str, color: str = "white") -> str:
    return (
        f"<span style='background:{fondo};color:{color};padding:3px 8px;"
        f"border-radius:10px;'>{texto}</span>"
    )


class PanelDocumentos(QWidget):
    # Mensajes para la barra de estado de la ventana principal.
    mensaje = Signal(str)

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.filas: list = []
        self.actual = -1

        self._hilo_importacion: HiloImportacion | None = None
        self._hilo_resumen: HiloResumenDocumento | None = None
        self._hilo_doi: HiloDOI | None = None
        self._hilo_voz: HiloVoz | None = None
        self._hilo_zotero: HiloZotero | None = None

        divisor = QSplitter(Qt.Orientation.Horizontal)
        divisor.addWidget(self._columna_izquierda())
        divisor.addWidget(self._columna_derecha())
        divisor.setSizes([420, 900])
        caja = QVBoxLayout(self)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.addWidget(divisor)

        self.reproductor = QMediaPlayer(self)
        self.salida = QAudioOutput(self)
        self.reproductor.setAudioOutput(self.salida)
        self.salida.setVolume(cfg.volumen_voz / 100.0)
        self.reproductor.positionChanged.connect(self.barra_audio.setValue)
        self.reproductor.durationChanged.connect(self.barra_audio.setMaximum)

        self.cargar()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------

    def _columna_izquierda(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)
        caja.setContentsMargins(0, 0, 0, 0)

        botones = QHBoxLayout()
        self.btn_archivos = QPushButton("Importar archivos...")
        self.btn_archivos.clicked.connect(self.importar_archivos)
        self.btn_carpeta = QPushButton("Importar carpeta...")
        self.btn_carpeta.clicked.connect(self.importar_carpeta)
        botones.addWidget(self.btn_archivos)
        botones.addWidget(self.btn_carpeta)
        caja.addLayout(botones)

        progreso = QHBoxLayout()
        self.barra = QProgressBar()
        self.barra.setVisible(False)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.setVisible(False)
        self.btn_cancelar.clicked.connect(self._cancelar_importacion)
        progreso.addWidget(self.barra, 1)
        progreso.addWidget(self.btn_cancelar)
        caja.addLayout(progreso)

        self.lista = QListWidget()
        self.lista.setAlternatingRowColors(True)
        self.lista.setStyleSheet("QListWidget::item { padding:8px; }")
        self.lista.currentRowChanged.connect(self.mostrar)
        caja.addWidget(self.lista, 1)
        return w

    def _columna_derecha(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)
        caja.setContentsMargins(0, 0, 0, 0)
        caja.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.panel = QWidget()
        self.caja_panel = QVBoxLayout(self.panel)
        self.caja_panel.setContentsMargins(18, 16, 18, 16)
        self.caja_panel.setSpacing(10)
        self.scroll.setWidget(self.panel)
        caja.addWidget(self.scroll, 1)

        barra = QFrame()
        barra.setFrameShape(QFrame.Shape.StyledPanel)
        barra.setStyleSheet("QFrame { background:#f4f6f8; border-top:1px solid #d8dee6; }")
        caja_barra = QVBoxLayout(barra)
        caja_barra.setContentsMargins(18, 8, 18, 10)
        fila = QHBoxLayout()
        self.btn_escuchar = QPushButton("Escuchar el resumen")
        self.btn_escuchar.setEnabled(False)
        self.btn_escuchar.clicked.connect(self._escuchar)
        self.btn_pausa = QPushButton("Pausa")
        self.btn_pausa.setEnabled(False)
        self.btn_pausa.clicked.connect(self._pausa)
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.setEnabled(False)
        self.btn_parar.clicked.connect(self.parar)
        for b in (self.btn_escuchar, self.btn_pausa, self.btn_parar):
            fila.addWidget(b)
        fila.addStretch()
        caja_barra.addLayout(fila)
        self.barra_audio = QSlider(Qt.Orientation.Horizontal)
        self.barra_audio.setEnabled(False)
        self.barra_audio.sliderMoved.connect(lambda p: self.reproductor.setPosition(p))
        caja_barra.addWidget(self.barra_audio)
        caja.addWidget(barra)
        return w

    # ------------------------------------------------------------------
    # Lista
    # ------------------------------------------------------------------

    def cargar(self, seleccionar: str | None = None) -> None:
        """Relee la base. ``seleccionar`` deja elegido ese documento."""
        db.inicializar()
        with db.conexion() as con:
            self.filas = db.listar_documentos(con)

        self.lista.blockSignals(True)
        self.lista.clear()
        for fila in self.filas:
            self.lista.addItem(self._item(fila))

        if not self.filas:
            self.lista.blockSignals(False)
            self._limpiar()
            self.caja_panel.addWidget(_tarjeta(
                "<b>Todavía no hay documentos</b><br>Importa PDFs que ya tengas "
                "en tu disco con <i>Importar archivos</i> o <i>Importar carpeta</i>. "
                "Se copian a la biblioteca de la app, se completan sus metadatos "
                "por DOI y se resumen a partir del texto completo. No se mezclan "
                "con la búsqueda diaria.",
                "#f2f2f2", "#ddd",
            ))
            self.caja_panel.addStretch()
            return

        indice = 0
        if seleccionar:
            indice = next(
                (i for i, f in enumerate(self.filas) if f["id"] == seleccionar), 0
            )
        elif 0 <= self.actual < len(self.filas):
            indice = self.actual
        self.lista.setCurrentRow(indice)
        self.lista.blockSignals(False)
        self.mostrar(indice)

    def _item(self, fila) -> QListWidgetItem:
        resumen = json.loads(fila["resumen_json"]) if fila["resumen_json"] else {}
        verificado = fila["metadatos_origen"] == "doi"
        marcas = []
        if not verificado:
            marcas.append("sin DOI")
        if not resumen:
            marcas.append("sin resumen")
        if fila["exportado_zotero"]:
            marcas.append("en Zotero")
        leido = "" if fila["leido"] else "•"
        venue = (fila["venue"] or "sin venue")[:38]
        texto = (
            f"{leido} {fila['titulo'][:95]}\n"
            f"     {venue}  |  {fila['anio'] or 's/f'}  |  "
            f"{resumen.get('veredicto', '')}  {' · '.join(marcas)}"
        )
        return QListWidgetItem(texto)

    # ------------------------------------------------------------------
    # Ficha
    # ------------------------------------------------------------------

    def _limpiar(self) -> None:
        while self.caja_panel.count():
            item = self.caja_panel.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _fila(self):
        return self.filas[self.actual] if 0 <= self.actual < len(self.filas) else None

    def mostrar(self, indice: int) -> None:
        self._limpiar()
        self.actual = indice
        fila = self._fila()
        if fila is None:
            return

        resumen = json.loads(fila["resumen_json"]) if fila["resumen_json"] else None
        desglose = json.loads(fila["desglose"] or "{}")
        verificado = fila["metadatos_origen"] == "doi"

        titulo_es = (resumen or {}).get("titulo_es") or fila["titulo"]
        lbl = QLabel(f"<h2 style='margin:0'>{titulo_es}</h2>")
        lbl.setWordWrap(True)
        self.caja_panel.addWidget(lbl)
        if resumen and resumen.get("titulo_es"):
            orig = QLabel(f"<i>{fila['titulo']}</i>")
            orig.setWordWrap(True)
            orig.setStyleSheet("color:#666; font-size:12px;")
            self.caja_panel.addWidget(orig)

        autores = json.loads(fila["autores"] or "[]")
        firma = ", ".join(autores[:5]) + (" y otros" if len(autores) > 5 else "")
        extra = json.loads(fila["extra"] or "{}")
        detalles = [
            f"<b>{fila['venue'] or 'sin venue'}</b> ({fila['tipo_venue']})",
            str(fila["fecha_pub"] or fila["anio"] or "sin fecha"),
        ]
        if extra.get("volume"):
            detalles.append(
                f"vol. {extra['volume']}"
                + (f"({extra['issue']})" if extra.get("issue") else "")
                + (f", {extra['pages']}" if extra.get("pages") else "")
            )
        if fila["doi"]:
            detalles.append(f"DOI {fila['doi']}")
        detalles.append(f"{fila['n_paginas']} págs.")
        meta = QLabel(
            " &nbsp;|&nbsp; ".join(detalles)
            + (f"<br>{firma}" if firma else "")
            + f"<br><span style='color:#888'>archivo: {fila['nombre_original']}</span>"
        )
        meta.setWordWrap(True)
        meta.setStyleSheet("color:#444; font-size:12px;")
        self.caja_panel.addWidget(meta)

        insignias = [
            _insignia("metadatos verificados por DOI", "#2e7d32") if verificado
            else _insignia("metadatos sin verificar", "#ef6c00")
        ]
        claves = desglose.get("dominios") or []
        nombres = desglose.get("nombres_dominios") or []
        for i, clave in enumerate(claves[:4]):
            nombre = nombres[i] if i < len(nombres) else clave
            insignias.append(_insignia(f"{clave} {nombre}", COLOR_D.get(clave, "#607d8b")))
        if not claves:
            insignias.append(_insignia("no toca tus temas", "#e3e9f0", "#555"))
        if fila["trabajo"]:
            insignias.append(_insignia(f"toca {fila['trabajo']}", color_trabajo(fila["trabajo"])))
        if resumen and resumen.get("veredicto"):
            v = resumen["veredicto"]
            insignias.append(_insignia(v, COLOR_VEREDICTO.get(v, "#555")))
        lbl_ins = QLabel(" &nbsp; ".join(insignias))
        lbl_ins.setTextFormat(Qt.TextFormat.RichText)
        lbl_ins.setWordWrap(True)
        self.caja_panel.addWidget(lbl_ins)

        if not verificado:
            origen = (
                "los leyó la IA en la portada" if fila["metadatos_origen"] == "ia"
                else "salen de las propiedades del PDF"
            )
            self.caja_panel.addWidget(_tarjeta(
                f"<b>Metadatos incompletos</b><br>No se encontró un DOI que "
                f"coincida con la portada; los datos {origen}. Indica el DOI "
                "para completarlos antes de enviarlo a Zotero.",
                "#fff3e0", "#f0b46a",
            ))

        self.caja_panel.addWidget(self._separador())

        if resumen:
            self.caja_panel.addWidget(_tarjeta(
                f"<b>Por qué te importa</b><br>{resumen.get('por_que_te_importa', '')}",
                "#fff6e5", "#e8c98a",
            ))
            for etiqueta, clave in (
                ("Qué hace", "que_hace"), ("Método", "metodo"),
                ("Hallazgo", "hallazgo"), ("Limitaciones", "limitaciones"),
            ):
                if resumen.get(clave):
                    self.caja_panel.addWidget(_tarjeta(f"<b>{etiqueta}</b><br>{resumen[clave]}"))
            aviso = QLabel(
                f"Resumen generado por IA ({fila['resumen_modelo']}) a partir del "
                "texto completo del PDF. No citar este texto, verificar contra el original."
            )
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color:#8a6d3b; font-size:11px; font-style:italic;")
            self.caja_panel.addWidget(aviso)
        else:
            self.caja_panel.addWidget(_tarjeta(
                "<b>Sin resumen generado</b><br>"
                + (fila["resumen_origen"] or "No se encontró el abstract."),
                "#f2f2f2", "#ddd",
            ))

        self.caja_panel.addWidget(self._separador())
        self.caja_panel.addWidget(self._acciones(fila, resumen, verificado))
        self.caja_panel.addStretch()

        hay_voz = bool(resumen and resumen.get("texto_para_voz"))
        self.btn_escuchar.setEnabled(hay_voz)
        self.btn_escuchar.setToolTip("" if hay_voz else "Primero genera el resumen.")

        if not fila["leido"]:
            with db.conexion() as con:
                db.actualizar_documento(con, fila["id"], leido=1)

    def _separador(self) -> QFrame:
        linea = QFrame()
        linea.setFrameShape(QFrame.Shape.HLine)
        linea.setStyleSheet("color:#ddd;")
        return linea

    def _acciones(self, fila, resumen, verificado: bool) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)
        caja.setContentsMargins(0, 0, 0, 0)
        arriba = QHBoxLayout()
        abajo = QHBoxLayout()

        b = QPushButton("Leer completo")
        b.clicked.connect(lambda: self._leer(fila))
        arriba.addWidget(b)

        b = QPushButton("Regenerar resumen" if resumen else "Resumir")
        b.setEnabled(self.cfg.tiene_clave())
        b.setToolTip(
            summarize.costo_documentos(self.cfg.modelo_claude, 1)
            if self.cfg.tiene_clave() else "Falta la clave de Claude."
        )
        b.clicked.connect(lambda: self._resumir(fila["id"]))
        arriba.addWidget(b)

        ya = bool(fila["exportado_zotero"])
        b = QPushButton("Ya está en Zotero" if ya else "Enviar a Zotero")
        b.setEnabled(not ya)
        b.clicked.connect(lambda: self._enviar_zotero(fila))
        arriba.addWidget(b)
        arriba.addStretch()

        b = QPushButton("Corregir DOI..." if verificado else "Indicar DOI...")
        b.clicked.connect(lambda: self._pedir_doi(fila))
        abajo.addWidget(b)

        url = fila["url"] or ""
        b = QPushButton("Abrir en el navegador")
        b.setEnabled(bool(url))
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        abajo.addWidget(b)

        b = QPushButton("Mostrar el archivo")
        b.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(Path(fila["ruta_pdf"]).parent))
        ))
        abajo.addWidget(b)

        b = QPushButton("Quitar")
        b.setToolTip("Quita el documento de la lista y borra la copia de la app.")
        b.clicked.connect(lambda: self._quitar(fila))
        abajo.addWidget(b)
        abajo.addStretch()

        caja.addLayout(arriba)
        caja.addLayout(abajo)
        return w

    # ------------------------------------------------------------------
    # Importación
    # ------------------------------------------------------------------

    def importar_archivos(self) -> None:
        rutas, _ = QFileDialog.getOpenFileNames(
            self, "Elegir PDFs", str(Path.home()), "PDF (*.pdf)"
        )
        if rutas:
            self._importar([Path(r) for r in rutas])

    def importar_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta con PDFs", str(Path.home())
        )
        if carpeta:
            self._importar([Path(carpeta)])

    def _importar(self, rutas: list[Path]) -> None:
        if self._hilo_importacion is not None and self._hilo_importacion.isRunning():
            self.mensaje.emit("Ya hay una importación en curso.")
            return
        pdfs = locales.buscar_pdfs(rutas)
        if not pdfs:
            QMessageBox.information(self, "Sin PDFs", "No se encontró ningún PDF ahí.")
            return

        n = len(pdfs)
        texto = (
            f"Se van a importar {n} PDF{'s' if n != 1 else ''}. Cada uno se copia "
            "a la biblioteca de la app y se busca su DOI para completar los "
            "metadatos. Los que ya estén importados se saltan."
        )
        caja = QMessageBox(self)
        caja.setWindowTitle("Importar documentos")
        caja.setIcon(QMessageBox.Icon.Question)
        con_resumen = None
        if self.cfg.tiene_clave():
            caja.setText(
                texto + "\n\nResumirlos ahora a partir del texto completo cuesta "
                f"{summarize.costo_documentos(self.cfg.modelo_claude, n)}."
            )
            con_resumen = caja.addButton("Importar y resumir", QMessageBox.ButtonRole.AcceptRole)
            solo = caja.addButton("Solo importar", QMessageBox.ButtonRole.AcceptRole)
        else:
            caja.setText(texto + "\n\nNo hay clave de Claude: se importan sin resumen.")
            solo = caja.addButton("Importar", QMessageBox.ButtonRole.AcceptRole)
        caja.addButton(QMessageBox.StandardButton.Cancel)
        caja.exec()
        elegido = caja.clickedButton()
        if elegido not in (con_resumen, solo):
            return

        self._activar_importacion(True)
        self._hilo_importacion = HiloImportacion(
            pdfs, self.cfg, elegido is con_resumen, self
        )
        self._hilo_importacion.progreso.connect(self._progreso)
        self._hilo_importacion.terminado.connect(self._importacion_lista)
        self._hilo_importacion.start()

    def _activar_importacion(self, activa: bool) -> None:
        self.btn_archivos.setEnabled(not activa)
        self.btn_carpeta.setEnabled(not activa)
        self.barra.setVisible(activa)
        self.btn_cancelar.setVisible(activa)
        self.btn_cancelar.setEnabled(True)
        self.barra.setValue(0)

    def _progreso(self, texto: str, pct: int) -> None:
        self.barra.setValue(pct)
        self.mensaje.emit(texto)

    def _cancelar_importacion(self) -> None:
        if self._hilo_importacion is not None:
            self._hilo_importacion.cancelar()
            self.btn_cancelar.setEnabled(False)
            self.mensaje.emit("Cancelando al terminar el documento en curso...")

    def _importacion_lista(self, resultados: list) -> None:
        self._activar_importacion(False)
        nuevos = [r for r in resultados if r.estado == "nuevo"]
        self.cargar(seleccionar=nuevos[0].doc_id if nuevos else None)

        cuenta = {
            "nuevo": len(nuevos),
            "duplicado": sum(r.estado == "duplicado" for r in resultados),
            "sin_texto": sum(r.estado == "sin_texto" for r in resultados),
            "error": sum(r.estado == "error" for r in resultados),
        }
        sin_doi = sum(not r.verificado for r in nuevos)
        self.mensaje.emit(
            f"Importados {cuenta['nuevo']}, ya estaban {cuenta['duplicado']}, "
            f"sin texto {cuenta['sin_texto']}, con error {cuenta['error']}."
        )
        problemas = [
            f"• {r.ruta.name}: {r.mensaje}" for r in resultados
            if r.estado in ("sin_texto", "error") or r.mensaje != "importado"
        ]
        if problemas or sin_doi:
            QMessageBox.information(
                self, "Importación terminada",
                f"{cuenta['nuevo']} importados, {sin_doi} sin DOI verificado.\n\n"
                + "\n".join(problemas[:25])
                + ("\n..." if len(problemas) > 25 else ""),
            )

    # ------------------------------------------------------------------
    # Resumen y DOI
    # ------------------------------------------------------------------

    def _resumir(self, doc_id: str) -> None:
        if self._hilo_resumen is not None and self._hilo_resumen.isRunning():
            return
        self.mensaje.emit(f"Resumiendo el documento con {self.cfg.modelo_claude}...")
        self._hilo_resumen = HiloResumenDocumento(doc_id, self.cfg, self)
        self._hilo_resumen.terminado.connect(
            lambda d: (self.mensaje.emit("Resumen listo."), self.cargar(seleccionar=d))
        )
        self._hilo_resumen.fallo.connect(
            lambda m: (
                self.mensaje.emit(f"No se pudo resumir: {m}"),
                QMessageBox.warning(self, "No se pudo resumir", m),
            )
        )
        self._hilo_resumen.start()

    def _pedir_doi(self, fila, despues=None) -> None:
        doi, ok = QInputDialog.getText(
            self, "DOI del documento",
            "Escribe el DOI (por ejemplo 10.1145/3580305.3599812).\n"
            "Se resuelve y se comprueba que el título coincida con la portada.",
            text=fila["doi"] or "",
        )
        if ok and doi.strip():
            self._aplicar_doi(fila["id"], doi.strip(), False, despues)

    def _aplicar_doi(self, doc_id: str, doi: str, forzar: bool, despues=None) -> None:
        self.mensaje.emit(f"Resolviendo el DOI {doi}...")
        self._hilo_doi = HiloDOI(doc_id, doi, self.cfg, forzar, self)
        self._hilo_doi.terminado.connect(
            lambda ok, m: self._doi_listo(ok, m, doc_id, doi, forzar, despues)
        )
        self._hilo_doi.start()

    def _doi_listo(self, ok: bool, mensaje: str, doc_id, doi, forzar, despues) -> None:
        self.mensaje.emit(mensaje)
        if ok:
            self.cargar(seleccionar=doc_id)
            if despues:
                despues()
            return
        if not forzar and "no aparece en la portada" in mensaje:
            r = QMessageBox.question(
                self, "El DOI no coincide",
                f"{mensaje}.\n\n¿Usarlo de todos modos? Hazlo solo si estás "
                "seguro de que es el de este documento (por ejemplo, si la "
                "portada no trae el título como texto).",
            )
            if r == QMessageBox.StandardButton.Yes:
                self._aplicar_doi(doc_id, doi, True, despues)
            return
        QMessageBox.warning(self, "No se pudo usar el DOI", mensaje)

    # ------------------------------------------------------------------
    # Lector, Zotero, quitar
    # ------------------------------------------------------------------

    def _leer(self, fila) -> None:
        ruta = Path(fila["ruta_pdf"])
        if not ruta.exists():
            QMessageBox.warning(self, "Falta el archivo", f"No se encuentra {ruta}.")
            return
        VentanaLector(ruta, fila["titulo"], self.cfg, self).exec()

    def _enviar_zotero(self, fila) -> None:
        if fila["metadatos_origen"] != "doi":
            caja = QMessageBox(self)
            caja.setWindowTitle("Metadatos sin verificar")
            caja.setIcon(QMessageBox.Icon.Warning)
            caja.setText(
                "Este documento no tiene un DOI verificado, así que sus metadatos "
                "pueden estar incompletos o equivocados.\n\nIndica el DOI para "
                "completarlos. Si el documento no tiene DOI (una tesis o un "
                "reporte técnico, por ejemplo), puedes enviarlo así: llevará la "
                "etiqueta 'metadatos-sin-verificar' en Zotero."
            )
            b_doi = caja.addButton("Indicar DOI...", QMessageBox.ButtonRole.AcceptRole)
            b_asi = caja.addButton("Enviar así", QMessageBox.ButtonRole.DestructiveRole)
            caja.addButton(QMessageBox.StandardButton.Cancel)
            caja.exec()
            if caja.clickedButton() is b_doi:
                doc_id = fila["id"]
                self._pedir_doi(fila, despues=lambda: self._enviar_por_id(doc_id))
                return
            if caja.clickedButton() is not b_asi:
                return
        self._lanzar_zotero(fila, dirigir=True)

    def _enviar_por_id(self, doc_id: str) -> None:
        with db.conexion() as con:
            fila = db.leer_documento(con, doc_id)
        if fila is not None:
            self._lanzar_zotero(fila, dirigir=True)

    def _lanzar_zotero(self, fila, dirigir: bool) -> None:
        if not Path(fila["ruta_pdf"]).exists():
            QMessageBox.warning(self, "Falta el archivo", "La copia del PDF ya no existe.")
            return
        item = locales.item_zotero(fila, self.cfg)
        doc_id = fila["id"]
        self.mensaje.emit("Enviando a Zotero...")
        self._hilo_zotero = HiloZotero(self.cfg, item, dirigir, self)
        self._hilo_zotero.progreso.connect(self.mensaje.emit)
        self._hilo_zotero.terminado.connect(lambda m: self._zotero_ok(m, doc_id))
        self._hilo_zotero.falta_subcoleccion.connect(
            lambda msg: self._zotero_falta_coleccion(msg, fila)
        )
        self._hilo_zotero.fallo.connect(
            lambda m: (
                self.mensaje.emit(f"Zotero: {m}"),
                QMessageBox.warning(self, "No se pudo exportar a Zotero", m),
            )
        )
        self._hilo_zotero.start()

    def _zotero_ok(self, mensaje: str, doc_id: str) -> None:
        with db.conexion() as con:
            db.actualizar_documento(con, doc_id, exportado_zotero=db.ahora())
        self.mensaje.emit(mensaje)
        self.cargar(seleccionar=doc_id)

    def _zotero_falta_coleccion(self, instrucciones: str, fila) -> None:
        r = QMessageBox.question(
            self, "Falta crear la subcolección",
            f"{instrucciones}\n\nCréala en Zotero y pulsa Reintentar, o guarda "
            "de todos modos en la colección que tengas seleccionada.",
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Cancel,
        )
        if r == QMessageBox.StandardButton.Retry:
            self._lanzar_zotero(fila, dirigir=True)
        elif r == QMessageBox.StandardButton.Save:
            self._lanzar_zotero(fila, dirigir=False)

    def _quitar(self, fila) -> None:
        r = QMessageBox.question(
            self, "Quitar documento",
            f"¿Quitar «{fila['titulo'][:80]}» de tus documentos?\n\n"
            "Se borra su resumen y la copia dentro de la app. Tu archivo "
            "original no se toca, y si ya estaba en Zotero, ahí se queda.",
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self.parar()
        with db.conexion() as con:
            db.borrar_documento(con, fila["id"])
        copia = Path(fila["ruta_pdf"])
        try:
            if copia.is_relative_to(locales.dir_locales(self.cfg)):
                copia.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("No se pudo borrar la copia %s: %s", copia, exc)
        self.actual = min(self.actual, len(self.filas) - 2)
        self.cargar()
        self.mensaje.emit("Documento quitado.")

    # ------------------------------------------------------------------
    # Voz
    # ------------------------------------------------------------------

    def _escuchar(self) -> None:
        fila = self._fila()
        if fila is None or not fila["resumen_json"]:
            return
        texto = json.loads(fila["resumen_json"]).get("texto_para_voz")
        if not texto:
            return
        self.btn_escuchar.setEnabled(False)
        self.mensaje.emit("Sintetizando la voz...")
        doc_id = fila["id"]
        self._hilo_voz = HiloVoz(texto, f"documento|{doc_id}", self.cfg, self)
        self._hilo_voz.terminado.connect(lambda ruta, motor: self._voz_lista(ruta, motor, doc_id))
        self._hilo_voz.fallo.connect(
            lambda m: (self.btn_escuchar.setEnabled(True),
                       self.mensaje.emit(f"No se pudo sintetizar: {m}"))
        )
        self._hilo_voz.start()

    def _voz_lista(self, ruta: str, motor: str, doc_id: str) -> None:
        with db.conexion() as con:
            db.actualizar_documento(con, doc_id, ruta_audio=ruta)
        self.reproductor.setSource(QUrl.fromLocalFile(ruta))
        self.reproductor.play()
        self.btn_escuchar.setEnabled(True)
        self.btn_pausa.setEnabled(True)
        self.btn_parar.setEnabled(True)
        self.barra_audio.setEnabled(True)
        self.mensaje.emit(f"Reproduciendo (motor {motor}).")

    def _pausa(self) -> None:
        if self.reproductor.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.reproductor.pause()
            self.btn_pausa.setText("Continuar")
        else:
            self.reproductor.play()
            self.btn_pausa.setText("Pausa")

    def parar(self) -> None:
        self.reproductor.stop()
        self.btn_pausa.setEnabled(False)
        self.btn_parar.setEnabled(False)
        self.btn_pausa.setText("Pausa")

    def actualizar_config(self, cfg: Config) -> None:
        self.cfg = cfg
        self.salida.setVolume(cfg.volumen_voz / 100.0)
        self.mostrar(self.actual)
