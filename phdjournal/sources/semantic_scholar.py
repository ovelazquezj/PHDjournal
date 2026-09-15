"""Fuente Semantic Scholar (Graph API).

Sin clave funciona, pero con cuota estrecha y respuestas 429 frecuentes. Se
maneja con reintento y retroceso; si la fuente se cae, la corrida sigue con
las otras tres. Aporta ``influentialCitationCount``, que distingue una cita
de fondo de una de trámite.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .base import Paper

log = logging.getLogger(__name__)

BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
CAMPOS = (
    "title,abstract,year,publicationDate,authors,venue,publicationVenue,"
    "citationCount,influentialCitationCount,externalIds,openAccessPdf,"
    "publicationTypes,url"
)
PAUSA_S = 3.5
# Sin clave, esta API responde 429 casi siempre. No vale la pena insistir:
# las otras tres fuentes ya cubren la corrida. Con clave gratuita sí responde.
MAX_REINTENTOS_SIN_CLAVE = 1
MAX_REINTENTOS_CON_CLAVE = 3


def _parsear(item: dict) -> Paper | None:
    titulo = (item.get("title") or "").strip()
    if not titulo:
        return None

    ext = item.get("externalIds") or {}
    pv = item.get("publicationVenue") or {}
    tipos = item.get("publicationTypes") or []

    tipo_venue = "otro"
    tipo_pv = (pv.get("type") or "").lower()
    if tipo_pv == "journal":
        tipo_venue = "journal"
    elif tipo_pv == "conference":
        tipo_venue = "conference"
    elif "JournalArticle" in tipos:
        tipo_venue = "journal"
    elif "Conference" in tipos:
        tipo_venue = "conference"
    if ext.get("ArXiv") and not item.get("venue"):
        tipo_venue = "preprint"

    return Paper(
        titulo=titulo,
        resumen=item.get("abstract") or "",
        autores=[a.get("name", "") for a in (item.get("authors") or [])[:20]],
        doi=ext.get("DOI") or "",
        arxiv_id=ext.get("ArXiv") or "",
        anio=item.get("year"),
        fecha_pub=item.get("publicationDate") or "",
        venue=item.get("venue") or pv.get("name") or "",
        tipo_venue=tipo_venue,
        url=item.get("url") or "",
        url_pdf=(item.get("openAccessPdf") or {}).get("url") or "",
        citas=int(item.get("citationCount") or 0),
        fuentes={"semantic_scholar"},
        crudo={"citas_influyentes": int(item.get("influentialCitationCount") or 0)},
    )


def buscar(
    consultas: list[str],
    max_por_consulta: int = 40,
    ventana_dias: int = 21,
    clave_api: str = "",
    timeout: float = 30.0,
) -> list[Paper]:
    corte = date.today() - timedelta(days=ventana_dias)
    anio_desde = corte.year
    resultados: list[Paper] = []

    cabeceras = {"User-Agent": "PHDjournal/1.0"}
    if clave_api:
        cabeceras["x-api-key"] = clave_api
    reintentos = MAX_REINTENTOS_CON_CLAVE if clave_api else MAX_REINTENTOS_SIN_CLAVE

    ahogada = False
    with httpx.Client(timeout=timeout, headers=cabeceras) as cli:
        for i, consulta in enumerate(consultas):
            if ahogada:
                break
            if i:
                time.sleep(PAUSA_S)
            params = {
                "query": consulta,
                "limit": str(min(max_por_consulta, 100)),
                "fields": CAMPOS,
                "year": f"{anio_desde}-",
            }
            datos = None
            for intento in range(reintentos):
                try:
                    r = cli.get(BASE, params=params)
                    if r.status_code == 429:
                        if intento + 1 >= reintentos:
                            # La cuota está agotada para toda la corrida; seguir
                            # pidiendo solo gasta tiempo de reloj.
                            ahogada = True
                            log.info(
                                "Semantic Scholar sin cuota (429). Se omite esta "
                                "fuente. Una clave gratuita en Configuración > "
                                "Fuentes la reactiva."
                            )
                            break
                        time.sleep(PAUSA_S * (2 ** intento))
                        continue
                    r.raise_for_status()
                    datos = r.json()
                    break
                except Exception as exc:
                    log.warning(
                        "Semantic Scholar falló en '%s' (intento %d): %s",
                        consulta[:40], intento + 1, exc,
                    )
                    break
            if not datos:
                continue

            for item in datos.get("data") or []:
                paper = _parsear(item)
                if paper is None:
                    continue
                f = paper.fecha
                if f is not None and f < corte:
                    continue
                resultados.append(paper)

    log.info("Semantic Scholar devolvió %d candidatos", len(resultados))
    return resultados
