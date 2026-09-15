"""Biblioteca local de PDFs.

Descarga el PDF cuando el trabajo es de acceso abierto, lo guarda con un
nombre estable y sabe partirlo en secciones para poder escucharlo por partes.

No intenta saltarse muros de pago. Si no hay un PDF abierto, la ficha ofrece
abrir la página del editor en el navegador y ya.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .sources.base import Paper, normalizar_texto

log = logging.getLogger(__name__)

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Encabezados de sección típicos en papers de CS.
_SECCIONES = re.compile(
    r"^\s*(?:\d+\.?\s+)?("
    r"abstract|introduction|related work|background|motivation|"
    r"method(?:s|ology)?|approach|design|implementation|system|architecture|"
    r"experiment(?:s|al setup)?|evaluation|results|discussion|"
    r"limitations|threats to validity|conclusion(?:s)?|future work|"
    r"acknowledg(?:e)?ments|references"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def nombre_archivo(paper: Paper) -> str:
    autor = (paper.autores[0].rsplit(" ", 1)[-1] if paper.autores else "anon")
    autor = _INVALIDOS.sub("", autor)[:24] or "anon"
    anio = paper.anio or "sf"
    titulo = _INVALIDOS.sub("", paper.titulo)[:70].strip().rstrip(".")
    return f"{autor} {anio} - {titulo}.pdf"


def descargar(paper: Paper, dir_biblioteca: Path, timeout: float = 90.0) -> Path:
    """Descarga el PDF de acceso abierto. Lanza si no hay o si no es un PDF."""
    if not paper.url_pdf:
        raise FileNotFoundError("Este trabajo no tiene PDF de acceso abierto conocido.")

    destino = dir_biblioteca / nombre_archivo(paper)
    if destino.exists() and destino.stat().st_size > 20_000:
        return destino

    dir_biblioteca.mkdir(parents=True, exist_ok=True)
    cabeceras = {"User-Agent": "PHDjournal/1.0 (lector personal de papers)"}

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=cabeceras) as cli:
        r = cli.get(paper.url_pdf)
        r.raise_for_status()
        contenido = r.content

    if not contenido.startswith(b"%PDF"):
        raise ValueError(
            "Lo que descargó no es un PDF. Suele pasar con muros de pago o "
            "páginas de aterrizaje: abre el enlace en el navegador."
        )

    tmp = destino.with_suffix(".parcial")
    tmp.write_bytes(contenido)
    tmp.replace(destino)
    log.info("PDF guardado en %s (%.1f KB)", destino, len(contenido) / 1024)
    return destino


def extraer_texto(ruta: Path) -> str:
    import fitz  # PyMuPDF

    with fitz.open(ruta) as doc:
        return "\n".join(pagina.get_text() for pagina in doc)


def partir_en_secciones(texto: str, minimo_chars: int = 400) -> list[tuple[str, str]]:
    """Devuelve [(título de sección, texto)]. Si no reconoce nada, un solo bloque."""
    coincidencias = list(_SECCIONES.finditer(texto))
    if not coincidencias:
        return [("Documento completo", texto)]

    secciones: list[tuple[str, str]] = []
    preambulo = texto[: coincidencias[0].start()].strip()
    if len(preambulo) >= minimo_chars:
        secciones.append(("Portada y resumen", preambulo))

    for i, m in enumerate(coincidencias):
        titulo = m.group(1).strip().title()
        inicio = m.end()
        fin = coincidencias[i + 1].start() if i + 1 < len(coincidencias) else len(texto)
        cuerpo = texto[inicio:fin].strip()
        if normalizar_texto(titulo) in ("references", "acknowledgments", "acknowledgements"):
            continue
        if len(cuerpo) >= minimo_chars:
            secciones.append((titulo, cuerpo))

    return secciones or [("Documento completo", texto)]
