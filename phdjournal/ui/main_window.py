"""Ventana principal del lector.

Dos pestañas que no se mezclan:

* **Búsqueda diaria**: a la izquierda los papers de la última corrida, a la
  derecha la ficha del seleccionado, con el resumen, la voz y las acciones.
* **Mis documentos**: los PDFs importados desde tu disco (``documentos.py``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QSplitter, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import db, pipeline, scheduler, zotero
from ..config import Config
from ..ranking import Puntaje
from .documentos import PanelDocumentos
from .estilo import (
    COLOR_D, COLOR_VEREDICTO, _tarjeta, color_trabajo, reponer_desplazamiento,
)
from .iconos import icono_app
from .reader import VentanaLector
from .settings_dialog import DialogoConfig
from .workers import HiloCorrida, HiloPDF, HiloResumen, HiloVoz, HiloZotero

log = logging.getLogger(__name__)


class VentanaPrincipal(QMainWindow):
    # La emite al terminar cualquier corrida, para que la bandeja notifique.
    corrida_terminada = Signal(object)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.corrida_id: int | None = None
        self.filas: list = []
        self.actual: int = -1

        self._hilo_corrida: HiloCorrida | None = None
        self._hilo_voz: HiloVoz | None = None
        self._hilo_pdf: HiloPDF | None = None
        self._hilo_zotero: HiloZotero | None = None
        self._hilo_resumen: HiloResumen | None = None
        self._cola_escucha: list[int] = []

        self.setWindowTitle("PHDjournal, lector diario de papers")
        self.setWindowIcon(icono_app())
        self.resize(1320, 880)

        self._construir_menu()
        self._construir_barra()
        self._construir_cuerpo()
        self._construir_estado()

        self.reproductor = QMediaPlayer(self)
        self.salida = QAudioOutput(self)
        self.reproductor.setAudioOutput(self.salida)
        self.salida.setVolume(cfg.volumen_voz / 100.0)
        self.reproductor.positionChanged.connect(self._mover_barra)
        self.reproductor.durationChanged.connect(self.barra_audio.setMaximum)
        self.reproductor.mediaStatusChanged.connect(self._fin_de_pista)

        self.cargar_ultima_corrida()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------

    def _construir_menu(self) -> None:
        barra = self.menuBar()

        m_archivo = barra.addMenu("&Archivo")
        a_buscar = QAction("&Buscar ahora", self)
        a_buscar.setShortcut("Ctrl+B")
        a_buscar.triggered.connect(lambda: self.lanzar_corrida("manual"))
        m_archivo.addAction(a_buscar)
        a_recargar = QAction("&Recargar", self)
        a_recargar.setShortcut("F5")
        a_recargar.triggered.connect(self.recargar)
        m_archivo.addAction(a_recargar)
        m_archivo.addSeparator()
        a_imp = QAction("&Importar documentos...", self)
        a_imp.setShortcut("Ctrl+I")
        a_imp.triggered.connect(self._importar_documentos)
        m_archivo.addAction(a_imp)
        a_imp_dir = QAction("Importar &carpeta de documentos...", self)
        a_imp_dir.triggered.connect(self._importar_carpeta)
        m_archivo.addAction(a_imp_dir)
        m_archivo.addSeparator()
        a_config = QAction("&Configuración...", self)
        a_config.triggered.connect(self.abrir_config)
        m_archivo.addAction(a_config)
        m_archivo.addSeparator()
        a_cerrar = QAction("&Ocultar en la bandeja", self)
        a_cerrar.triggered.connect(self.hide)
        m_archivo.addAction(a_cerrar)

        m_ayuda = barra.addMenu("A&yuda")
        a_guia = QAction("&Cómo usar PHDjournal", self)
        a_guia.setShortcut("F1")
        a_guia.triggered.connect(self._abrir_guia)
        m_ayuda.addAction(a_guia)
        m_ayuda.addSeparator()
        a_lic = QAction("&Licencia", self)
        a_lic.triggered.connect(self._abrir_licencia)
        m_ayuda.addAction(a_lic)
        a_acerca = QAction("&Acerca de PHDjournal", self)
        a_acerca.triggered.connect(self._abrir_acerca)
        m_ayuda.addAction(a_acerca)

    def _abrir_guia(self) -> None:
        from .ayuda import DialogoGuia

        DialogoGuia(self).exec()

    def _abrir_licencia(self) -> None:
        from .ayuda import DialogoLicencia

        DialogoLicencia(self).exec()

    def _abrir_acerca(self) -> None:
        from .ayuda import DialogoAcercaDe

        DialogoAcercaDe(self).exec()

    def _construir_barra(self) -> None:
        barra = QToolBar("Principal")
        barra.setMovable(False)
        self.addToolBar(barra)

        self.act_buscar = QAction("Buscar ahora", self)
        self.act_buscar.triggered.connect(lambda: self.lanzar_corrida("manual"))
        barra.addAction(self.act_buscar)

        self.act_escuchar_todo = QAction("Escuchar todos", self)
        self.act_escuchar_todo.triggered.connect(self._escuchar_todos)
        barra.addAction(self.act_escuchar_todo)

        # Recargar: la ventana lee la base una vez al abrirse. Si la corrida
        # ocurrió en otro proceso (por ejemplo `python -m phdjournal --buscar`
        # desde la consola), esta ventana no se entera sola.
        act_recargar = QAction("Recargar", self)
        act_recargar.setShortcut("F5")
        act_recargar.setToolTip(
            "Vuelve a leer la base. Útil si buscaste desde la consola (F5)."
        )
        act_recargar.triggered.connect(self.recargar)
        barra.addAction(act_recargar)

        barra.addSeparator()
        act_config = QAction("Configuración", self)
        act_config.triggered.connect(self.abrir_config)
        barra.addAction(act_config)

        espaciador = QWidget()
        espaciador.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        barra.addWidget(espaciador)

        self.lbl_proxima = QLabel("")
        self.lbl_proxima.setStyleSheet("color:#555; padding-right:10px;")
        barra.addWidget(self.lbl_proxima)

    def _construir_cuerpo(self) -> None:
        divisor = QSplitter(Qt.Orientation.Horizontal)

        self.lista = QListWidget()
        self.lista.setAlternatingRowColors(True)
        self.lista.setStyleSheet("QListWidget::item { padding:8px; }")
        self.lista.currentRowChanged.connect(self.mostrar_paper)
        divisor.addWidget(self.lista)

        # Columna derecha: ficha desplazable arriba, controles de voz fijos
        # abajo. Fijos a propósito: si vivieran dentro de la ficha, se irían
        # de la vista al desplazar el resumen, justo cuando quieres pausar.
        derecha = QWidget()
        caja_derecha = QVBoxLayout(derecha)
        caja_derecha.setContentsMargins(0, 0, 0, 0)
        caja_derecha.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.panel = QWidget()
        self.caja_panel = QVBoxLayout(self.panel)
        self.caja_panel.setContentsMargins(18, 16, 18, 16)
        self.caja_panel.setSpacing(10)
        self.scroll.setWidget(self.panel)
        caja_derecha.addWidget(self.scroll, 1)
        caja_derecha.addWidget(self._barra_audio_fija())

        divisor.addWidget(derecha)
        divisor.setSizes([420, 900])

        self.documentos = PanelDocumentos(self.cfg, self)
        self.documentos.mensaje.connect(lambda m: self.lbl_estado.setText(m))

        self.pestanas = QTabWidget()
        self.pestanas.addTab(divisor, "Búsqueda diaria")
        self.pestanas.addTab(self.documentos, "Mis documentos")
        self.pestanas.currentChanged.connect(self._cambio_pestana)
        self.setCentralWidget(self.pestanas)

    def _cambio_pestana(self, _indice: int) -> None:
        # Una sola voz a la vez: cambiar de pestaña calla la otra.
        self._parar()
        self.documentos.parar()

    def _importar_documentos(self) -> None:
        self.pestanas.setCurrentWidget(self.documentos)
        self.documentos.importar_archivos()

    def _importar_carpeta(self) -> None:
        self.pestanas.setCurrentWidget(self.documentos)
        self.documentos.importar_carpeta()

    def _barra_audio_fija(self) -> QWidget:
        w = QFrame()
        w.setFrameShape(QFrame.Shape.StyledPanel)
        w.setStyleSheet("QFrame { background:#f4f6f8; border-top:1px solid #d8dee6; }")
        caja = QVBoxLayout(w)
        caja.setContentsMargins(18, 8, 18, 10)

        fila = QHBoxLayout()
        self.btn_escuchar = QPushButton("Escuchar el resumen")
        self.btn_escuchar.setEnabled(False)
        self.btn_escuchar.clicked.connect(self._escuchar_actual)
        self.btn_pausa = QPushButton("Pausa")
        self.btn_pausa.setEnabled(False)
        self.btn_pausa.clicked.connect(self._pausa)
        self.btn_parar = QPushButton("Parar")
        self.btn_parar.setEnabled(False)
        self.btn_parar.clicked.connect(self._parar)
        for b in (self.btn_escuchar, self.btn_pausa, self.btn_parar):
            fila.addWidget(b)
        fila.addStretch()
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        self.barra_audio = QSlider(Qt.Orientation.Horizontal)
        self.barra_audio.setEnabled(False)
        self.barra_audio.sliderMoved.connect(self._buscar_en_audio)
        caja.addWidget(self.barra_audio)
        return w

    def _construir_estado(self) -> None:
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(6, 0, 6, 0)

        self.lbl_estado = QLabel("Listo.")
        fila.addWidget(self.lbl_estado, 1)

        self.barra_progreso = QProgressBar()
        self.barra_progreso.setMaximumWidth(260)
        self.barra_progreso.setVisible(False)
        fila.addWidget(self.barra_progreso)

        self.statusBar().addPermanentWidget(contenedor, 1)

    # ------------------------------------------------------------------
    # Corridas
    # ------------------------------------------------------------------

    def lanzar_corrida(self, franja: str = "manual") -> None:
        if self._hilo_corrida is not None and self._hilo_corrida.isRunning():
            self.lbl_estado.setText("Ya hay una búsqueda en curso.")
            return

        self.act_buscar.setEnabled(False)
        self.barra_progreso.setVisible(True)
        self.barra_progreso.setValue(0)

        self._hilo_corrida = HiloCorrida(self.cfg, franja, self)
        self._hilo_corrida.progreso.connect(self._progreso_corrida)
        self._hilo_corrida.terminado.connect(self._corrida_lista)
        self._hilo_corrida.fallo.connect(self._corrida_fallo)
        self._hilo_corrida.start()

    def _progreso_corrida(self, mensaje: str, pct: int) -> None:
        self.lbl_estado.setText(mensaje)
        self.barra_progreso.setValue(pct)

    def _corrida_lista(self, resultado) -> None:
        self.act_buscar.setEnabled(True)
        self.barra_progreso.setVisible(False)
        scheduler.marcar_ejecutada(resultado.franja)

        if resultado.n_mostrados == 0:
            self.lbl_estado.setText(
                f"Nada nuevo entre {resultado.n_candidatos} candidatos. "
                "Prueba ampliando la ventana en Configuración > Ranking."
            )
        else:
            detalle = " | ".join(f"{k}: {v}" for k, v in resultado.estado_fuentes.items())
            self.lbl_estado.setText(
                f"{resultado.n_mostrados} papers listos de {resultado.n_candidatos} "
                f"candidatos. {detalle}"
            )
        if resultado.errores_resumen:
            log.warning("Errores de resumen: %s", resultado.errores_resumen)

        self.cargar_corrida(resultado.corrida_id)
        self.actualizar_proxima()
        self.corrida_terminada.emit(resultado)

    def _corrida_fallo(self, mensaje: str) -> None:
        self.act_buscar.setEnabled(True)
        self.barra_progreso.setVisible(False)
        self.lbl_estado.setText(f"La búsqueda falló: {mensaje}")
        QMessageBox.critical(self, "La búsqueda falló", mensaje)

    def recargar(self) -> None:
        """Relee la base y la configuración, sin reiniciar la app."""
        antes = self.corrida_id
        self.cfg = Config.cargar()
        self.salida.setVolume(self.cfg.volumen_voz / 100.0)
        self.cargar_ultima_corrida()
        self.documentos.actualizar_config(self.cfg)
        self.documentos.cargar()
        if self.corrida_id != antes:
            self.lbl_estado.setText(
                f"Recargado: corrida {self.corrida_id} con {len(self.filas)} papers."
            )
        else:
            self.lbl_estado.setText(
                f"Recargado: sigue siendo la corrida {self.corrida_id}, "
                f"{len(self.filas)} papers."
            )

    def cargar_ultima_corrida(self) -> None:
        db.inicializar()
        with db.conexion() as con:
            fila = db.ultima_corrida(con)
        if fila is None:
            self.lbl_estado.setText(
                "Todavía no hay ninguna búsqueda. Pulsa 'Buscar ahora' para la primera."
            )
            self.actualizar_proxima()
            return
        self.cargar_corrida(int(fila["id"]))
        self.actualizar_proxima()

    def cargar_corrida(self, corrida_id: int) -> None:
        """Pinta la corrida. Si es la misma que ya se ve, no mueve al lector.

        Se recarga la misma corrida al volver de Zotero, al generar un resumen
        o con F5. Antes eso dejaba la lista en el primer paper; ahora se
        conserva el paper que estás viendo (aunque no sea el que se envió:
        el envío tarda y puedes haber pasado a otro), el desplazamiento de la
        lista y el de la ficha. Solo una corrida nueva empieza arriba.
        """
        misma = corrida_id == self.corrida_id
        actual_id = None
        if misma and 0 <= self.actual < len(self.filas):
            actual_id = self.filas[self.actual]["id"]
        scroll_lista = self.lista.verticalScrollBar().value()
        scroll_ficha = self.scroll.verticalScrollBar().value()

        self.corrida_id = corrida_id
        with db.conexion() as con:
            self.filas = db.papers_de_corrida(con, corrida_id)

        # Sin señales mientras se rellena: clear() y setCurrentRow() dispararían
        # mostrar_paper con filas intermedias.
        self.lista.blockSignals(True)
        self.lista.clear()
        for fila in self.filas:
            self.lista.addItem(self._item_lista(fila))
        indice = next(
            (i for i, f in enumerate(self.filas) if f["id"] == actual_id), None
        )
        if self.filas:
            self.lista.setCurrentRow(indice if indice is not None else 0)
        self.lista.blockSignals(False)

        if not self.filas:
            self.actual = -1
            self._limpiar_panel()
            return
        self.mostrar_paper(self.lista.currentRow())
        if indice is not None:
            self.lista.verticalScrollBar().setValue(scroll_lista)
            reponer_desplazamiento(self.scroll.verticalScrollBar(), scroll_ficha)
        else:
            self.lista.scrollToTop()
            self.scroll.verticalScrollBar().setValue(0)

    def _item_lista(self, fila) -> QListWidgetItem:
        desglose = json.loads(fila["desglose"] or "{}")
        dominios = " ".join(desglose.get("dominios", [])[:3])
        tag = f"· {fila['trabajo']}" if fila["trabajo"] else ""
        marca = "*" if fila["marcado"] else ""
        leido = "" if fila["leido"] else "•"
        venue = (fila["venue"] or "sin venue")[:38]
        texto = (
            f"{leido} {fila['puesto']}. {fila['titulo'][:95]}\n"
            f"     {venue}  |  {fila['fecha_pub'] or fila['anio'] or ''}  |  "
            f"{fila['puntaje']:.3f}  |  {dominios} {tag} {marca}"
        )
        return QListWidgetItem(texto)

    # ------------------------------------------------------------------
    # Ficha del paper
    # ------------------------------------------------------------------

    def _limpiar_panel(self) -> None:
        while self.caja_panel.count():
            item = self.caja_panel.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def mostrar_paper(self, indice: int) -> None:
        self._limpiar_panel()
        self.actual = indice
        if not (0 <= indice < len(self.filas)):
            return

        fila = self.filas[indice]
        resumen = json.loads(fila["resumen_json"]) if fila["resumen_json"] else None
        desglose = json.loads(fila["desglose"] or "{}")

        # Título
        titulo_es = (resumen or {}).get("titulo_es") or fila["titulo"]
        lbl_titulo = QLabel(f"<h2 style='margin:0'>{titulo_es}</h2>")
        lbl_titulo.setWordWrap(True)
        self.caja_panel.addWidget(lbl_titulo)

        if resumen and resumen.get("titulo_es"):
            orig = QLabel(f"<i>{fila['titulo']}</i>")
            orig.setWordWrap(True)
            orig.setStyleSheet("color:#666; font-size:12px;")
            self.caja_panel.addWidget(orig)

        # Metadatos
        autores = json.loads(fila["autores"] or "[]")
        firma = ", ".join(autores[:5]) + (" y otros" if len(autores) > 5 else "")
        meta = (
            f"<b>{fila['venue'] or 'sin venue'}</b> ({fila['tipo_venue']}) &nbsp;|&nbsp; "
            f"{fila['fecha_pub'] or fila['anio'] or 'sin fecha'} &nbsp;|&nbsp; "
            f"{fila['citas']} citas &nbsp;|&nbsp; "
            f"fuentes: {', '.join(json.loads(fila['fuentes'] or '[]'))}"
        )
        lbl_meta = QLabel(meta + (f"<br>{firma}" if firma else ""))
        lbl_meta.setWordWrap(True)
        lbl_meta.setStyleSheet("color:#444; font-size:12px;")
        self.caja_panel.addWidget(lbl_meta)

        # Puntaje
        tag = fila["trabajo"]
        insignias = [
            f"<span style='background:#e3e9f0;padding:3px 8px;border-radius:10px;'>"
            f"puntaje {fila['puntaje']:.3f}</span>"
        ]
        # Los dominios van primero: son la razón real por la que el paper está
        # aquí. La etiqueta de tesis es un extra que puede no existir.
        claves = desglose.get("dominios") or []
        nombres = desglose.get("nombres_dominios") or []
        for i, clave in enumerate(claves[:4]):
            nombre = nombres[i] if i < len(nombres) else clave
            insignias.append(
                f"<span style='background:{COLOR_D.get(clave, '#607d8b')};color:white;"
                f"padding:3px 8px;border-radius:10px;'>{clave} {nombre}</span>"
            )
        if tag:
            insignias.append(
                f"<span style='background:{color_trabajo(tag)};color:white;"
                f"padding:3px 8px;border-radius:10px;'>toca {tag}</span>"
            )
        if resumen and resumen.get("veredicto"):
            v = resumen["veredicto"]
            insignias.append(
                f"<span style='background:{COLOR_VEREDICTO.get(v, '#555')};color:white;"
                f"padding:3px 8px;border-radius:10px;'>{v}</span>"
            )
        lbl_ins = QLabel(" &nbsp; ".join(insignias))
        lbl_ins.setTextFormat(Qt.TextFormat.RichText)
        self.caja_panel.addWidget(lbl_ins)

        explic = desglose.get("explicacion", {})
        if explic:
            detalle = QLabel(
                "Por qué salió: "
                + " &nbsp;·&nbsp; ".join(
                    f"{k}: {v}" for k, v in explic.items() if k != "pesos"
                )
            )
            detalle.setWordWrap(True)
            detalle.setStyleSheet("color:#777; font-size:11px;")
            self.caja_panel.addWidget(detalle)

        self.caja_panel.addWidget(self._separador())

        # Resumen
        if resumen:
            self.caja_panel.addWidget(
                _tarjeta(
                    f"<b>Por qué te importa</b><br>{resumen.get('por_que_te_importa', '')}",
                    "#fff6e5", "#e8c98a",
                )
            )
            for etiqueta, clave in (
                ("Qué hace", "que_hace"),
                ("Método", "metodo"),
                ("Hallazgo", "hallazgo"),
                ("Limitaciones", "limitaciones"),
            ):
                if resumen.get(clave):
                    self.caja_panel.addWidget(
                        _tarjeta(f"<b>{etiqueta}</b><br>{resumen[clave]}")
                    )

            aviso = QLabel(
                f"Resumen generado por IA ({fila['resumen_modelo']}). "
                "No citar este texto, verificar contra el original."
            )
            aviso.setWordWrap(True)
            aviso.setStyleSheet("color:#8a6d3b; font-size:11px; font-style:italic;")
            self.caja_panel.addWidget(aviso)
        else:
            self.caja_panel.addWidget(
                _tarjeta(
                    "<b>Sin resumen generado</b><br>" + (fila["resumen_origen"] or ""),
                    "#f2f2f2", "#ddd",
                )
            )

        self.caja_panel.addWidget(self._separador())
        self.caja_panel.addWidget(self._acciones(fila))
        self.caja_panel.addStretch()

        # La barra de voz es permanente; aquí solo se ajusta según el paper.
        # Si falta el resumen pero hay clave, el botón lo genera al vuelo en
        # vez de quedarse muerto.
        hay_voz = bool(resumen and resumen.get("texto_para_voz"))
        hay_clave = self.cfg.tiene_clave()
        self.btn_escuchar.setEnabled(hay_voz or hay_clave)
        if hay_voz:
            self.btn_escuchar.setText("Escuchar el resumen")
            self.btn_escuchar.setToolTip("")
        elif hay_clave:
            self.btn_escuchar.setText("Resumir y escuchar")
            self.btn_escuchar.setToolTip(
                "Este paper no se resumió cuando se buscó. Se genera ahora."
            )
        else:
            self.btn_escuchar.setText("Escuchar el resumen")
            self.btn_escuchar.setToolTip(
                "Falta el resumen y no hay clave de Claude cargada."
            )

        # Marcar como visto
        if not fila["leido"]:
            with db.conexion() as con:
                db.marcar(con, fila["id"], "leido", 1)

    def _separador(self) -> QFrame:
        linea = QFrame()
        linea.setFrameShape(QFrame.Shape.HLine)
        linea.setStyleSheet("color:#ddd;")
        return linea

    def _buscar_en_audio(self, posicion: int) -> None:
        self.reproductor.setPosition(posicion)

    def _acciones(self, fila) -> QWidget:
        w = QWidget()
        caja = QHBoxLayout(w)
        caja.setContentsMargins(0, 0, 0, 0)

        btn_pdf = QPushButton("Leer completo")
        btn_pdf.clicked.connect(lambda: self._leer_completo(fila))
        caja.addWidget(btn_pdf)

        btn_web = QPushButton("Abrir en el navegador")
        url = fila["url"] or (f"https://doi.org/{fila['doi']}" if fila["doi"] else "")
        btn_web.setEnabled(bool(url))
        btn_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        caja.addWidget(btn_web)

        ya = bool(fila["exportado_zotero"])
        btn_zotero = QPushButton("Ya está en Zotero" if ya else "Marcar útil y enviar a Zotero")
        btn_zotero.setEnabled(not ya)
        btn_zotero.clicked.connect(lambda: self._enviar_zotero(fila))
        caja.addWidget(btn_zotero)

        caja.addStretch()
        return w

    # ------------------------------------------------------------------
    # Voz
    # ------------------------------------------------------------------

    def _texto_voz(self, indice: int) -> str | None:
        if not (0 <= indice < len(self.filas)):
            return None
        fila = self.filas[indice]
        if not fila["resumen_json"]:
            return None
        resumen = json.loads(fila["resumen_json"])
        return resumen.get("texto_para_voz")

    def _escuchar_actual(self) -> None:
        self._cola_escucha = []
        self._reproducir_indice(self.actual)

    def _escuchar_todos(self) -> None:
        if not self.filas:
            return
        self._cola_escucha = list(range(1, len(self.filas)))
        self._reproducir_indice(0)

    def _reproducir_indice(self, indice: int) -> None:
        texto = self._texto_voz(indice)
        if not texto:
            # Falta el resumen: se genera ahora y se reproduce al terminar.
            self._resumir_y_luego_reproducir(indice)
            return
        if self.lista.currentRow() != indice:
            self.lista.setCurrentRow(indice)

        self.btn_escuchar.setEnabled(False)
        self.lbl_estado.setText("Sintetizando la voz...")

        clave = f"resumen|{self.filas[indice]['id']}"
        self._hilo_voz = HiloVoz(texto, clave, self.cfg, self)
        self._hilo_voz.terminado.connect(self._voz_lista)
        self._hilo_voz.fallo.connect(self._voz_fallo)
        self._hilo_voz.start()

    def _resumir_y_luego_reproducir(self, indice: int) -> None:
        if not (0 <= indice < len(self.filas)):
            return
        if not self.cfg.tiene_clave():
            self.lbl_estado.setText(
                "Falta el resumen y no hay clave de Claude. Cárgala en Configuración."
            )
            self._siguiente_de_la_cola()
            return

        fila = self.filas[indice]
        if self.lista.currentRow() != indice:
            self.lista.setCurrentRow(indice)

        paper = pipeline.paper_desde_fila(fila)
        desglose = json.loads(fila["desglose"] or "{}")
        puntaje = Puntaje(
            total=fila["puntaje"],
            relevancia=desglose.get("relevancia", 0.0),
            trabajo=fila["trabajo"],
            terminos_encontrados=desglose.get("terminos", []),
        )

        self.btn_escuchar.setEnabled(False)
        self.lbl_estado.setText(
            f"Generando el resumen que faltaba con {self.cfg.modelo_claude}..."
        )
        self._hilo_resumen = HiloResumen(paper, puntaje, self.cfg, self)
        self._hilo_resumen.terminado.connect(lambda _pid, _r: self._resumen_listo(indice))
        self._hilo_resumen.fallo.connect(self._resumen_fallo)
        self._hilo_resumen.start()

    def _resumen_listo(self, indice: int) -> None:
        # Recargar para que la ficha muestre el resumen recién creado.
        with db.conexion() as con:
            self.filas = db.papers_de_corrida(con, self.corrida_id)
        self.mostrar_paper(indice)
        self.lbl_estado.setText("Resumen listo, reproduciendo.")
        self._reproducir_indice(indice)

    def _resumen_fallo(self, mensaje: str) -> None:
        self.btn_escuchar.setEnabled(True)
        self.lbl_estado.setText(f"No se pudo resumir: {mensaje}")
        self._siguiente_de_la_cola()

    def _siguiente_de_la_cola(self) -> None:
        """Si estabas escuchando los cinco, no te quedes atorado en uno malo."""
        if self._cola_escucha:
            self._reproducir_indice(self._cola_escucha.pop(0))

    def _voz_lista(self, ruta: str, motor: str) -> None:
        with db.conexion() as con:
            if 0 <= self.actual < len(self.filas):
                db.marcar(con, self.filas[self.actual]["id"], "ruta_audio", ruta)
        self.reproductor.setSource(QUrl.fromLocalFile(ruta))
        self.reproductor.play()
        self.btn_escuchar.setEnabled(True)
        self.btn_pausa.setEnabled(True)
        self.btn_parar.setEnabled(True)
        self.barra_audio.setEnabled(True)
        restantes = f", faltan {len(self._cola_escucha)}" if self._cola_escucha else ""
        self.lbl_estado.setText(f"Reproduciendo (motor {motor}){restantes}.")

    def _voz_fallo(self, mensaje: str) -> None:
        self.btn_escuchar.setEnabled(True)
        self.lbl_estado.setText(f"No se pudo sintetizar: {mensaje}")

    def _pausa(self) -> None:
        if self.reproductor.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.reproductor.pause()
            self.btn_pausa.setText("Continuar")
        else:
            self.reproductor.play()
            self.btn_pausa.setText("Pausa")

    def _parar(self) -> None:
        self._cola_escucha = []
        self.reproductor.stop()
        self.btn_pausa.setEnabled(False)
        self.btn_parar.setEnabled(False)
        self.btn_pausa.setText("Pausa")

    def _mover_barra(self, pos: int) -> None:
        self.barra_audio.setValue(pos)

    def _fin_de_pista(self, estado) -> None:
        if estado != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._cola_escucha:
            siguiente = self._cola_escucha.pop(0)
            self._reproducir_indice(siguiente)
        else:
            self.btn_pausa.setEnabled(False)
            self.btn_parar.setEnabled(False)
            self.lbl_estado.setText("Fin de la reproducción.")

    # ------------------------------------------------------------------
    # PDF y Zotero
    # ------------------------------------------------------------------

    def _leer_completo(self, fila) -> None:
        existente = fila["ruta_pdf"]
        if existente and Path(existente).exists():
            self._abrir_lector(existente, fila["titulo"])
            return

        paper = pipeline.paper_desde_fila(fila)
        if not paper.url_pdf:
            QMessageBox.information(
                self, "Sin PDF abierto",
                "Este trabajo no tiene PDF de acceso abierto conocido. "
                "Usa 'Abrir en el navegador' para llegar a la página del editor.",
            )
            return

        self.lbl_estado.setText("Descargando el PDF...")
        self._hilo_pdf = HiloPDF(paper, self.cfg.dir_biblioteca, self)
        self._hilo_pdf.terminado.connect(
            lambda ruta: self._pdf_listo(ruta, fila["id"], fila["titulo"])
        )
        self._hilo_pdf.fallo.connect(
            lambda m: (
                self.lbl_estado.setText(f"No se pudo descargar: {m}"),
                QMessageBox.warning(self, "No se pudo descargar el PDF", m),
            )
        )
        self._hilo_pdf.start()

    def _pdf_listo(self, ruta: str, paper_id: str, titulo: str) -> None:
        with db.conexion() as con:
            db.marcar(con, paper_id, "ruta_pdf", ruta)
        self.lbl_estado.setText(f"PDF guardado en {ruta}")
        self._abrir_lector(ruta, titulo)

    def _abrir_lector(self, ruta: str, titulo: str) -> None:
        lector = VentanaLector(Path(ruta), titulo, self.cfg, self)
        lector.exec()

    def _enviar_zotero(self, fila) -> None:
        paper = pipeline.paper_desde_fila(fila)
        resumen = json.loads(fila["resumen_json"]) if fila["resumen_json"] else None
        desglose = json.loads(fila["desglose"] or "{}")

        item = zotero.construir_item(
            paper, resumen, fila["resumen_modelo"] or self.cfg.modelo_claude,
            fila["trabajo"], desglose,
        )

        with db.conexion() as con:
            db.marcar(con, fila["id"], "marcado", 1)
            cola_id = db.encolar_zotero(con, fila["id"], item)

        self.lbl_estado.setText("Enviando a Zotero...")
        self._hilo_zotero = HiloZotero(self.cfg, item, True, self)
        self._hilo_zotero.progreso.connect(self.lbl_estado.setText)
        self._hilo_zotero.terminado.connect(
            lambda m: self._zotero_ok(m, fila["id"], cola_id)
        )
        self._hilo_zotero.falta_subcoleccion.connect(
            lambda msg: self._zotero_falta_coleccion(msg, item, fila["id"], cola_id)
        )
        self._hilo_zotero.fallo.connect(lambda m: self._zotero_fallo(m, cola_id))
        self._hilo_zotero.start()

    def _zotero_ok(self, mensaje: str, paper_id: str, cola_id: int) -> None:
        with db.conexion() as con:
            db.marcar(con, paper_id, "exportado_zotero", db.ahora())
            db.cerrar_item_cola(con, cola_id, True)
        self.lbl_estado.setText(mensaje)
        self.cargar_corrida(self.corrida_id)

    def _zotero_falta_coleccion(
        self, instrucciones: str, item: dict, paper_id: str, cola_id: int
    ) -> None:
        """La subcolección destino no existe. El conector no puede crearla."""
        respuesta = QMessageBox.question(
            self,
            "Falta crear la subcolección",
            f"{instrucciones}\n\n"
            "Créala en Zotero y pulsa Reintentar, o guarda de todos modos en la "
            "colección que tengas seleccionada (el ítem llevará la etiqueta "
            "PHDjournal para que lo encuentres siempre).",
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Cancel,
        )
        if respuesta == QMessageBox.StandardButton.Cancel:
            self.lbl_estado.setText(
                "Exportación cancelada. Queda en la cola para el próximo intento."
            )
            return

        dirigir = respuesta == QMessageBox.StandardButton.Retry
        self._hilo_zotero = HiloZotero(self.cfg, item, dirigir, self)
        self._hilo_zotero.terminado.connect(
            lambda m: self._zotero_ok(m, paper_id, cola_id)
        )
        if dirigir:
            self._hilo_zotero.falta_subcoleccion.connect(
                lambda msg: self._zotero_falta_coleccion(msg, item, paper_id, cola_id)
            )
        self._hilo_zotero.fallo.connect(lambda m: self._zotero_fallo(m, cola_id))
        self._hilo_zotero.start()

    def _zotero_fallo(self, mensaje: str, cola_id: int) -> None:
        with db.conexion() as con:
            db.cerrar_item_cola(con, cola_id, False, mensaje)
        self.lbl_estado.setText(f"Zotero: {mensaje}")
        QMessageBox.warning(
            self, "No se pudo exportar a Zotero",
            f"{mensaje}\n\nEl ítem quedó en la cola y se reintentará. "
            "Nada se perdió.",
        )

    # ------------------------------------------------------------------

    def abrir_config(self) -> None:
        dlg = DialogoConfig(self.cfg, self)
        if dlg.exec():
            self.cfg = Config.cargar()
            self.salida.setVolume(self.cfg.volumen_voz / 100.0)
            self.documentos.actualizar_config(self.cfg)
            self.actualizar_proxima()
            self.lbl_estado.setText("Configuración guardada.")

    def actualizar_proxima(self) -> None:
        try:
            self.lbl_proxima.setText(
                "Próxima búsqueda: " + scheduler.proxima_descripcion(self.cfg)
            )
        except Exception:
            self.lbl_proxima.setText("")

    def closeEvent(self, evento) -> None:  # noqa: N802
        """Cerrar la ventana no mata la app: se esconde en la bandeja."""
        self.reproductor.stop()
        self.documentos.parar()
        evento.ignore()
        self.hide()
