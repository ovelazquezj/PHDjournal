"""Temas configurables: base en código + superposición del usuario.

`profile.py` es la **base**: los diez temas de arranque, con sus términos,
pesos, consultas y umbrales. No se toca desde la interfaz.

`data/temas.json` es la **superposición**: guarda solo lo que el usuario
cambió. Temas nuevos, términos añadidos o quitados, pesos alterados, temas
apagados, umbrales movidos.

Se eligió superposición y no reemplazo por una razón concreta: durante el
desarrollo la base se afinó dos veces y en las dos la selección mejoró. Con
reemplazo, el usuario se habría quedado congelado en la versión que editó.
Con superposición, las mejoras de la base le siguen llegando y sus ajustes
sobreviven encima.

La otra ventaja es que el archivo queda pequeño y legible: si algo sale mal,
se abre y se ve exactamente qué se cambió.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import profile
from .config import DIR_DATOS

log = logging.getLogger(__name__)

RUTA_TEMAS = DIR_DATOS / "temas.json"
VERSION = 1

# Los temas creados por el usuario llevan prefijo U para no chocar nunca con
# los D de la base, aunque la base crezca.
PREFIJO_USUARIO = "U"


@dataclass
class Perfil:
    """El perfil efectivo con el que corre la app: base + superposición."""

    dominios: dict[str, profile.Dominio]      # solo los activos
    todos: dict[str, profile.Dominio]         # incluidos los apagados
    abren: set[str]
    penalizaciones: dict[str, float]
    umbral_dominio: float
    umbral_veto: float
    consultas_arxiv: list[str]
    consultas_texto: list[str]
    categorias_arxiv: list[str]

    def activo(self, clave: str) -> bool:
        return clave in self.dominios

    def nombre(self, clave: str) -> str:
        dom = self.todos.get(clave)
        return dom.nombre if dom else clave


# ---------------------------------------------------------------------------
# Superposición en disco
# ---------------------------------------------------------------------------

def _overlay_vacio() -> dict:
    return {
        "version": VERSION,
        "dominios": {},
        "penalizaciones_add": {},
        "penalizaciones_quitadas": [],
        "umbrales": {},
    }


def cargar_overlay() -> dict:
    if not RUTA_TEMAS.exists():
        return _overlay_vacio()
    try:
        datos = json.loads(RUTA_TEMAS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("temas.json ilegible (%s); se ignora la superposición", exc)
        return _overlay_vacio()

    base = _overlay_vacio()
    base.update({k: v for k, v in datos.items() if k in base})
    return base


def guardar_overlay(overlay: dict) -> None:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    overlay["version"] = VERSION
    tmp = RUTA_TEMAS.with_suffix(".tmp")
    tmp.write_text(json.dumps(overlay, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(RUTA_TEMAS)
    log.info("Superposición de temas guardada en %s", RUTA_TEMAS)


def siguiente_clave_usuario(overlay: dict) -> str:
    usados = {
        int(k[1:]) for k in overlay.get("dominios", {})
        if k.startswith(PREFIJO_USUARIO) and k[1:].isdigit()
    }
    n = 1
    while n in usados:
        n += 1
    return f"{PREFIJO_USUARIO}{n}"


# ---------------------------------------------------------------------------
# Fusión
# ---------------------------------------------------------------------------

def construir(overlay: dict | None = None) -> Perfil:
    """Fusiona la base de ``profile.py`` con la superposición del usuario."""
    overlay = overlay if overlay is not None else cargar_overlay()
    ajustes = overlay.get("dominios", {}) or {}

    todos: dict[str, profile.Dominio] = {}
    abren: set[str] = set()
    arxiv: list[str] = []
    texto: list[str] = []

    claves = list(profile.DOMINIOS.keys()) + [
        k for k in ajustes if k not in profile.DOMINIOS
    ]

    for clave in claves:
        ajuste = ajustes.get(clave, {}) or {}
        base = profile.DOMINIOS.get(clave)

        if base is not None:
            terminos = dict(base.terminos)
            nombre = ajuste.get("nombre", base.nombre)
            capa = ajuste.get("capa", base.capa)
            peso = float(ajuste.get("peso", base.peso))
            abre = bool(ajuste.get("abre", clave in profile.DOMINIOS_QUE_ABREN))
            c_arxiv = list(profile.ARXIV_POR_DOMINIO.get(clave, []))
            c_texto = list(profile.TEXTO_POR_DOMINIO.get(clave, []))
        else:
            # Tema creado por el usuario: todo viene de la superposición.
            terminos = {}
            nombre = ajuste.get("nombre", clave)
            capa = ajuste.get("capa", profile.NUCLEO)
            peso = float(ajuste.get("peso", 1.0))
            abre = bool(ajuste.get("abre", True))
            c_arxiv = []
            c_texto = []

        # Términos: primero se quitan, luego se añaden.
        for t in ajuste.get("terminos_quitados", []) or []:
            terminos.pop(t, None)
        for t, p in (ajuste.get("terminos_add", {}) or {}).items():
            try:
                terminos[t] = float(p)
            except (TypeError, ValueError):
                continue

        # Consultas: las propias del usuario sustituyen si las hay.
        c_arxiv = list(ajuste.get("consultas_arxiv", c_arxiv) or [])
        c_texto = list(ajuste.get("consultas_texto", c_texto) or [])

        dom = profile.Dominio(clave, nombre, capa, peso, terminos)
        todos[clave] = dom

        if ajuste.get("activo", True) and terminos:
            if abre:
                abren.add(clave)
            arxiv.extend(c_arxiv)
            texto.extend(c_texto)

    activos = {
        k: d for k, d in todos.items()
        if (ajustes.get(k, {}) or {}).get("activo", True) and d.terminos
    }

    # Si el usuario apagó todo lo que abría, el feed quedaría vacío. Se avisa
    # y se cae a la base, que es preferible a una corrida sin resultados.
    if not abren:
        log.warning(
            "Ningún tema activo abre la puerta; se usa la base para no dejar "
            "el feed vacío."
        )
        abren = set(profile.DOMINIOS_QUE_ABREN) & set(activos)

    penal = dict(profile.PENALIZACIONES)
    for t in overlay.get("penalizaciones_quitadas", []) or []:
        penal.pop(t, None)
    for t, p in (overlay.get("penalizaciones_add", {}) or {}).items():
        try:
            penal[t] = float(p)
        except (TypeError, ValueError):
            continue

    umb = overlay.get("umbrales", {}) or {}
    return Perfil(
        dominios=activos,
        todos=todos,
        abren=abren,
        penalizaciones=penal,
        umbral_dominio=float(umb.get("dominio", profile.UMBRAL_DOMINIO)),
        umbral_veto=float(umb.get("veto", profile.UMBRAL_VETO)),
        consultas_arxiv=_unicos(arxiv),
        consultas_texto=_unicos(texto),
        categorias_arxiv=list(profile.ARXIV_CATEGORIAS),
    )


def _unicos(xs: list[str]) -> list[str]:
    vistos: set[str] = set()
    salida = []
    for x in xs:
        if x and x not in vistos:
            vistos.add(x)
            salida.append(x)
    return salida


# ---------------------------------------------------------------------------
# Edición: helpers que la interfaz usa para no manipular el JSON a mano
# ---------------------------------------------------------------------------

def ajuste_de(overlay: dict, clave: str) -> dict:
    return overlay.setdefault("dominios", {}).setdefault(clave, {})


def fijar(overlay: dict, clave: str, campo: str, valor) -> None:
    ajuste_de(overlay, clave)[campo] = valor


def set_terminos(overlay: dict, clave: str, terminos: dict[str, float]) -> None:
    """Guarda el resultado de editar la tabla de términos de un tema.

    Para los temas de la base se guarda el **diferencial** (qué se añadió y
    qué se quitó), no la lista entera. Así, si la base gana términos nuevos en
    una actualización, el usuario los recibe.
    """
    ajuste = ajuste_de(overlay, clave)
    base = profile.DOMINIOS.get(clave)

    if base is None:
        ajuste["terminos_add"] = {t: float(p) for t, p in terminos.items()}
        ajuste.pop("terminos_quitados", None)
        return

    quitados = [t for t in base.terminos if t not in terminos]
    add = {
        t: float(p) for t, p in terminos.items()
        if t not in base.terminos or abs(base.terminos[t] - float(p)) > 1e-9
    }
    if quitados:
        ajuste["terminos_quitados"] = quitados
    else:
        ajuste.pop("terminos_quitados", None)
    if add:
        ajuste["terminos_add"] = add
    else:
        ajuste.pop("terminos_add", None)


def crear_tema(
    overlay: dict,
    nombre: str,
    terminos: dict[str, float],
    capa: str = profile.NUCLEO,
    peso: float = 1.0,
    abre: bool = True,
    consultas_arxiv: list[str] | None = None,
    consultas_texto: list[str] | None = None,
) -> str:
    clave = siguiente_clave_usuario(overlay)
    overlay.setdefault("dominios", {})[clave] = {
        "nombre": nombre,
        "capa": capa,
        "peso": float(peso),
        # Los temas nuevos nacen abriendo: si no, serían inertes. Un tema que
        # no abre solo puede sumar puntos a papers que ya entraron por otra
        # vía, así que crear uno sin esto no traería nada nuevo.
        "abre": bool(abre),
        "activo": True,
        "terminos_add": {t: float(p) for t, p in terminos.items()},
        "consultas_arxiv": consultas_arxiv or consultas_desde_terminos(terminos, "arxiv"),
        "consultas_texto": consultas_texto or consultas_desde_terminos(terminos, "texto"),
    }
    return clave


def borrar_tema(overlay: dict, clave: str) -> bool:
    """Solo se pueden borrar los temas del usuario. Los de la base se apagan."""
    if clave in profile.DOMINIOS:
        fijar(overlay, clave, "activo", False)
        return False
    overlay.get("dominios", {}).pop(clave, None)
    return True


def restaurar_tema(overlay: dict, clave: str) -> None:
    overlay.get("dominios", {}).pop(clave, None)


def restaurar_todo(overlay: dict) -> dict:
    return _overlay_vacio()


# ---------------------------------------------------------------------------
# Consultas derivadas de los términos
# ---------------------------------------------------------------------------

_MULTIPALABRA = re.compile(r"\s")


def consultas_desde_terminos(
    terminos: dict[str, float], estilo: str = "texto", maximo: int = 4
) -> list[str]:
    """Genera consultas de búsqueda a partir de los términos de un tema.

    Sin esto, crear un tema nuevo sería inútil: los términos deciden cómo se
    **ordena** lo que llega, pero las consultas deciden **qué llega**. Un tema
    sin consultas propias solo podría puntuar papers traídos por otros temas.

    Se prefieren las frases de varias palabras y los pesos altos, porque son
    las que discriminan; un término de una sola palabra como "corpus" hace una
    consulta pésima.
    """
    fuertes = sorted(
        (t for t in terminos if _MULTIPALABRA.search(t)),
        key=lambda t: terminos[t],
        reverse=True,
    )
    if not fuertes:
        fuertes = sorted(terminos, key=lambda t: terminos[t], reverse=True)
    fuertes = fuertes[: maximo * 2]

    consultas: list[str] = []
    if estilo == "arxiv":
        for i in range(0, min(len(fuertes), maximo * 2), 2):
            par = fuertes[i : i + 2]
            consultas.append(" OR ".join(f'abs:"{t}"' for t in par))
    else:
        for i in range(0, min(len(fuertes), maximo * 2), 2):
            consultas.append(" ".join(fuertes[i : i + 2]))
    return consultas[:maximo]
