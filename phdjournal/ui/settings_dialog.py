"""Pantalla de configuración.

Seis pestañas: Claude, Horarios, Ranking, Voz, Zotero y Fuentes. La clave de
la API se escribe aquí y se guarda cifrada con DPAPI; el campo nunca muestra
la clave guardada, solo si hay una o no.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSlider, QSpinBox, QTabWidget, QTimeEdit,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import QTime

from .. import summarize, tts, zotero
from ..config import Config

log = logging.getLogger(__name__)

MODELOS = [
    ("claude-opus-5", "Opus 5, el más capaz"),
    ("claude-sonnet-5", "Sonnet 5, equilibrado"),
    ("claude-haiku-4-5", "Haiku 4.5, el más barato"),
]

FUENTES = [
    ("arxiv", "arXiv, preprints, lo primero que aparece"),
    ("openalex", "OpenAlex, metadatos de IEEE, ACM, Elsevier y Springer"),
    ("semantic_scholar", "Semantic Scholar, citas influyentes"),
    ("crossref", "Crossref, confirma publicación formal"),
]


class DialogoConfig(QDialog):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Configuración de PHDjournal")
        self.setMinimumSize(640, 560)

        pestanas = QTabWidget()
        pestanas.addTab(self._tab_temas(), "Temas")
        pestanas.addTab(self._tab_claude(), "Claude")
        pestanas.addTab(self._tab_horarios(), "Horarios")
        pestanas.addTab(self._tab_ranking(), "Ranking")
        pestanas.addTab(self._tab_voz(), "Voz")
        pestanas.addTab(self._tab_zotero(), "Zotero")
        pestanas.addTab(self._tab_fuentes(), "Fuentes")

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        botones.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)

        caja = QVBoxLayout(self)
        caja.addWidget(pestanas)
        caja.addWidget(botones)

    # ------------------------------------------------------------------
    # Temas
    # ------------------------------------------------------------------

    def _tab_temas(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)

        self.lbl_temas = QLabel()
        self.lbl_temas.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_temas.setWordWrap(True)
        caja.addWidget(self.lbl_temas)

        btn = QPushButton("Administrar temas de investigación...")
        btn.clicked.connect(self._abrir_temas)
        caja.addWidget(btn)

        nota = QLabel(
            "Los temas deciden qué papers entran al feed y en qué orden. "
            "Vienen configurados para NLP en el borde, y puedes encenderlos, "
            "apagarlos, editarles los términos o crear temas nuevos "
            "describiéndolos en una frase.\n\n"
            "Tus cambios se guardan aparte, en data\\temas.json, y se aplican "
            "encima del perfil de fábrica. Así, si el perfil base mejora en una "
            "actualización, no pierdes ni tus ajustes ni las mejoras."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color:#666; padding-top:10px;")
        caja.addWidget(nota)
        caja.addStretch()
        self._refrescar_temas()
        return w

    def _refrescar_temas(self) -> None:
        from .. import temas

        perfil = temas.construir()
        propios = [k for k in perfil.todos if not k.startswith("D")]
        apagados = [k for k in perfil.todos if k not in perfil.dominios]
        partes = [
            f"<b>{len(perfil.dominios)}</b> temas activos de {len(perfil.todos)}, "
            f"<b>{sum(len(d.terminos) for d in perfil.dominios.values())}</b> términos, "
            f"<b>{len(perfil.consultas_arxiv) + len(perfil.consultas_texto)}</b> consultas.",
            f"Abren la puerta: <b>{', '.join(sorted(perfil.abren))}</b>.",
        ]
        if propios:
            partes.append(f"Temas creados por ti: {', '.join(propios)}.")
        if apagados:
            partes.append(f"Apagados: {', '.join(apagados)}.")
        self.lbl_temas.setText("<br>".join(partes))

    def _abrir_temas(self) -> None:
        from .temas_dialog import DialogoTemas

        if DialogoTemas(self.cfg, self).exec():
            self._refrescar_temas()

    # ------------------------------------------------------------------
    # Claude
    # ------------------------------------------------------------------

    def _tab_claude(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.ed_clave = QLineEdit()
        self.ed_clave.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_clave.setPlaceholderText(
            "Ya hay una clave guardada, escribe aquí solo si la vas a cambiar"
            if self.cfg.tiene_clave() else "sk-ant-..."
        )
        form.addRow("Clave de la API:", self.ed_clave)

        estado = QLabel(
            "Hay una clave guardada y cifrada." if self.cfg.tiene_clave()
            else "No hay clave. Sin ella la app muestra los abstracts sin resumir."
        )
        estado.setStyleSheet("color: #666;")
        form.addRow("", estado)

        fila = QHBoxLayout()
        btn_probar = QPushButton("Probar clave")
        btn_probar.clicked.connect(self._probar_clave)
        btn_borrar = QPushButton("Borrar clave guardada")
        btn_borrar.clicked.connect(self._borrar_clave)
        fila.addWidget(btn_probar)
        fila.addWidget(btn_borrar)
        fila.addStretch()
        cont = QWidget()
        cont.setLayout(fila)
        form.addRow("", cont)

        self.cb_modelo = QComboBox()
        for mid, desc in MODELOS:
            self.cb_modelo.addItem(f"{mid} - {desc}", mid)
        idx = self.cb_modelo.findData(self.cfg.modelo_claude)
        if idx >= 0:
            self.cb_modelo.setCurrentIndex(idx)
        self.cb_modelo.currentIndexChanged.connect(self._actualizar_costo)
        form.addRow("Modelo:", self.cb_modelo)

        self.lbl_costo = QLabel()
        self.lbl_costo.setStyleSheet("color: #666;")
        form.addRow("Costo estimado:", self.lbl_costo)
        self._actualizar_costo()

        nota = QLabel(
            "La clave se guarda cifrada con DPAPI de Windows, atada a tu cuenta.\n"
            "Si copias data\\config.json a otra máquina, la clave no se puede descifrar."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #666; padding-top: 12px;")
        form.addRow("", nota)

        form.addRow(QLabel("<b>Tu perfil de investigación</b>"))
        self.txt_perfil = QPlainTextEdit(self.cfg.perfil_investigador)
        self.txt_perfil.setPlaceholderText(
            "Un párrafo: qué investigas, sobre qué trabajas, qué te interesa.\n\n"
            "Se inyecta en el prompt para que los resúmenes respondan 'por qué "
            "te importa a TI' en lugar de describir el paper en abstracto.\n\n"
            "Si lo dejas vacío, se arma solo con tus temas activos y tus trabajos."
        )
        self.txt_perfil.setMaximumHeight(130)
        form.addRow("", self.txt_perfil)
        return w

    def _actualizar_costo(self) -> None:
        modelo = self.cb_modelo.currentData()
        por_dia = self.sp_papers.value() * 2 if hasattr(self, "sp_papers") else 10
        self.lbl_costo.setText(summarize.costo_estimado(modelo, por_dia))

    def _probar_clave(self) -> None:
        import anthropic

        clave = self.ed_clave.text().strip() or self.cfg.get_clave_claude()
        if not clave:
            QMessageBox.warning(self, "Sin clave", "Escribe una clave primero.")
            return
        try:
            cliente = anthropic.Anthropic(api_key=clave, max_retries=1)
            cliente.messages.create(
                model=self.cb_modelo.currentData(),
                max_tokens=16,
                messages=[{"role": "user", "content": "Responde solo: ok"}],
            )
            QMessageBox.information(self, "Clave válida", "La clave funciona.")
        except Exception as exc:
            QMessageBox.critical(self, "La clave falló", str(exc))

    def _borrar_clave(self) -> None:
        if QMessageBox.question(
            self, "Borrar clave", "¿Borrar la clave guardada?"
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.set_clave_claude("")
            self.cfg.guardar()
            self.ed_clave.clear()
            QMessageBox.information(self, "Listo", "Clave borrada.")

    # ------------------------------------------------------------------
    # Horarios
    # ------------------------------------------------------------------

    def _tab_horarios(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.te_manana = QTimeEdit(QTime.fromString(self.cfg.horario_manana, "HH:mm"))
        self.te_manana.setDisplayFormat("HH:mm")
        form.addRow("Búsqueda de la mañana:", self.te_manana)

        self.te_tarde = QTimeEdit(QTime.fromString(self.cfg.horario_tarde, "HH:mm"))
        self.te_tarde.setDisplayFormat("HH:mm")
        form.addRow("Búsqueda de la tarde:", self.te_tarde)

        self.sp_papers = QSpinBox()
        self.sp_papers.setRange(1, 20)
        self.sp_papers.setValue(self.cfg.papers_por_corrida)
        self.sp_papers.valueChanged.connect(self._actualizar_costo)
        form.addRow("Papers por corrida:", self.sp_papers)

        self.ck_arranque = QCheckBox("Arrancar con Windows, en la bandeja")
        self.ck_arranque.setChecked(self.cfg.arranque_con_windows)
        form.addRow("", self.ck_arranque)

        self.ck_notif = QCheckBox("Avisar con una notificación al terminar la búsqueda")
        self.ck_notif.setChecked(self.cfg.notificaciones)
        form.addRow("", self.ck_notif)

        nota = QLabel(
            "Si la computadora está apagada a la hora programada, la búsqueda se "
            "dispara al encenderla. No se pierde el día ni se repite."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #666; padding-top: 12px;")
        form.addRow("", nota)
        return w

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def _tab_ranking(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)

        grupo = QGroupBox("Pesos del ranking híbrido")
        form = QFormLayout(grupo)
        self.sp_pesos: dict[str, QDoubleSpinBox] = {}
        etiquetas = {
            "relevancia": "Relevancia con tu línea",
            "venue": "Calidad del venue",
            "citas": "Velocidad de citas",
            "novedad": "Novedad",
        }
        valores = {
            "relevancia": self.cfg.peso_relevancia,
            "venue": self.cfg.peso_venue,
            "citas": self.cfg.peso_citas,
            "novedad": self.cfg.peso_novedad,
        }
        for clave, etiqueta in etiquetas.items():
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 1.0)
            sp.setSingleStep(0.05)
            sp.setDecimals(2)
            sp.setValue(valores[clave])
            sp.valueChanged.connect(self._actualizar_suma)
            self.sp_pesos[clave] = sp
            form.addRow(etiqueta + ":", sp)

        self.lbl_suma = QLabel()
        form.addRow("Suma:", self.lbl_suma)
        caja.addWidget(grupo)

        grupo2 = QGroupBox("Alcance de la búsqueda")
        form2 = QFormLayout(grupo2)
        self.sp_ventana = QSpinBox()
        self.sp_ventana.setRange(1, 120)
        self.sp_ventana.setSuffix(" días")
        self.sp_ventana.setValue(self.cfg.ventana_dias)
        form2.addRow("Ventana hacia atrás:", self.sp_ventana)

        self.sp_candidatos = QSpinBox()
        self.sp_candidatos.setRange(10, 200)
        self.sp_candidatos.setValue(self.cfg.candidatos_por_fuente)
        form2.addRow("Candidatos por consulta:", self.sp_candidatos)
        caja.addWidget(grupo2)

        nota = QLabel(
            "Los pesos se normalizan solos: lo que importa es la proporción entre "
            "ellos, no que sumen exactamente 1.00.\n\n"
            "La relevancia tiene una puerta: si un paper no menciona nada del "
            "borde, los grafos de conocimiento o los modelos pequeños, queda fuera "
            "aunque venga de Nature."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #666;")
        caja.addWidget(nota)
        caja.addStretch()
        self._actualizar_suma()
        return w

    def _actualizar_suma(self) -> None:
        total = sum(sp.value() for sp in self.sp_pesos.values())
        self.lbl_suma.setText(f"{total:.2f} (se normaliza automáticamente)")

    # ------------------------------------------------------------------
    # Voz
    # ------------------------------------------------------------------

    def _tab_voz(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.cb_motor = QComboBox()
        self.cb_motor.addItem("edge-tts, voces neuronales (necesita internet)", "edge")
        self.cb_motor.addItem("SAPI5 local (sin internet, suena peor)", "sapi")
        idx = self.cb_motor.findData(self.cfg.motor_voz)
        if idx >= 0:
            self.cb_motor.setCurrentIndex(idx)
        form.addRow("Motor:", self.cb_motor)

        self.cb_voz = QComboBox()
        for vid, desc in tts.VOCES_SUGERIDAS:
            self.cb_voz.addItem(f"{vid} - {desc}", vid)
        idx = self.cb_voz.findData(self.cfg.voz)
        if idx >= 0:
            self.cb_voz.setCurrentIndex(idx)
        form.addRow("Voz:", self.cb_voz)

        self.sl_velocidad = QSlider(Qt.Orientation.Horizontal)
        self.sl_velocidad.setRange(-50, 100)
        try:
            actual = int(str(self.cfg.velocidad_voz).replace("%", "").replace("+", ""))
        except ValueError:
            actual = 0
        self.sl_velocidad.setValue(actual)
        self.lbl_velocidad = QLabel(f"{actual:+d}%")
        self.sl_velocidad.valueChanged.connect(
            lambda v: self.lbl_velocidad.setText(f"{v:+d}%")
        )
        fila = QHBoxLayout()
        fila.addWidget(self.sl_velocidad)
        fila.addWidget(self.lbl_velocidad)
        cont = QWidget()
        cont.setLayout(fila)
        form.addRow("Velocidad:", cont)

        self.sl_volumen = QSlider(Qt.Orientation.Horizontal)
        self.sl_volumen.setRange(10, 100)
        self.sl_volumen.setValue(self.cfg.volumen_voz)
        form.addRow("Volumen:", self.sl_volumen)

        btn = QPushButton("Probar la voz")
        btn.clicked.connect(self._probar_voz)
        form.addRow("", btn)
        return w

    def _probar_voz(self) -> None:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtCore import QUrl

        muestra = (
            "Escalado invertido en el borde: un modelo de mil quinientos millones "
            "de parámetros cuantizado a int cuatro recupera el noventa y ocho por "
            "ciento de la exactitud del modelo grande, con una quinta parte de la "
            "latencia."
        )
        try:
            ruta, motor = tts.sintetizar(
                muestra, "muestra-config", self.cfg.dir_audio,
                motor=self.cb_motor.currentData(),
                voz=self.cb_voz.currentData(),
                velocidad=f"{self.sl_velocidad.value():+d}%",
                volumen=self.sl_volumen.value(),
                forzar=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo sintetizar", str(exc))
            return

        self._reproductor = QMediaPlayer(self)
        self._salida = QAudioOutput(self)
        self._reproductor.setAudioOutput(self._salida)
        self._salida.setVolume(self.sl_volumen.value() / 100.0)
        self._reproductor.setSource(QUrl.fromLocalFile(str(ruta)))
        self._reproductor.play()
        if motor != self.cb_motor.currentData():
            QMessageBox.information(
                self, "Se usó el respaldo",
                f"El motor elegido falló, se sintetizó con '{motor}'.",
            )

    # ------------------------------------------------------------------
    # Zotero
    # ------------------------------------------------------------------

    def _tab_zotero(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        fila = QHBoxLayout()
        self.ed_zotero_exe = QLineEdit(self.cfg.zotero_exe)
        btn_buscar = QPushButton("...")
        btn_buscar.setMaximumWidth(36)
        btn_buscar.clicked.connect(self._elegir_exe)
        fila.addWidget(self.ed_zotero_exe)
        fila.addWidget(btn_buscar)
        cont = QWidget()
        cont.setLayout(fila)
        form.addRow("Ejecutable:", cont)

        self.ed_zotero_datos = QLineEdit(self.cfg.zotero_datos)
        self.ed_zotero_datos.setPlaceholderText("Vacío = autodetectar (C:\\Users\\...\\Zotero)")
        form.addRow("Carpeta de datos:", self.ed_zotero_datos)

        self.ed_padre = QLineEdit(self.cfg.zotero_coleccion_padre)
        form.addRow("Colección padre:", self.ed_padre)

        self.ed_sub = QLineEdit(self.cfg.zotero_subcoleccion)
        form.addRow("Subcolección destino:", self.ed_sub)

        self.ck_lanzar = QCheckBox("Abrir Zotero minimizado por su cuenta cuando haga falta")
        self.ck_lanzar.setChecked(self.cfg.zotero_auto_lanzar)
        form.addRow("", self.ck_lanzar)

        btn_verificar = QPushButton("Verificar que exista la subcolección")
        btn_verificar.clicked.connect(self._verificar_zotero)
        form.addRow("", btn_verificar)

        nota = QLabel(
            "Tu biblioteca es local, sin cuenta de sincronización. La única vía "
            "que escribe directo es el conector de Zotero, y solo existe mientras "
            "Zotero corre; por eso la app lo abre sola.\n\n"
            "El guardado va dirigido a la subcolección de arriba sin importar qué "
            "tengas seleccionado en Zotero. Lo único que la app no puede hacer es "
            "crear la subcolección: eso se hace una vez, a mano. Todo ítem lleva "
            "además la etiqueta PHDjournal y la del paper de tesis."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #666; padding-top: 12px;")
        form.addRow("", nota)
        return w

    def _elegir_exe(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Ejecutable de Zotero", self.ed_zotero_exe.text(), "zotero.exe (*.exe)"
        )
        if ruta:
            self.ed_zotero_exe.setText(ruta)

    def _verificar_zotero(self) -> None:
        temporal = Config.cargar()
        temporal.zotero_datos = self.ed_zotero_datos.text().strip()
        temporal.zotero_coleccion_padre = self.ed_padre.text().strip()
        temporal.zotero_subcoleccion = self.ed_sub.text().strip()
        ok, detalle = zotero.verificar_subcoleccion(temporal)
        if ok:
            QMessageBox.information(
                self, "Todo listo",
                f"Existe '{temporal.zotero_coleccion_padre} > "
                f"{temporal.zotero_subcoleccion}' (id {detalle}).",
            )
        else:
            QMessageBox.warning(self, "Falta crearla", detalle)

    # ------------------------------------------------------------------
    # Fuentes
    # ------------------------------------------------------------------

    def _tab_fuentes(self) -> QWidget:
        w = QWidget()
        caja = QVBoxLayout(w)

        grupo = QGroupBox("Fuentes activas")
        vbox = QVBoxLayout(grupo)
        self.ck_fuentes: dict[str, QCheckBox] = {}
        for clave, desc in FUENTES:
            ck = QCheckBox(desc)
            ck.setChecked(clave in self.cfg.fuentes_activas)
            self.ck_fuentes[clave] = ck
            vbox.addWidget(ck)
        caja.addWidget(grupo)

        form = QFormLayout()
        self.ed_email = QLineEdit(self.cfg.email_contacto)
        self.ed_email.setPlaceholderText("tu@correo.com")
        form.addRow("Correo de contacto:", self.ed_email)

        self.ed_clave_s2 = QLineEdit()
        self.ed_clave_s2.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_clave_s2.setPlaceholderText(
            "Ya hay una clave guardada" if self.cfg.get_clave_s2()
            else "opcional, se pide gratis en semanticscholar.org/product/api"
        )
        form.addRow("Clave de Semantic Scholar:", self.ed_clave_s2)
        cont = QWidget()
        cont.setLayout(form)
        caja.addWidget(cont)

        nota = QLabel(
            "OpenAlex y Crossref dan prioridad de cola a quien se identifica con "
            "un correo. Es opcional y no se manda a ningún otro lado.\n\n"
            "Semantic Scholar sin clave responde 429 casi siempre y la app se la "
            "salta sola. La clave es gratuita y la reactiva; se guarda cifrada "
            "igual que la de Claude.\n\n"
            "Google Scholar no está: no tiene API y raspar su web viola sus "
            "términos de servicio."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #666;")
        caja.addWidget(nota)
        caja.addStretch()
        return w

    # ------------------------------------------------------------------

    def _guardar(self) -> None:
        c = self.cfg
        if self.ed_clave.text().strip():
            try:
                c.set_clave_claude(self.ed_clave.text().strip())
            except Exception as exc:
                QMessageBox.critical(self, "No se pudo cifrar la clave", str(exc))
                return

        c.modelo_claude = self.cb_modelo.currentData()
        c.perfil_investigador = self.txt_perfil.toPlainText().strip()
        c.horario_manana = self.te_manana.time().toString("HH:mm")
        c.horario_tarde = self.te_tarde.time().toString("HH:mm")
        c.papers_por_corrida = self.sp_papers.value()
        c.arranque_con_windows = self.ck_arranque.isChecked()
        c.notificaciones = self.ck_notif.isChecked()

        c.peso_relevancia = self.sp_pesos["relevancia"].value()
        c.peso_venue = self.sp_pesos["venue"].value()
        c.peso_citas = self.sp_pesos["citas"].value()
        c.peso_novedad = self.sp_pesos["novedad"].value()
        c.ventana_dias = self.sp_ventana.value()
        c.candidatos_por_fuente = self.sp_candidatos.value()

        c.motor_voz = self.cb_motor.currentData()
        c.voz = self.cb_voz.currentData()
        c.velocidad_voz = f"{self.sl_velocidad.value():+d}%"
        c.volumen_voz = self.sl_volumen.value()

        c.zotero_exe = self.ed_zotero_exe.text().strip()
        c.zotero_datos = self.ed_zotero_datos.text().strip()
        c.zotero_coleccion_padre = self.ed_padre.text().strip()
        c.zotero_subcoleccion = self.ed_sub.text().strip()
        c.zotero_auto_lanzar = self.ck_lanzar.isChecked()

        c.fuentes_activas = [k for k, ck in self.ck_fuentes.items() if ck.isChecked()]
        c.email_contacto = self.ed_email.text().strip()
        if self.ed_clave_s2.text().strip():
            c.set_clave_s2(self.ed_clave_s2.text().strip())

        c.guardar()
        self.accept()
