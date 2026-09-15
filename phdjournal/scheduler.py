"""Programador interno de las dos corridas diarias.

La app vive en la bandeja y revisa cada minuto si toca buscar. Se guarda la
fecha de la última corrida de cada franja, así que:

* si la laptop estaba apagada a las 5:30 y la enciendes a las 9:00, la corrida
  de la mañana se dispara al encender, no se pierde el día;
* la corrida de la tarde nunca se adelanta a su hora;
* reiniciar la app veinte veces en un día no dispara veinte búsquedas.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time

from . import db
from .config import Config

log = logging.getLogger(__name__)

FRANJAS = ("manana", "tarde")


def _hora(texto: str, defecto: time) -> time:
    try:
        h, m = texto.strip().split(":")
        return time(int(h), int(m))
    except Exception:
        log.warning("Horario inválido '%s', se usa %s", texto, defecto)
        return defecto


def horarios(cfg: Config) -> dict[str, time]:
    return {
        "manana": _hora(cfg.horario_manana, time(5, 30)),
        "tarde": _hora(cfg.horario_tarde, time(18, 30)),
    }


def _clave(franja: str) -> str:
    return f"ultima_corrida_{franja}"


def ultima_ejecucion(franja: str) -> date | None:
    with db.conexion() as con:
        valor = db.kv_get(con, _clave(franja))
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def marcar_ejecutada(franja: str, cuando: date | None = None) -> None:
    with db.conexion() as con:
        db.kv_set(con, _clave(franja), (cuando or date.today()).isoformat())


def franja_pendiente(cfg: Config, ahora: datetime | None = None) -> str | None:
    """Devuelve la franja que toca ejecutar, o None si no hay nada pendiente."""
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    tabla = horarios(cfg)

    for franja in FRANJAS:
        objetivo = tabla[franja]
        if ahora.time() < objetivo:
            continue  # todavía no es hora
        ultima = ultima_ejecucion(franja)
        if ultima is None or ultima < hoy:
            return franja
    return None


def proxima_descripcion(cfg: Config, ahora: datetime | None = None) -> str:
    """Texto para la barra de estado: cuándo es la siguiente búsqueda."""
    ahora = ahora or datetime.now()
    tabla = horarios(cfg)
    hoy = ahora.date()

    candidatas: list[tuple[datetime, str]] = []
    for franja in FRANJAS:
        objetivo = datetime.combine(hoy, tabla[franja])
        ultima = ultima_ejecucion(franja)
        ya_corrio_hoy = ultima is not None and ultima >= hoy
        if objetivo > ahora:
            candidatas.append((objetivo, franja))
        elif not ya_corrio_hoy:
            return f"pendiente ahora ({_nombre(franja)})"

    if candidatas:
        cuando, franja = min(candidatas)
        return f"{_nombre(franja)} a las {cuando.strftime('%H:%M')}"

    # Las dos ya corrieron hoy: la siguiente es la mañana de mañana.
    return f"mañana a las {tabla['manana'].strftime('%H:%M')}"


def _nombre(franja: str) -> str:
    return "mañana" if franja == "manana" else "tarde"
