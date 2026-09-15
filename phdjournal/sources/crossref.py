"""Fuente Crossref.

Cubre el registro formal de DOIs: es la que confirma que un preprint ya salió
publicado y en qué revista. Muchos registros no traen abstract, así que
Crossref sirve sobre todo para enriquecer y para el tipo de venue, no como
fuente principal de descubrimiento.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .base import Paper

log = logging.getLogger(__name__)

BASE = "https://api.crossref.org/works"
_JATS = re.compile(r"<[^>]+>")

_TIPOS = {
    "journal-article": "journal",
    "proceedings-article": "conference",
    "posted-content": "preprint",
    "book-chapter": "book",
    "monograph": "book",
}


def _fecha_de(parte: dict | None) -> str:
    if not parte:
        return ""
    partes = (parte.get("date-parts") or [[]])[0]
    if not partes:
        return ""
    y = partes[0]
    m = partes[1] if len(partes) > 1 else 1
    d = partes[2] if len(partes) > 2 else 1
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return str(y)


def _parsear(item: dict) -> Paper | None:
    titulos = item.get("title") or []
    titulo = (titulos[0] if titulos else "").strip()
    if not titulo:
        return None

    resumen = _JATS.sub(" ", item.get("abstract") or "")
    contenedor = item.get("container-title") or []
    fecha = _fecha_de(item.get("published") or item.get("issued"))

    autores = []
    for a in (item.get("author") or [])[:20]:
        nombre = " ".join(x for x in [a.get("given", ""), a.get("family", "")] if x)
        if nombre:
            autores.append(nombre)

    url_pdf = ""
    for enlace in item.get("link") or []:
        if enlace.get("content-type") == "application/pdf":
            url_pdf = enlace.get("URL", "")
            break

    return Paper(
        titulo=titulo,
        resumen=resumen,
        autores=autores,
        doi=item.get("DOI") or "",
        anio=int(fecha[:4]) if fecha[:4].isdigit() else None,
        fecha_pub=fecha,
        venue=contenedor[0] if contenedor else "",
        tipo_venue=_TIPOS.get(item.get("type", ""), "otro"),
        url=item.get("URL") or "",
        url_pdf=url_pdf,
        citas=int(item.get("is-referenced-by-count") or 0),
        fuentes={"crossref"},
        crudo={"editorial": item.get("publisher", "")},
    )


def buscar(
    consultas: list[str],
    max_por_consulta: int = 40,
    ventana_dias: int = 21,
    email: str = "",
    timeout: float = 30.0,
) -> list[Paper]:
    desde = (date.today() - timedelta(days=ventana_dias)).isoformat()
    resultados: list[Paper] = []
    ua = f"PHDjournal/1.0 (mailto:{email})" if email else "PHDjournal/1.0"

    with httpx.Client(timeout=timeout, headers={"User-Agent": ua}, follow_redirects=True) as cli:
        for consulta in consultas:
            # Ordenar por fecha en Crossref ignora la relevancia y devuelve
            # basura: registros sin abstract, de temas ajenos y con fechas
            # imposibles (se vieron 2108 y 2114). Se ordena por relevancia y se
            # exige abstract.
            params = {
                "query.bibliographic": consulta,
                "filter": f"from-pub-date:{desde},type:journal-article,has-abstract:true",
                "rows": str(min(max_por_consulta, 100)),
                "sort": "relevance",
                "order": "desc",
                "select": (
                    "DOI,title,abstract,author,container-title,published,issued,"
                    "type,URL,link,is-referenced-by-count,publisher"
                ),
            }
            if email:
                params["mailto"] = email
            try:
                r = cli.get(BASE, params=params)
                r.raise_for_status()
                datos = r.json()
            except Exception as exc:
                log.warning("Crossref falló en '%s': %s", consulta[:50], exc)
                continue

            limite_futuro = date.today() + timedelta(days=90)
            for item in (datos.get("message") or {}).get("items") or []:
                paper = _parsear(item)
                if paper is None:
                    continue
                f = paper.fecha
                # Crossref tiene registros con fechas de captura absurdas.
                if f is not None and f > limite_futuro:
                    log.debug("Descartado por fecha imposible %s: %s", f, paper.titulo[:50])
                    continue
                resultados.append(paper)

    log.info("Crossref devolvió %d candidatos", len(resultados))
    return resultados
