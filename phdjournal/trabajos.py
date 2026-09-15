"""Mis trabajos: los proyectos propios del investigador.

Un investigador tiene trabajos en curso, papers, capítulos, proyectos. Esta
capa los describe con términos para que la app pueda etiquetar cada paper que
llega: *"esto toca tu trabajo T2"*.

Diferencia importante con los temas, y es la razón de que sean dos cosas
separadas:

* Los **temas** abren la puerta, pesan en el puntaje y generan las consultas
  de búsqueda.
* Los **trabajos** solo etiquetan. No suben ni bajan el puntaje, no buscan
  nada, y "sin etiqueta" es una respuesta perfectamente válida.

Vive entero en ``data/trabajos.json``. En el repositorio público la lista va
vacía: los trabajos de alguien son suyos y no tienen por qué estar en el
código fuente. Antes estaban, como P1 a P4 incrustados en ``profile.py``, y
era un error de diseño: publicaba la agenda de investigación del autor junto
con la herramienta.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import DIR_DATOS

log = logging.getLogger(__name__)

RUTA_TRABAJOS = DIR_DATOS / "trabajos.json"
VERSION = 1
PREFIJO = "T"

# Puntaje mínimo para poner la etiqueta. Por debajo, el paper sale sin ella y
# no pasa nada: es de interés general y forzar una etiqueta sería mentir.
UMBRAL_ETIQUETA = 6.0


@dataclass
class Trabajo:
    clave: str
    nombre: str
    terminos: dict[str, float] = field(default_factory=dict)
    nota: str = ""
    activo: bool = True

    def como_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "terminos": self.terminos,
            "nota": self.nota,
            "activo": self.activo,
        }


def cargar() -> dict[str, Trabajo]:
    if not RUTA_TRABAJOS.exists():
        return {}
    try:
        datos = json.loads(RUTA_TRABAJOS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("trabajos.json ilegible (%s); se ignora", exc)
        return {}

    salida: dict[str, Trabajo] = {}
    for clave, d in (datos.get("trabajos", {}) or {}).items():
        try:
            salida[clave] = Trabajo(
                clave=clave,
                nombre=str(d.get("nombre", clave)),
                terminos={str(k): float(v) for k, v in (d.get("terminos") or {}).items()},
                nota=str(d.get("nota", "")),
                activo=bool(d.get("activo", True)),
            )
        except (TypeError, ValueError):
            log.warning("Trabajo %s mal formado; se omite", clave)
    return salida


def guardar(trabajos: dict[str, Trabajo]) -> None:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    datos = {
        "version": VERSION,
        "trabajos": {c: t.como_dict() for c, t in trabajos.items()},
    }
    tmp = RUTA_TRABAJOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(RUTA_TRABAJOS)
    log.info("%d trabajos guardados en %s", len(trabajos), RUTA_TRABAJOS)


def siguiente_clave(trabajos: dict[str, Trabajo]) -> str:
    usados = {int(c[1:]) for c in trabajos if c.startswith(PREFIJO) and c[1:].isdigit()}
    n = 1
    while n in usados:
        n += 1
    return f"{PREFIJO}{n}"


def crear(
    trabajos: dict[str, Trabajo],
    nombre: str,
    terminos: dict[str, float],
    nota: str = "",
) -> str:
    clave = siguiente_clave(trabajos)
    trabajos[clave] = Trabajo(clave, nombre, dict(terminos), nota)
    return clave


def etiquetar(
    texto: str,
    titulo: str,
    trabajos: dict[str, Trabajo],
    contar,
    umbral: float = UMBRAL_ETIQUETA,
) -> str | None:
    """Devuelve la clave del trabajo que mejor encaja, o None.

    ``contar`` es la función de conteo de términos del ranking; se pasa como
    argumento para no crear una dependencia circular entre módulos.
    """
    mejor, mejor_puntos = None, 0.0
    for clave, t in trabajos.items():
        if not t.activo or not t.terminos:
            continue
        puntos, _ = contar(texto, titulo, t.terminos)
        if puntos > mejor_puntos:
            mejor, mejor_puntos = clave, puntos
    return mejor if mejor_puntos >= umbral else None


def nombre_de(clave: str | None, trabajos: dict[str, Trabajo] | None = None) -> str:
    if not clave:
        return ""
    trabajos = trabajos if trabajos is not None else cargar()
    t = trabajos.get(clave)
    return t.nombre if t else clave
