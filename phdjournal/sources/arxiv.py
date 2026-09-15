"""Fuente arXiv.

API Atom pública, sin clave. arXiv pide un retardo de ~3 s entre peticiones;
se respeta en ``buscar``. Es la fuente que llega primero a los preprints, que
en Edge AI suelen anticipar en meses a la versión de journal.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .base import Paper

log = logging.getLogger(__name__)

BASE = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
PAUSA_S = 3.0


def _texto(nodo, ruta: str) -> str:
    hijo = nodo.find(ruta, NS)
    return (hijo.text or "").strip() if hijo is not None else ""


def _parsear_entrada(entrada) -> Paper | None:
    titulo = _texto(entrada, "atom:title")
    if not titulo:
        return None

    url_abs = _texto(entrada, "atom:id")
    url_pdf = ""
    for link in entrada.findall("atom:link", NS):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            url_pdf = link.get("href", "")
            break
    if not url_pdf and url_abs:
        url_pdf = url_abs.replace("/abs/", "/pdf/")

    publicado = _texto(entrada, "atom:published")[:10]
    journal_ref = _texto(entrada, "arxiv:journal_ref")
    categoria = ""
    prim = entrada.find("arxiv:primary_category", NS)
    if prim is not None:
        categoria = prim.get("term", "")

    return Paper(
        titulo=titulo,
        resumen=_texto(entrada, "atom:summary"),
        autores=[
            (a.text or "").strip()
            for a in entrada.findall("atom:author/atom:name", NS)
        ],
        doi=_texto(entrada, "arxiv:doi"),
        arxiv_id=url_abs,
        fecha_pub=publicado,
        anio=int(publicado[:4]) if publicado[:4].isdigit() else None,
        venue=journal_ref or "arXiv",
        tipo_venue="journal" if journal_ref else "preprint",
        url=url_abs,
        url_pdf=url_pdf,
        fuentes={"arxiv"},
        crudo={"categoria_arxiv": categoria, "journal_ref": journal_ref},
    )


def buscar(
    consultas: list[str],
    categorias: list[str],
    max_por_consulta: int = 60,
    ventana_dias: int = 21,
    timeout: float = 30.0,
) -> list[Paper]:
    """Ejecuta cada consulta y devuelve los papers dentro de la ventana."""
    corte = date.today() - timedelta(days=ventana_dias)
    filtro_cat = " OR ".join(f"cat:{c}" for c in categorias)
    resultados: list[Paper] = []

    # follow_redirects: export.arxiv.org responde 301 de http a https.
    with httpx.Client(
        timeout=timeout, headers={"User-Agent": "PHDjournal/1.0"}, follow_redirects=True
    ) as cli:
        for i, consulta in enumerate(consultas):
            if i:
                time.sleep(PAUSA_S)
            completa = f"({consulta}) AND ({filtro_cat})" if filtro_cat else consulta
            params = {
                "search_query": completa,
                "start": "0",
                "max_results": str(max_por_consulta),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            url = f"{BASE}?{urllib.parse.urlencode(params)}"
            try:
                r = cli.get(url)
                r.raise_for_status()
                raiz = ET.fromstring(r.content)
            except Exception as exc:
                log.warning("arXiv falló en '%s': %s", consulta[:50], exc)
                continue

            for entrada in raiz.findall("atom:entry", NS):
                paper = _parsear_entrada(entrada)
                if paper is None:
                    continue
                f = paper.fecha
                if f is not None and f < corte:
                    continue
                resultados.append(paper)

    log.info("arXiv devolvió %d candidatos", len(resultados))
    return resultados
