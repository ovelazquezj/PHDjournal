"""Fuente OpenAlex.

Gratis y sin clave. Es la pieza que da metadatos de IEEE, ACM, Elsevier y
Springer, que no publican APIs abiertas. También trae el conteo de citas y
señales de calidad de la revista, que alimentan el ranking.

El resumen viene como índice invertido, hay que reconstruirlo.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .base import Paper

log = logging.getLogger(__name__)

BASE = "https://api.openalex.org/works"
MAX_REINTENTOS = 3
PAUSA_429 = 2.0

# OpenAlex llama "type" al tipo de obra y "type" también al del venue.
_TIPOS_VENUE = {
    "journal": "journal",
    "conference": "conference",
    "repository": "preprint",
    "book series": "book",
    "ebook platform": "book",
}

# Respaldo por tipo de obra cuando ninguna localización trae tipo de venue.
_TIPOS_OBRA = {
    "article": "journal",
    "journal-article": "journal",
    "proceedings-article": "conference",
    "preprint": "preprint",
    "posted-content": "preprint",
    "book-chapter": "book",
    "book": "book",
}


def _reconstruir_resumen(indice: dict | None) -> str:
    """Convierte abstract_inverted_index en texto plano."""
    if not indice:
        return ""
    posiciones: list[tuple[int, str]] = []
    for palabra, indices in indice.items():
        for i in indices:
            posiciones.append((i, palabra))
    posiciones.sort()
    return " ".join(p for _, p in posiciones)


def _parsear(obra: dict) -> Paper | None:
    titulo = (obra.get("title") or obra.get("display_name") or "").strip()
    if not titulo:
        return None

    fuente_primaria = (obra.get("primary_location") or {}).get("source") or {}
    venue = fuente_primaria.get("display_name") or ""
    tipo_venue = _TIPOS_VENUE.get((fuente_primaria.get("type") or "").lower(), "")

    ids = obra.get("ids") or {}
    arxiv_id = ""
    for loc in obra.get("locations") or []:
        fuente = loc.get("source") or {}
        nombre = fuente.get("display_name") or ""
        if "arxiv" in nombre.lower():
            arxiv_id = loc.get("landing_page_url") or ""
            continue
        # primary_location.source viene nulo en muchos actas de ACM e IEEE;
        # el nombre del venue sí está en alguna de las otras localizaciones.
        if not venue and nombre:
            venue = nombre
            tipo_venue = _TIPOS_VENUE.get((fuente.get("type") or "").lower(), "")

    if not tipo_venue:
        tipo_obra = (obra.get("type") or "").lower()
        tipo_venue = _TIPOS_OBRA.get(tipo_obra, "preprint" if not venue else "otro")

    oa = obra.get("open_access") or {}
    url_pdf = (obra.get("best_oa_location") or {}).get("pdf_url") or ""

    fecha = obra.get("publication_date") or ""
    autores = [
        (a.get("author") or {}).get("display_name", "")
        for a in (obra.get("authorships") or [])[:20]
    ]

    return Paper(
        titulo=titulo,
        resumen=_reconstruir_resumen(obra.get("abstract_inverted_index")),
        autores=[a for a in autores if a],
        doi=obra.get("doi") or ids.get("doi") or "",
        arxiv_id=arxiv_id,
        anio=obra.get("publication_year"),
        fecha_pub=fecha,
        venue=venue,
        tipo_venue=tipo_venue,
        url=obra.get("doi") or ids.get("openalex") or "",
        url_pdf=url_pdf,
        citas=int(obra.get("cited_by_count") or 0),
        fuentes={"openalex"},
        crudo={
            "openalex_id": ids.get("openalex", ""),
            "es_oa": bool(oa.get("is_oa")),
            "fwci": obra.get("fwci"),
            "venue_is_oa": fuente_primaria.get("is_oa"),
            "venue_issn_l": fuente_primaria.get("issn_l"),
        },
    )


def buscar(
    consultas: list[str],
    max_por_consulta: int = 50,
    ventana_dias: int = 21,
    email: str = "",
    timeout: float = 30.0,
) -> list[Paper]:
    desde = (date.today() - timedelta(days=ventana_dias)).isoformat()
    resultados: list[Paper] = []
    cabeceras = {"User-Agent": f"PHDjournal/1.0 (mailto:{email})" if email else "PHDjournal/1.0"}

    with httpx.Client(timeout=timeout, headers=cabeceras, follow_redirects=True) as cli:
        for consulta in consultas:
            params = {
                "filter": f"from_publication_date:{desde},title_and_abstract.search:{consulta}",
                "per-page": str(min(max_por_consulta, 200)),
                "sort": "publication_date:desc",
                "select": (
                    "id,ids,doi,title,display_name,publication_year,publication_date,"
                    "type,cited_by_count,fwci,authorships,primary_location,locations,"
                    "best_oa_location,open_access,abstract_inverted_index"
                ),
            }
            if email:
                params["mailto"] = email

            # OpenAlex tiene límite por ráfaga. Con dos corridas al día no se
            # roza, pero varias búsquedas manuales seguidas sí lo disparan, y
            # sin reintento un 429 dejaba la fuente entera en cero.
            datos = None
            for intento in range(MAX_REINTENTOS):
                try:
                    r = cli.get(BASE, params=params)
                    if r.status_code == 429:
                        espera = PAUSA_429 * (2 ** intento)
                        log.info("OpenAlex 429, esperando %.1fs", espera)
                        time.sleep(espera)
                        continue
                    r.raise_for_status()
                    datos = r.json()
                    break
                except Exception as exc:
                    log.warning("OpenAlex falló en '%s': %s", consulta[:50], exc)
                    break
            if not datos:
                continue

            for obra in datos.get("results", []):
                paper = _parsear(obra)
                if paper is not None:
                    resultados.append(paper)

    log.info("OpenAlex devolvió %d candidatos", len(resultados))
    return resultados
