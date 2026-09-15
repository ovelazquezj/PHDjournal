"""Notificación en la barra de tareas.

Intenta primero un toast nativo de Windows 11 (``windows-toasts``). Si esa
biblioteca no está o falla, cae al globo del icono de bandeja de Qt, que
siempre funciona. En los dos casos, hacer clic abre la ventana del lector.

Como la app vive en la bandeja y ya está corriendo cuando salta la
notificación, el callback de activación se resuelve dentro del proceso. No
hace falta registrar un AUMID para que el clic funcione.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

APP_ID = "PHDjournal"


class Notificador:
    def __init__(self, al_activar: Callable[[], None], bandeja=None) -> None:
        self.al_activar = al_activar
        self.bandeja = bandeja
        self._toaster = None
        self._toasts_vivos: list = []  # evita que el GC se lleve el callback

        try:
            from windows_toasts import WindowsToaster

            self._toaster = WindowsToaster(APP_ID)
            log.info("Notificaciones nativas de Windows disponibles")
        except Exception as exc:
            log.info("windows-toasts no disponible (%s); se usará la bandeja", exc)

    def notificar(self, titulo: str, cuerpo: str) -> None:
        if self._toaster is not None and self._enviar_toast(titulo, cuerpo):
            return
        self._enviar_bandeja(titulo, cuerpo)

    # ------------------------------------------------------------------

    def _enviar_toast(self, titulo: str, cuerpo: str) -> bool:
        try:
            from windows_toasts import Toast

            toast = Toast()
            toast.text_fields = [titulo, cuerpo]

            def _activado(_args=None) -> None:
                try:
                    self.al_activar()
                except Exception:
                    log.exception("Falló el callback de la notificación")

            toast.on_activated = _activado
            toast.on_dismissed = lambda *_: self._olvidar(toast)
            self._toasts_vivos.append(toast)
            if len(self._toasts_vivos) > 10:
                self._toasts_vivos.pop(0)

            self._toaster.show_toast(toast)
            return True
        except Exception as exc:
            log.warning("El toast nativo falló (%s); se usa la bandeja", exc)
            return False

    def _olvidar(self, toast) -> None:
        try:
            self._toasts_vivos.remove(toast)
        except ValueError:
            pass

    def _enviar_bandeja(self, titulo: str, cuerpo: str) -> None:
        if self.bandeja is None:
            log.warning("Sin canal de notificación: %s - %s", titulo, cuerpo)
            return
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            self.bandeja.showMessage(
                titulo, cuerpo, QSystemTrayIcon.MessageIcon.Information, 20000
            )
        except Exception:
            log.exception("Tampoco se pudo notificar por la bandeja")
