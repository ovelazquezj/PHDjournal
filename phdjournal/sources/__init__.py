"""Recolección de candidatos desde las cuatro fuentes, en paralelo.

Cada fuente corre en su propio hilo. Si una falla o se queda sin cuota, las
demás siguen: una corrida nunca se cae entera por culpa de un solo servicio.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import profile  # noqa: F401  (categorías arXiv por defecto)
from ..config import Config
from .base import Paper, fusionar_lista

log = logging.getLogger(__name__)


def recolectar(
    cfg: Config, perfil=None
) -> tuple[list[Paper], dict[str, str]]:
    """Devuelve (candidatos fusionados, estado por fuente).

    Las consultas salen del perfil fusionado, no de una lista fija: si el
    usuario apaga un tema en la configuración, sus consultas dejan de correr.
    """
    from .. import temas
    from . import arxiv, crossref, openalex, semantic_scholar

    perfil = perfil if perfil is not None else temas.construir()
    tareas = {}
    estado: dict[str, str] = {}

    log.info(
        "%d temas activos, %d consultas arXiv, %d de texto",
        len(perfil.dominios), len(perfil.consultas_arxiv), len(perfil.consultas_texto),
    )

    def _arxiv() -> list[Paper]:
        return arxiv.buscar(
            perfil.consultas_arxiv,
            perfil.categorias_arxiv,
            max_por_consulta=cfg.candidatos_por_fuente,
            ventana_dias=cfg.ventana_dias,
        )

    def _openalex() -> list[Paper]:
        return openalex.buscar(
            perfil.consultas_texto,
            max_por_consulta=cfg.candidatos_por_fuente,
            ventana_dias=cfg.ventana_dias,
            email=cfg.email_contacto,
        )

    def _s2() -> list[Paper]:
        return semantic_scholar.buscar(
            perfil.consultas_texto,
            max_por_consulta=min(cfg.candidatos_por_fuente, 40),
            ventana_dias=cfg.ventana_dias,
            clave_api=cfg.get_clave_s2(),
        )

    def _crossref() -> list[Paper]:
        return crossref.buscar(
            perfil.consultas_texto,
            max_por_consulta=min(cfg.candidatos_por_fuente, 40),
            ventana_dias=cfg.ventana_dias,
            email=cfg.email_contacto,
        )

    funciones = {
        "arxiv": _arxiv,
        "openalex": _openalex,
        "semantic_scholar": _s2,
        "crossref": _crossref,
    }
    activas = [f for f in cfg.fuentes_activas if f in funciones]

    crudos: list[Paper] = []
    with ThreadPoolExecutor(max_workers=len(activas) or 1) as pool:
        for nombre in activas:
            tareas[pool.submit(funciones[nombre])] = nombre
        for futuro in as_completed(tareas):
            nombre = tareas[futuro]
            try:
                papers = futuro.result()
                crudos.extend(papers)
                estado[nombre] = f"{len(papers)} candidatos"
            except Exception as exc:
                log.exception("Fuente %s falló por completo", nombre)
                estado[nombre] = f"error: {exc}"

    fusionados = fusionar_lista(crudos)
    log.info("%d crudos -> %d tras fusionar duplicados", len(crudos), len(fusionados))
    return fusionados, estado
