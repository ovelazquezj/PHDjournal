"""Hilos de trabajo.

Nada que tarde, que use la red o que llame a una API corre en el hilo de la
interfaz. Cada tarea larga es un QThread que emite señales; la ventana solo
pinta lo que recibe.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .. import pdf as pdf_mod
from .. import pipeline, summarize, tts, zotero
from ..config import Config
from ..sources.base import Paper

log = logging.getLogger(__name__)


class HiloCorrida(QThread):
    """Ejecuta una búsqueda completa."""

    progreso = Signal(str, int)
    terminado = Signal(object)          # ResultadoCorrida
    fallo = Signal(str)

    def __init__(self, cfg: Config, franja: str = "manual", parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.franja = franja

    def run(self) -> None:
        try:
            resultado = pipeline.ejecutar(
                self.cfg, self.franja, progreso=lambda m, p: self.progreso.emit(m, p)
            )
            self.terminado.emit(resultado)
        except Exception as exc:
            log.exception("La corrida falló")
            self.fallo.emit(str(exc))


class HiloVoz(QThread):
    """Sintetiza un texto y devuelve la ruta del audio."""

    terminado = Signal(str, str)        # (ruta, motor usado)
    fallo = Signal(str)

    def __init__(self, texto: str, clave: str, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.texto = texto
        self.clave = clave
        self.cfg = cfg

    def run(self) -> None:
        try:
            ruta, motor = tts.sintetizar(
                self.texto,
                self.clave,
                self.cfg.dir_audio,
                motor=self.cfg.motor_voz,
                voz=self.cfg.voz,
                velocidad=self.cfg.velocidad_voz,
                volumen=self.cfg.volumen_voz,
            )
            self.terminado.emit(str(ruta), motor)
        except Exception as exc:
            log.exception("La síntesis de voz falló")
            self.fallo.emit(str(exc))


class HiloPDF(QThread):
    """Descarga el PDF de acceso abierto."""

    terminado = Signal(str)
    fallo = Signal(str)

    def __init__(self, paper: Paper, destino: Path, parent=None) -> None:
        super().__init__(parent)
        self.paper = paper
        self.destino = destino

    def run(self) -> None:
        try:
            ruta = pdf_mod.descargar(self.paper, self.destino)
            self.terminado.emit(str(ruta))
        except Exception as exc:
            self.fallo.emit(str(exc))


class HiloZotero(QThread):
    """Exporta un ítem a Zotero, abriéndolo si hace falta."""

    progreso = Signal(str)
    terminado = Signal(str)
    falta_subcoleccion = Signal(str)          # instrucciones para crearla
    fallo = Signal(str)

    def __init__(self, cfg: Config, item: dict, dirigir: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.item = item
        self.dirigir = dirigir

    def run(self) -> None:
        try:
            if not zotero.ping(self.cfg.zotero_puerto):
                self.progreso.emit("Zotero está cerrado, abriéndolo minimizado...")
            resultado = zotero.guardar_items(self.cfg, [self.item], dirigir=self.dirigir)
            self.terminado.emit(f"Guardado en {resultado['destino']}")
        except zotero.SubcoleccionFaltante as exc:
            self.falta_subcoleccion.emit(str(exc))
        except Exception as exc:
            log.exception("La exportación a Zotero falló")
            self.fallo.emit(str(exc))


class HiloResumen(QThread):
    """Genera el resumen de un paper que no lo tiene.

    Pasa cuando una corrida se ejecutó sin clave de la API, o cuando el
    resumen falló esa vez. Sin esto, el paper queda mudo para siempre: una
    búsqueda nueva trae papers nuevos, no rellena los viejos.
    """

    terminado = Signal(str, object)     # (paper_id, resumen)
    fallo = Signal(str)

    def __init__(self, paper: Paper, puntaje, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.paper = paper
        self.puntaje = puntaje
        self.cfg = cfg

    def run(self) -> None:
        try:
            resumen, t_in, t_out = summarize.resumir(self.paper, self.puntaje, self.cfg)
            from .. import db

            with db.conexion() as con:
                db.guardar_resumen(
                    con, self.paper.id, self.cfg.idioma_resumen,
                    self.cfg.modelo_claude, resumen, t_in, t_out,
                    generado_por_ia=True,
                )
            self.terminado.emit(self.paper.id, resumen)
        except Exception as exc:
            log.exception("No se pudo resumir a petición")
            self.fallo.emit(str(exc))


class HiloSeccion(QThread):
    """Resume una sección del PDF para escucharla."""

    terminado = Signal(str, str)        # (titulo, texto)
    fallo = Signal(str)

    def __init__(self, titulo: str, texto: str, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.titulo = titulo
        self.texto = texto
        self.cfg = cfg

    def run(self) -> None:
        try:
            resumen = summarize.resumir_seccion(self.titulo, self.texto, self.cfg)
            self.terminado.emit(self.titulo, resumen)
        except Exception as exc:
            self.fallo.emit(str(exc))
