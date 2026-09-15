"""Modelo común de paper y utilidades de identidad.

Cada fuente devuelve objetos ``Paper``. La identidad se resuelve en este
orden: DOI normalizado, id de arXiv, hash del título normalizado. Así el mismo
trabajo encontrado en arXiv y en OpenAlex colapsa en un solo registro y suma
las dos fuentes en vez de aparecer dos veces en la lista de cinco.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


_ESPACIOS = re.compile(r"\s+")
_NO_ALFANUM = re.compile(r"[^a-z0-9 ]+")


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin acentos, sin puntuación, espacios colapsados."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = _NO_ALFANUM.sub(" ", texto)
    return _ESPACIOS.sub(" ", texto).strip()


def normalizar_doi(doi: str | None) -> str:
    if not doi:
        return ""
    doi = doi.strip().lower()
    for prefijo in ("https://doi.org/", "http://doi.org/", "doi:", "https://dx.doi.org/"):
        if doi.startswith(prefijo):
            doi = doi[len(prefijo):]
    return doi.strip()


def normalizar_arxiv(valor: str | None) -> str:
    """Devuelve el id base de arXiv, sin versión ni URL. '2401.12345v3' -> '2401.12345'."""
    if not valor:
        return ""
    valor = valor.strip().lower()
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", valor)
    if m:
        return m.group(1)
    m = re.search(r"([a-z-]+(?:\.[a-z]{2})?/\d{7})(v\d+)?", valor)
    return m.group(1) if m else ""


@dataclass
class Paper:
    titulo: str
    resumen: str = ""
    autores: list[str] = field(default_factory=list)
    doi: str = ""
    arxiv_id: str = ""
    anio: int | None = None
    fecha_pub: str = ""          # ISO 'YYYY-MM-DD'
    venue: str = ""
    tipo_venue: str = ""         # journal | conference | preprint | book | otro
    url: str = ""
    url_pdf: str = ""
    citas: int = 0
    fuentes: set[str] = field(default_factory=set)
    crudo: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.doi = normalizar_doi(self.doi)
        self.arxiv_id = normalizar_arxiv(self.arxiv_id)
        self.titulo = _ESPACIOS.sub(" ", (self.titulo or "").strip())
        self.resumen = _ESPACIOS.sub(" ", (self.resumen or "").strip())

    @property
    def id(self) -> str:
        if self.doi:
            return "doi:" + self.doi
        if self.arxiv_id:
            return "arxiv:" + self.arxiv_id
        h = hashlib.sha1(normalizar_texto(self.titulo).encode("utf-8")).hexdigest()
        return "titulo:" + h[:20]

    @property
    def texto_busqueda(self) -> str:
        return normalizar_texto(f"{self.titulo} {self.resumen}")

    @property
    def fecha(self) -> date | None:
        if self.fecha_pub:
            for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
                try:
                    return datetime.strptime(self.fecha_pub[: len(fmt.replace("%Y", "2000"))], fmt).date()
                except ValueError:
                    continue
        if self.anio:
            try:
                return date(self.anio, 7, 1)
            except ValueError:
                return None
        return None

    def fusionar(self, otro: "Paper") -> None:
        """Absorbe los datos de un duplicado encontrado en otra fuente."""
        if len(otro.resumen) > len(self.resumen):
            self.resumen = otro.resumen
        if len(otro.autores) > len(self.autores):
            self.autores = otro.autores
        self.doi = self.doi or otro.doi
        self.arxiv_id = self.arxiv_id or otro.arxiv_id
        self.anio = self.anio or otro.anio
        self.fecha_pub = self.fecha_pub or otro.fecha_pub
        self.url = self.url or otro.url
        self.url_pdf = self.url_pdf or otro.url_pdf
        self.citas = max(self.citas, otro.citas)
        # Un venue real le gana a "arXiv"
        if otro.venue and (not self.venue or self.tipo_venue == "preprint"):
            if otro.tipo_venue != "preprint":
                self.venue = otro.venue
                self.tipo_venue = otro.tipo_venue
        self.fuentes |= otro.fuentes
        self.crudo.update(otro.crudo)


def fusionar_lista(papers: list[Paper]) -> list[Paper]:
    """Colapsa duplicados. Además del id, empareja por título normalizado."""
    por_id: dict[str, Paper] = {}
    por_titulo: dict[str, str] = {}

    for p in papers:
        if not p.titulo:
            continue
        clave_titulo = normalizar_texto(p.titulo)
        if len(clave_titulo) < 15:
            continue

        destino_id = None
        if p.id in por_id:
            destino_id = p.id
        elif clave_titulo in por_titulo:
            destino_id = por_titulo[clave_titulo]

        if destino_id is not None:
            por_id[destino_id].fusionar(p)
            por_titulo.setdefault(clave_titulo, destino_id)
        else:
            por_id[p.id] = p
            por_titulo[clave_titulo] = p.id

    return list(por_id.values())
