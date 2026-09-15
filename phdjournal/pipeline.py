"""La corrida completa: buscar, rankear, resumir, guardar.

Se ejecuta dos veces al día por el programador interno, y también a mano desde
el botón "Buscar ahora". Todo el progreso se reporta por callback para que la
interfaz pueda mostrarlo sin congelarse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from . import db, ranking, sources, summarize, temas
from .config import DIR_DATOS, Config
from .sources.base import Paper

log = logging.getLogger(__name__)

Progreso = Callable[[str, int], None]  # (mensaje, porcentaje 0..100)

# Los candidatos de la última corrida se guardan en crudo para que el banco de
# pruebas de la pantalla de Temas pueda rankearlos con un perfil editado sin
# volver a pedir nada a la red ni gastar en la API.
RUTA_CANDIDATOS = DIR_DATOS / "ultimos_candidatos.json"


def guardar_candidatos(candidatos: list[Paper]) -> None:
    import json

    try:
        datos = [
            {
                "titulo": p.titulo, "resumen": p.resumen, "autores": p.autores,
                "doi": p.doi, "arxiv_id": p.arxiv_id, "anio": p.anio,
                "fecha_pub": p.fecha_pub, "venue": p.venue,
                "tipo_venue": p.tipo_venue, "url": p.url, "url_pdf": p.url_pdf,
                "citas": p.citas, "fuentes": sorted(p.fuentes),
            }
            for p in candidatos
        ]
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        RUTA_CANDIDATOS.write_text(
            json.dumps(datos, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        log.warning("No se pudieron cachear los candidatos: %s", exc)


def cargar_candidatos() -> list[Paper]:
    """Los candidatos de la última corrida, para el banco de pruebas."""
    import json

    if not RUTA_CANDIDATOS.exists():
        return []
    try:
        datos = json.loads(RUTA_CANDIDATOS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    salida = []
    for d in datos:
        d = dict(d)
        d["fuentes"] = set(d.get("fuentes", []))
        try:
            salida.append(Paper(**d))
        except TypeError:
            continue
    return salida


@dataclass
class ResultadoCorrida:
    corrida_id: int
    franja: str
    n_candidatos: int
    n_mostrados: int
    estado_fuentes: dict[str, str]
    errores_resumen: list[str]

    @property
    def hubo_papers(self) -> bool:
        return self.n_mostrados > 0


def _nada(_mensaje: str, _pct: int) -> None:
    pass


def ejecutar(
    cfg: Config, franja: str = "manual", progreso: Progreso | None = None
) -> ResultadoCorrida:
    progreso = progreso or _nada
    db.inicializar()
    perfil = temas.construir()

    with db.conexion() as con:
        corrida_id = db.abrir_corrida(con, franja)
        ya_vistos = db.ids_ya_mostrados(con)

    log.info(
        "Corrida %s (%s), %d papers ya mostrados antes", corrida_id, franja, len(ya_vistos)
    )

    # --- 1. Recolectar --------------------------------------------------
    progreso("Consultando arXiv, OpenAlex, Semantic Scholar y Crossref...", 5)
    try:
        candidatos, estado_fuentes = sources.recolectar(cfg, perfil)
    except Exception as exc:
        log.exception("La recolección falló por completo")
        with db.conexion() as con:
            db.cerrar_corrida(con, corrida_id, 0, 0, error=str(exc))
        raise

    progreso(f"{len(candidatos)} candidatos únicos encontrados", 35)
    guardar_candidatos(candidatos)

    # --- 2. Rankear ------------------------------------------------------
    progreso("Puntuando con el ranking híbrido...", 45)
    ordenados = ranking.ordenar(candidatos, cfg, excluir=ya_vistos, perfil=perfil)
    elegidos = ordenados[: cfg.papers_por_corrida]

    if not elegidos:
        progreso("No hubo nada nuevo que valga la pena", 100)
        with db.conexion() as con:
            db.cerrar_corrida(con, corrida_id, len(candidatos), 0)
        return ResultadoCorrida(corrida_id, franja, len(candidatos), 0, estado_fuentes, [])

    # --- 3. Persistir la selección ---------------------------------------
    with db.conexion() as con:
        for puesto, (paper, puntaje) in enumerate(elegidos, start=1):
            db.guardar_paper(con, paper)
            db.registrar_seleccion(
                con, corrida_id, paper.id, puesto, puntaje.total,
                puntaje.como_dict(), puntaje.trabajo,
            )

    # --- 4. Resumir -------------------------------------------------------
    errores: list[str] = []
    if not cfg.tiene_clave():
        errores.append(
            "Sin clave de Claude: se muestran los abstracts originales, sin resumen."
        )
        progreso("Falta la clave de la API, se omiten los resúmenes", 95)
    else:
        total = len(elegidos)
        for i, (paper, puntaje) in enumerate(elegidos, start=1):
            pct = 55 + int(40 * (i - 1) / max(total, 1))
            progreso(f"Resumiendo {i} de {total}: {paper.titulo[:60]}...", pct)
            try:
                resumen, t_in, t_out = summarize.resumir(paper, puntaje, cfg)
                with db.conexion() as con:
                    db.guardar_resumen(
                        con, paper.id, cfg.idioma_resumen, cfg.modelo_claude,
                        resumen, t_in, t_out, generado_por_ia=True,
                    )
            except Exception as exc:
                log.warning("No se pudo resumir '%s': %s", paper.titulo[:50], exc)
                errores.append(f"{paper.titulo[:50]}: {exc}")

    # --- 5. Cerrar ---------------------------------------------------------
    with db.conexion() as con:
        db.cerrar_corrida(con, corrida_id, len(candidatos), len(elegidos))

    progreso(f"Listo: {len(elegidos)} papers para leer", 100)
    return ResultadoCorrida(
        corrida_id, franja, len(candidatos), len(elegidos), estado_fuentes, errores
    )


def paper_desde_fila(fila) -> Paper:
    """Reconstruye un Paper a partir de una fila de la base."""
    import json

    return Paper(
        titulo=fila["titulo"],
        resumen=fila["resumen_origen"] or "",
        autores=json.loads(fila["autores"] or "[]"),
        doi=fila["doi"] or "",
        arxiv_id=fila["arxiv_id"] or "",
        anio=fila["anio"],
        fecha_pub=fila["fecha_pub"] or "",
        venue=fila["venue"] or "",
        tipo_venue=fila["tipo_venue"] or "otro",
        url=fila["url"] or "",
        url_pdf=fila["url_pdf"] or "",
        citas=fila["citas"] or 0,
        fuentes=set(json.loads(fila["fuentes"] or "[]")),
        crudo=json.loads(fila["crudo"] or "{}"),
    )
