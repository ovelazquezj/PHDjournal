"""La app residente: icono de bandeja, programador y notificaciones.

Cerrar la ventana no cierra el programa, lo esconde. Se sale de verdad desde
el menú del icono de la bandeja. Así las dos búsquedas diarias siguen
ocurriendo sin que tengas que dejar una ventana abierta.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import db, scheduler
from ..config import Config
from ..notify import Notificador
from .iconos import icono_app
from .main_window import VentanaPrincipal
from .settings_dialog import DialogoConfig

log = logging.getLogger(__name__)

NOMBRE_SERVIDOR = "PHDjournal-instancia-unica"
INTERVALO_REVISION_MS = 60_000


class Aplicacion:
    def __init__(self, qapp: QApplication) -> None:
        self.qapp = qapp
        self.qapp.setApplicationName("PHDjournal")
        self.qapp.setOrganizationName("PHDjournal")
        self.qapp.setWindowIcon(icono_app())
        # Cerrar la última ventana no debe terminar el proceso.
        self.qapp.setQuitOnLastWindowClosed(False)

        db.inicializar()
        self.cfg = Config.cargar()

        # El asistente va ANTES de construir la ventana: decide que temas
        # quedan activos, y la ventana se pinta con esa decision ya tomada.
        from .bienvenida import DialogoBienvenida, hace_falta

        self._abrir_temas_al_arrancar = False
        if hace_falta(self.cfg):
            dlg = DialogoBienvenida(self.cfg)
            dlg.exec()
            self._abrir_temas_al_arrancar = dlg.quiere_generar
            self.cfg = Config.cargar()

        self.ventana = VentanaPrincipal(self.cfg)
        self.ventana.corrida_terminada.connect(self._tras_corrida)

        self._construir_bandeja()
        self.notificador = Notificador(self.mostrar_ventana, self.bandeja)

        self.temporizador = QTimer()
        self.temporizador.timeout.connect(self.revisar_horario)
        self.temporizador.start(INTERVALO_REVISION_MS)

        self._servidor_instancia()

        # Primera revisión cinco segundos después de arrancar, para no pelear
        # con el arranque de Windows.
        QTimer.singleShot(5000, self.revisar_horario)

    # ------------------------------------------------------------------

    def _construir_bandeja(self) -> None:
        self.bandeja = QSystemTrayIcon(icono_app(), self.qapp)
        self.bandeja.setToolTip("PHDjournal")

        menu = QMenu()
        act_abrir = QAction("Abrir el lector", menu)
        act_abrir.triggered.connect(self.mostrar_ventana)
        menu.addAction(act_abrir)

        act_buscar = QAction("Buscar ahora", menu)
        act_buscar.triggered.connect(self._buscar_ahora)
        menu.addAction(act_buscar)

        menu.addSeparator()
        act_config = QAction("Configuración", menu)
        act_config.triggered.connect(self._abrir_config)
        menu.addAction(act_config)

        menu.addSeparator()
        act_salir = QAction("Salir de PHDjournal", menu)
        act_salir.triggered.connect(self.salir)
        menu.addAction(act_salir)

        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(self._clic_bandeja)
        self.bandeja.messageClicked.connect(self.mostrar_ventana)
        self.bandeja.show()

    def _clic_bandeja(self, razon) -> None:
        if razon in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.mostrar_ventana()

    # ------------------------------------------------------------------

    def mostrar_ventana(self) -> None:
        self.ventana.showNormal()
        self.ventana.raise_()
        self.ventana.activateWindow()

    def _buscar_ahora(self) -> None:
        self.mostrar_ventana()
        self.ventana.lanzar_corrida("manual")

    def _abrir_config(self) -> None:
        dlg = DialogoConfig(self.cfg, self.ventana)
        if dlg.exec():
            self.cfg = Config.cargar()
            self.ventana.cfg = self.cfg
            self.ventana.actualizar_proxima()

    # ------------------------------------------------------------------

    def revisar_horario(self) -> None:
        """Cada minuto: ¿toca buscar?"""
        try:
            franja = scheduler.franja_pendiente(self.cfg)
        except Exception:
            log.exception("Falló la revisión de horario")
            return
        if franja is None:
            self.ventana.actualizar_proxima()
            return
        if self.ventana._hilo_corrida is not None and self.ventana._hilo_corrida.isRunning():
            return

        log.info("Disparando la corrida de la franja '%s'", franja)
        self.ventana.lanzar_corrida(franja)

    def _tras_corrida(self, resultado) -> None:
        if not self.cfg.notificaciones:
            return
        if resultado.n_mostrados == 0:
            return
        momento = {"manana": "de la mañana", "tarde": "de la tarde"}.get(
            resultado.franja, ""
        )
        self.notificador.notificar(
            f"PHDjournal: {resultado.n_mostrados} papers {momento}",
            "Clic para abrir el lector y escuchar los resúmenes.",
        )

    # ------------------------------------------------------------------

    def _servidor_instancia(self) -> None:
        """Escucha a otras instancias para traer la ventana al frente."""
        QLocalServer.removeServer(NOMBRE_SERVIDOR)
        self.servidor = QLocalServer()
        if self.servidor.listen(NOMBRE_SERVIDOR):
            self.servidor.newConnection.connect(self._otra_instancia)

    def _otra_instancia(self) -> None:
        conexion = self.servidor.nextPendingConnection()
        if conexion is not None:
            conexion.disconnectFromServer()
        self.mostrar_ventana()

    # ------------------------------------------------------------------

    def salir(self) -> None:
        if (
            QMessageBox.question(
                self.ventana,
                "Salir",
                "Si sales, las búsquedas automáticas se detienen hasta que "
                "vuelvas a abrir PHDjournal.\n\n¿Salir de todos modos?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.bandeja.hide()
        self.qapp.quit()

    def ejecutar(self) -> int:
        return self.qapp.exec()


def ya_hay_instancia() -> bool:
    """Si ya corre otra copia, se le avisa y esta se retira."""
    socket = QLocalSocket()
    socket.connectToServer(NOMBRE_SERVIDOR)
    if socket.waitForConnected(500):
        socket.disconnectFromServer()
        socket.waitForDisconnected(500)
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    qapp = QApplication(argv)

    if ya_hay_instancia():
        log.info("Ya hay una instancia corriendo; se le pidió mostrarse.")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None, "PHDjournal",
            "Windows no está exponiendo el área de notificación. "
            "La app necesita la bandeja del sistema para vivir en segundo plano.",
        )
        return 1

    app = Aplicacion(qapp)
    if "--minimizado" not in argv:
        app.mostrar_ventana()
    if getattr(app, "_abrir_temas_al_arrancar", False):
        from PySide6.QtCore import QTimer

        from .temas_dialog import DialogoTemas

        QTimer.singleShot(400, lambda: DialogoTemas(app.cfg, app.ventana).exec())
    return app.ejecutar()
