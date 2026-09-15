"""Pantalla de Temas: qué busca la app.

Tres diálogos:

* ``DialogoTemas``, la lista de temas con sus interruptores.
* ``DialogoTerminos``, la tabla de términos y pesos de un tema.
* ``DialogoNuevoTema``, que describe un tema en lenguaje natural y deja que
  Claude proponga los términos.

Y el que más importa, ``DialogoPrueba``: rankea los candidatos de la última
corrida con el perfil editado, **sin red y sin gastar en la API**, y enseña
qué entraría y qué saldría. Existe porque durante el desarrollo la puerta se
configuró mal dos veces y cada error costó una corrida real para descubrirlo.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import pipeline, profile, ranking, summarize, temas
from .. import trabajos as trabajos_mod
from ..config import Config

log = logging.getLogger(__name__)

CAPAS = [
    ("nucleo", "Núcleo, define tu especialidad"),
    ("puente", "Puente, conecta con tu tesis"),
    ("soporte", "Soporte, metodología y contexto"),
]


# ---------------------------------------------------------------------------
# Hilo del asistente
# ---------------------------------------------------------------------------

class HiloTema(QThread):
    terminado = Signal(object)
    fallo = Signal(str)

    def __init__(self, descripcion: str, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.descripcion = descripcion
        self.cfg = cfg

    def run(self) -> None:
        try:
            self.terminado.emit(summarize.generar_tema(self.descripcion, self.cfg))
        except Exception as exc:
            self.fallo.emit(str(exc))


# ---------------------------------------------------------------------------
# Editor de términos
# ---------------------------------------------------------------------------

class DialogoTerminos(QDialog):
    def __init__(self, nombre: str, terminos: dict[str, float], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Términos de {nombre}")
        self.resize(560, 620)

        caja = QVBoxLayout(self)
        ayuda = QLabel(
            "Los términos se buscan en el título y el resumen. En el título "
            "valen el triple.\n\n"
            "Peso 3.0 o más para lo que identifique el tema por sí solo; 1.0 a "
            "2.0 para lo que solo acompaña. Usa frases: una palabra suelta como "
            "\"edge\" captura \"nodes and edges\" de cualquier paper de grafos."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color:#666;")
        caja.addWidget(ayuda)

        # lbl_n se crea ANTES de poblar la tabla: _fila llama a _contar, que lo
        # usa. Crearlo después daba AttributeError al abrir el diálogo.
        self.lbl_n = QLabel()

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Término (en inglés)", "Peso"])
        self.tabla.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for t, p in sorted(terminos.items(), key=lambda x: (-x[1], x[0])):
            self._fila(t, p)
        caja.addWidget(self.tabla, 1)

        fila = QHBoxLayout()
        b_add = QPushButton("Añadir")
        b_add.clicked.connect(lambda: self._fila("", 2.0))
        b_del = QPushButton("Quitar seleccionado")
        b_del.clicked.connect(self._quitar)
        fila.addWidget(b_add)
        fila.addWidget(b_del)
        fila.addStretch()
        fila.addWidget(self.lbl_n)
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        caja.addWidget(botones)
        self._contar()

    def _fila(self, termino: str, peso: float) -> None:
        f = self.tabla.rowCount()
        self.tabla.insertRow(f)
        self.tabla.setItem(f, 0, QTableWidgetItem(termino))
        sp = QDoubleSpinBox()
        sp.setRange(0.1, 5.0)
        sp.setSingleStep(0.5)
        sp.setDecimals(1)
        sp.setValue(float(peso))
        self.tabla.setCellWidget(f, 1, sp)
        self._contar()

    def _quitar(self) -> None:
        for f in sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True):
            self.tabla.removeRow(f)
        self._contar()

    def _contar(self) -> None:
        self.lbl_n.setText(f"{self.tabla.rowCount()} términos")

    def terminos(self) -> dict[str, float]:
        salida: dict[str, float] = {}
        for f in range(self.tabla.rowCount()):
            item = self.tabla.item(f, 0)
            sp = self.tabla.cellWidget(f, 1)
            t = (item.text() if item else "").strip().lower()
            if t and sp is not None:
                salida[t] = float(sp.value())
        return salida


# ---------------------------------------------------------------------------
# Tema nuevo con asistente
# ---------------------------------------------------------------------------

class DialogoNuevoTema(QDialog):
    """Sirve para temas y para trabajos propios.

    En modo trabajo se ocultan la capa y la casilla de la puerta, que no
    aplican: un trabajo solo etiqueta.
    """

    def __init__(self, cfg: Config, parent=None, modo_trabajo: bool = False) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.modo_trabajo = modo_trabajo
        self.propuesta: dict | None = None
        self._hilo: HiloTema | None = None

        self.setWindowTitle("Trabajo nuevo" if modo_trabajo else "Tema nuevo")
        self.resize(660, 640)
        caja = QVBoxLayout(self)

        caja.addWidget(QLabel(
            "<b>Describe tu trabajo</b>" if modo_trabajo
            else "<b>Describe el tema que quieres seguir</b>"
        ))
        self.txt = QPlainTextEdit()
        self.txt.setPlaceholderText(
            "Por ejemplo: un paper sobre cuantización INT4 de modelos pequeños "
            "con grafos de conocimiento sobre Jetson y Raspberry Pi."
            if modo_trabajo else
            "Por ejemplo: aprendizaje federado en dispositivos del borde, "
            "sobre todo la parte de agregación segura y de deriva entre clientes."
        )
        self.txt.setMaximumHeight(110)
        caja.addWidget(self.txt)

        fila = QHBoxLayout()
        self.btn_gen = QPushButton("Proponer términos con Claude")
        self.btn_gen.clicked.connect(self._generar)
        fila.addWidget(self.btn_gen)
        self.lbl_estado = QLabel("")
        self.lbl_estado.setStyleSheet("color:#666;")
        fila.addWidget(self.lbl_estado, 1)
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        form = QFormLayout()
        self.ed_nombre = QLineEdit()
        form.addRow("Nombre del trabajo:" if modo_trabajo else "Nombre del tema:",
                    self.ed_nombre)

        self.ed_nota = QLineEdit()
        self.ed_nota.setPlaceholderText("Estado o contexto, opcional")
        self.cb_capa = QComboBox()
        for c, d in CAPAS:
            self.cb_capa.addItem(d, c)
        self.ck_abre = QCheckBox("Este tema, por sí solo, basta para traerme un paper")
        self.ck_abre.setChecked(True)
        nota = QLabel(
            "Déjala marcada. Un tema que no abre solo puede sumar puntos a "
            "papers que ya entraron por otra vía, así que nacería inerte."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color:#666; font-size:11px;")

        if modo_trabajo:
            form.addRow("Nota:", self.ed_nota)
        else:
            form.addRow("Capa:", self.cb_capa)
            form.addRow("", self.ck_abre)
            form.addRow("", nota)
        w = QWidget()
        w.setLayout(form)
        caja.addWidget(w)

        caja.addWidget(QLabel("<b>Términos propuestos</b> (revísalos y quita lo que sobre)"))
        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Término", "Peso"])
        self.tabla.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        caja.addWidget(self.tabla, 1)

        b_del = QPushButton("Quitar seleccionado")
        b_del.clicked.connect(self._quitar)
        caja.addWidget(b_del)

        self.lbl_aviso = QLabel("")
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet("color:#8a6d3b;")
        caja.addWidget(self.lbl_aviso)

        self.botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setText("Crear tema")
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.botones.accepted.connect(self.accept)
        self.botones.rejected.connect(self.reject)
        caja.addWidget(self.botones)

    def _generar(self) -> None:
        desc = self.txt.toPlainText().strip()
        if len(desc) < 10:
            QMessageBox.warning(self, "Falta la descripción", "Describe el tema primero.")
            return
        if not self.cfg.tiene_clave():
            QMessageBox.warning(
                self, "Sin clave",
                "Carga la clave de Claude en la pestaña Claude, o escribe los "
                "términos a mano después de crear el tema.",
            )
            return
        self.btn_gen.setEnabled(False)
        self.lbl_estado.setText("Pensando...")
        self._hilo = HiloTema(desc, self.cfg, self)
        self._hilo.terminado.connect(self._listo)
        self._hilo.fallo.connect(self._fallo)
        self._hilo.start()

    def _listo(self, propuesta: dict) -> None:
        self.propuesta = propuesta
        self.btn_gen.setEnabled(True)
        self.lbl_estado.setText("Propuesta lista, revísala.")
        self.ed_nombre.setText(propuesta.get("nombre", ""))
        i = self.cb_capa.findData(propuesta.get("capa", "nucleo"))
        if i >= 0:
            self.cb_capa.setCurrentIndex(i)

        self.tabla.setRowCount(0)
        for t in propuesta.get("terminos", []):
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self.tabla.setItem(f, 0, QTableWidgetItem(str(t.get("termino", ""))))
            sp = QDoubleSpinBox()
            sp.setRange(0.1, 5.0)
            sp.setSingleStep(0.5)
            sp.setDecimals(1)
            sp.setValue(float(t.get("peso", 2.0)))
            self.tabla.setCellWidget(f, 1, sp)

        aviso = (propuesta.get("advertencia") or "").strip()
        self.lbl_aviso.setText(f"Aviso de Claude: {aviso}" if aviso else "")
        self.botones.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.tabla.rowCount() > 0
        )

    def _fallo(self, mensaje: str) -> None:
        self.btn_gen.setEnabled(True)
        self.lbl_estado.setText("")
        QMessageBox.critical(self, "No se pudo generar", mensaje)

    def _quitar(self) -> None:
        for f in sorted({i.row() for i in self.tabla.selectedIndexes()}, reverse=True):
            self.tabla.removeRow(f)

    def resultado(self) -> dict:
        terminos: dict[str, float] = {}
        for f in range(self.tabla.rowCount()):
            item = self.tabla.item(f, 0)
            sp = self.tabla.cellWidget(f, 1)
            t = (item.text() if item else "").strip().lower()
            if t and sp is not None:
                terminos[t] = float(sp.value())
        p = self.propuesta or {}
        return {
            "nombre": self.ed_nombre.text().strip() or (
                "Trabajo sin nombre" if self.modo_trabajo else "Tema sin nombre"
            ),
            "nota": self.ed_nota.text().strip(),
            "capa": self.cb_capa.currentData(),
            "abre": self.ck_abre.isChecked(),
            "terminos": terminos,
            "consultas_texto": p.get("consultas_texto") or [],
            "consultas_arxiv": p.get("consultas_arxiv") or [],
        }


# ---------------------------------------------------------------------------
# Banco de pruebas
# ---------------------------------------------------------------------------

class DialogoPrueba(QDialog):
    def __init__(self, cfg: Config, overlay: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Banco de pruebas")
        self.resize(940, 680)
        caja = QVBoxLayout(self)

        candidatos = pipeline.cargar_candidatos()
        if not candidatos:
            caja.addWidget(QLabel(
                "Todavía no hay candidatos guardados. Haz una búsqueda y vuelve: "
                "la app cachea los candidatos de la última corrida para poder "
                "probar aquí sin gastar nada."
            ))
            return

        antes = ranking.ordenar(candidatos, cfg, perfil=temas.construir({}))
        despues = ranking.ordenar(candidatos, cfg, perfil=temas.construir(overlay))

        ids_antes = {p.id for p, _ in antes}
        ids_despues = {p.id for p, _ in despues}
        entran = [(p, s) for p, s in despues if p.id not in ids_antes]
        salen = [(p, s) for p, s in antes if p.id not in ids_despues]

        resumen = QLabel(
            f"<b>{len(candidatos)}</b> candidatos de la última corrida.<br>"
            f"Con el perfil de fábrica pasaban <b>{len(antes)}</b>; "
            f"con tus cambios pasan <b>{len(despues)}</b>.<br>"
            f"<span style='color:#2e7d32'>Entran {len(entran)}</span> &nbsp;·&nbsp; "
            f"<span style='color:#c62828'>Salen {len(salen)}</span>"
        )
        resumen.setTextFormat(Qt.TextFormat.RichText)
        caja.addWidget(resumen)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["", "Puntaje", "Temas", "Paper"])
        self.tabla.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.tabla.setColumnWidth(0, 62)
        self.tabla.setColumnWidth(1, 70)
        self.tabla.setColumnWidth(2, 130)

        for p, s in entran[:60]:
            self._fila("entra", "#2e7d32", p, s)
        for p, s in salen[:60]:
            self._fila("sale", "#c62828", p, s)
        if not entran and not salen:
            self._fila("=", "#666", None, None, "Tus cambios no alteran qué entra.")
        caja.addWidget(self.tabla, 1)

        top = QLabel("<b>Los 10 primeros con tus cambios</b>")
        caja.addWidget(top)
        self.tabla2 = QTableWidget(0, 4)
        self.tabla2.setHorizontalHeaderLabels(["#", "Puntaje", "Temas", "Paper"])
        self.tabla2.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.tabla2.setColumnWidth(0, 36)
        self.tabla2.setColumnWidth(1, 70)
        self.tabla2.setColumnWidth(2, 130)
        for i, (p, s) in enumerate(despues[: cfg.papers_por_corrida], start=1):
            f = self.tabla2.rowCount()
            self.tabla2.insertRow(f)
            self.tabla2.setItem(f, 0, QTableWidgetItem(str(i)))
            self.tabla2.setItem(f, 1, QTableWidgetItem(f"{s.total:.3f}"))
            self.tabla2.setItem(f, 2, QTableWidgetItem(" ".join(s.dominios)))
            self.tabla2.setItem(f, 3, QTableWidgetItem(p.titulo[:110]))
        caja.addWidget(self.tabla2, 1)

        nota = QLabel(
            "Esta prueba no llama a la API ni a la red: usa los candidatos ya "
            "descargados. No cuesta nada repetirla."
        )
        nota.setStyleSheet("color:#666; font-size:11px;")
        caja.addWidget(nota)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.reject)
        botones.accepted.connect(self.accept)
        caja.addWidget(botones)

    def _fila(self, etiqueta, color, paper, puntaje, texto=None) -> None:
        f = self.tabla.rowCount()
        self.tabla.insertRow(f)
        it = QTableWidgetItem(etiqueta)
        it.setForeground(Qt.GlobalColor.black)
        self.tabla.setItem(f, 0, it)
        self.tabla.setItem(
            f, 1, QTableWidgetItem(f"{puntaje.total:.3f}" if puntaje else "")
        )
        self.tabla.setItem(
            f, 2, QTableWidgetItem(" ".join(puntaje.dominios) if puntaje else "")
        )
        self.tabla.setItem(
            f, 3, QTableWidgetItem(texto or (paper.titulo[:110] if paper else ""))
        )


# ---------------------------------------------------------------------------
# Mis trabajos
# ---------------------------------------------------------------------------

class DialogoTrabajos(QDialog):
    """Los trabajos propios del investigador: papers, capítulos, proyectos.

    A diferencia de los temas, estos **solo etiquetan**: no abren la puerta, no
    pesan en el puntaje y no generan consultas. Sirven para que la ficha diga
    "esto toca tu trabajo T2" y para que el resumen conecte con lo que estás
    escribiendo.
    """

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.trabajos = trabajos_mod.cargar()

        self.setWindowTitle("Mis trabajos")
        self.resize(820, 560)
        caja = QVBoxLayout(self)

        intro = QLabel(
            "Tus papers, capítulos o proyectos en curso. La app etiqueta cada "
            "paper que llega con el trabajo tuyo al que toca, y se lo dice a "
            "Claude para que el resumen conecte con lo que estás escribiendo.<br><br>"
            "<b>No influyen en el puntaje ni en la búsqueda.</b> Solo etiquetan, "
            "y \"sin etiqueta\" es una respuesta válida."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        caja.addWidget(intro)

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(
            ["Activo", "Clave", "Nombre", "Nota", "Términos"]
        )
        self.tabla.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        caja.addWidget(self.tabla, 1)

        fila = QHBoxLayout()
        for texto, fn in (
            ("Nuevo trabajo", self._nuevo),
            ("Editar términos", self._editar),
            ("Renombrar", self._renombrar),
            ("Borrar", self._borrar),
        ):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            fila.addWidget(b)
        fila.addStretch()
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        self.lbl_vacio = QLabel()
        self.lbl_vacio.setWordWrap(True)
        self.lbl_vacio.setStyleSheet("color:#666;")
        caja.addWidget(self.lbl_vacio)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        caja.addWidget(botones)

        self._pintar()

    def _pintar(self) -> None:
        self.tabla.setRowCount(0)
        self._claves: list[str] = []
        for clave, t in self.trabajos.items():
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self._claves.append(clave)

            ck = QCheckBox()
            ck.setChecked(t.activo)
            ck.stateChanged.connect(
                lambda _s, c=clave, w=ck: setattr(self.trabajos[c], "activo", w.isChecked())
            )
            self.tabla.setCellWidget(f, 0, ck)
            self.tabla.setItem(f, 1, QTableWidgetItem(clave))
            self.tabla.setItem(f, 2, QTableWidgetItem(t.nombre))
            self.tabla.setItem(f, 3, QTableWidgetItem(t.nota))
            self.tabla.setItem(f, 4, QTableWidgetItem(str(len(t.terminos))))

        self.lbl_vacio.setText(
            "Todavía no has declarado ningún trabajo. Pulsa 'Nuevo trabajo' y "
            "describe uno en una frase; Claude propone los términos."
            if not self.trabajos else ""
        )

    def _clave_sel(self) -> str | None:
        f = self.tabla.currentRow()
        if 0 <= f < len(self._claves):
            return self._claves[f]
        QMessageBox.information(self, "Elige un trabajo", "Selecciona una fila primero.")
        return None

    def _nuevo(self) -> None:
        dlg = DialogoNuevoTema(self.cfg, self, modo_trabajo=True)
        if not dlg.exec():
            return
        r = dlg.resultado()
        if not r["terminos"]:
            QMessageBox.warning(self, "Sin términos", "El trabajo necesita términos.")
            return
        clave = trabajos_mod.crear(
            self.trabajos, r["nombre"], r["terminos"], r.get("nota", "")
        )
        self._pintar()
        QMessageBox.information(
            self, "Trabajo creado",
            f"Creado como {clave} con {len(r['terminos'])} términos.",
        )

    def _editar(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        t = self.trabajos[clave]
        dlg = DialogoTerminos(t.nombre, t.terminos, self)
        if dlg.exec():
            t.terminos = dlg.terminos()
            self._pintar()

    def _renombrar(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        t = self.trabajos[clave]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Renombrar {clave}")
        form = QFormLayout(dlg)
        ed_nombre = QLineEdit(t.nombre)
        ed_nombre.setMinimumWidth(420)
        ed_nota = QLineEdit(t.nota)
        ed_nota.setPlaceholderText("Estado o contexto, opcional")
        form.addRow("Nombre:", ed_nombre)
        form.addRow("Nota:", ed_nota)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            t.nombre = ed_nombre.text().strip() or t.nombre
            t.nota = ed_nota.text().strip()
            self._pintar()

    def _borrar(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        if QMessageBox.question(
            self, "Borrar trabajo",
            f"¿Borrar {clave}, {self.trabajos[clave].nombre}?\n\n"
            "Los papers ya etiquetados con él conservan la etiqueta.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.trabajos.pop(clave, None)
        self._pintar()

    def _guardar(self) -> None:
        trabajos_mod.guardar(self.trabajos)
        self.accept()


# ---------------------------------------------------------------------------
# Lista de temas
# ---------------------------------------------------------------------------

class DialogoTemas(QDialog):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.overlay = temas.cargar_overlay()

        self.setWindowTitle("Temas de investigación")
        self.resize(940, 620)
        caja = QVBoxLayout(self)

        intro = QLabel(
            "Estos temas deciden <b>qué se busca</b> y <b>cómo se ordena</b>. "
            "Apagar un tema también deja de buscarlo, no solo de puntuarlo."
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setWordWrap(True)
        caja.addWidget(intro)

        self.tabla = QTableWidget(0, 7)
        self.tabla.setHorizontalHeaderLabels(
            ["Activo", "Clave", "Nombre", "Capa", "Peso", "Abre solo", "Términos"]
        )
        self.tabla.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        caja.addWidget(self.tabla, 1)

        ayuda = QLabel(
            "<b>Abre solo</b>: si está marcado, ese tema basta para traer un paper. "
            "Si no, el tema suma puntos pero solo acompañando a otro que sí abra.<br>"
            "Los temas de borde y de eficiencia vienen sin marcar a propósito: al "
            "activarlos entraron acelerómetros, tráfico de red y modelos "
            "hiperespectrales, que comparten vocabulario pero no problema."
        )
        ayuda.setTextFormat(Qt.TextFormat.RichText)
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color:#666; font-size:11px;")
        caja.addWidget(ayuda)

        fila = QHBoxLayout()
        for texto, fn in (
            ("Editar términos", self._editar),
            ("Tema nuevo", self._nuevo),
            ("Quitar", self._quitar),
            ("Restaurar este", self._restaurar_uno),
            ("Restaurar todo", self._restaurar_todo),
        ):
            b = QPushButton(texto)
            b.clicked.connect(fn)
            fila.addWidget(b)
        fila.addStretch()
        b_trabajos = QPushButton("Mis trabajos...")
        b_trabajos.setToolTip("Tus papers y proyectos propios, que solo etiquetan.")
        b_trabajos.clicked.connect(lambda: DialogoTrabajos(self.cfg, self).exec())
        fila.addWidget(b_trabajos)

        b_probar = QPushButton("Probar cambios")
        b_probar.setToolTip("Rankea los candidatos ya descargados. No gasta nada.")
        b_probar.clicked.connect(self._probar)
        fila.addWidget(b_probar)
        cont = QWidget()
        cont.setLayout(fila)
        caja.addWidget(cont)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        caja.addWidget(botones)

        self._pintar()

    # ------------------------------------------------------------------

    def _pintar(self) -> None:
        perfil = temas.construir(self.overlay)
        self.tabla.setRowCount(0)
        self._claves: list[str] = []

        for clave, dom in perfil.todos.items():
            ajuste = (self.overlay.get("dominios", {}) or {}).get(clave, {}) or {}
            activo = ajuste.get("activo", True)
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self._claves.append(clave)

            ck = QCheckBox()
            ck.setChecked(bool(activo))
            ck.stateChanged.connect(
                lambda _s, c=clave, w=ck: temas.fijar(
                    self.overlay, c, "activo", w.isChecked()
                )
            )
            self.tabla.setCellWidget(f, 0, ck)

            propio = clave not in profile.DOMINIOS
            self.tabla.setItem(f, 1, QTableWidgetItem(clave + (" *" if propio else "")))
            self.tabla.setItem(f, 2, QTableWidgetItem(dom.nombre))

            cb = QComboBox()
            for c, d in CAPAS:
                cb.addItem(d.split(",")[0], c)
            i = cb.findData(dom.capa)
            if i >= 0:
                cb.setCurrentIndex(i)
            cb.currentIndexChanged.connect(
                lambda _i, c=clave, w=cb: temas.fijar(
                    self.overlay, c, "capa", w.currentData()
                )
            )
            self.tabla.setCellWidget(f, 3, cb)

            sp = QDoubleSpinBox()
            sp.setRange(0.1, 2.0)
            sp.setSingleStep(0.1)
            sp.setDecimals(2)
            sp.setValue(dom.peso)
            sp.valueChanged.connect(
                lambda v, c=clave: temas.fijar(self.overlay, c, "peso", float(v))
            )
            self.tabla.setCellWidget(f, 4, sp)

            ck2 = QCheckBox()
            ck2.setChecked(clave in perfil.abren)
            ck2.stateChanged.connect(
                lambda _s, c=clave, w=ck2: temas.fijar(
                    self.overlay, c, "abre", w.isChecked()
                )
            )
            self.tabla.setCellWidget(f, 5, ck2)

            self.tabla.setItem(f, 6, QTableWidgetItem(str(len(dom.terminos))))

    def _clave_sel(self) -> str | None:
        f = self.tabla.currentRow()
        if 0 <= f < len(self._claves):
            return self._claves[f]
        QMessageBox.information(self, "Elige un tema", "Selecciona una fila primero.")
        return None

    def _editar(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        perfil = temas.construir(self.overlay)
        dom = perfil.todos[clave]
        dlg = DialogoTerminos(dom.nombre, dom.terminos, self)
        if dlg.exec():
            temas.set_terminos(self.overlay, clave, dlg.terminos())
            self._pintar()

    def _nuevo(self) -> None:
        dlg = DialogoNuevoTema(self.cfg, self)
        if not dlg.exec():
            return
        r = dlg.resultado()
        if not r["terminos"]:
            QMessageBox.warning(self, "Sin términos", "El tema necesita términos.")
            return
        clave = temas.crear_tema(
            self.overlay, r["nombre"], r["terminos"], r["capa"], 1.0, r["abre"],
            r["consultas_arxiv"], r["consultas_texto"],
        )
        self._pintar()
        QMessageBox.information(
            self, "Tema creado",
            f"Creado como {clave} con {len(r['terminos'])} términos.\n\n"
            "Pulsa 'Probar cambios' para ver qué traería antes de guardar.",
        )

    def _quitar(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        propio = clave not in profile.DOMINIOS
        msg = (
            f"¿Borrar el tema {clave}?" if propio
            else f"{clave} es un tema de fábrica y no se puede borrar.\n\n"
                 "¿Lo apago? Deja de buscarse y de puntuar, y puedes reactivarlo."
        )
        if QMessageBox.question(self, "Quitar tema", msg) != QMessageBox.StandardButton.Yes:
            return
        temas.borrar_tema(self.overlay, clave)
        self._pintar()

    def _restaurar_uno(self) -> None:
        clave = self._clave_sel()
        if not clave:
            return
        if clave not in profile.DOMINIOS:
            QMessageBox.information(
                self, "Es tuyo", "Este tema no es de fábrica; no hay a qué restaurarlo."
            )
            return
        temas.restaurar_tema(self.overlay, clave)
        self._pintar()

    def _restaurar_todo(self) -> None:
        if QMessageBox.question(
            self, "Restaurar todo",
            "Se pierden todos tus cambios de temas y se vuelve al perfil de "
            "fábrica. ¿Continuar?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.overlay = temas.restaurar_todo(self.overlay)
        self._pintar()

    def _probar(self) -> None:
        DialogoPrueba(self.cfg, self.overlay, self).exec()

    def _guardar(self) -> None:
        perfil = temas.construir(self.overlay)
        if not perfil.dominios:
            QMessageBox.warning(
                self, "Sin temas activos",
                "Al menos un tema tiene que estar activo o no se buscará nada.",
            )
            return
        temas.guardar_overlay(self.overlay)
        self.accept()
