"""Calidad de venue.

Tabla curada para esta línea de investigación, no un ranking universal. Los
valores son 0..1 y responden a una pregunta concreta: si este trabajo saliera
aquí, ¿cuánto peso tendría en un compendio de tesis de la UAH?

Criterio: se privilegian los venues que ya están en la estrategia de la tesis
(IoTJ, ACM TIoT, JSA) y las conferencias de sistemas y bases de datos que son
el terreno natural del Paper 4. Los preprints no se castigan de más: en Edge
AI arXiv suele ir meses por delante del journal.

Para ajustar un venue basta editar este archivo; los cambios se aplican en la
siguiente corrida sin tocar nada más.
"""

from __future__ import annotations

import re

from .sources.base import normalizar_texto


def _contiene_frase(nombre: str, patron: str) -> bool:
    """¿Aparece ``patron`` como frase completa dentro de ``nombre``?

    Con límites de palabra, para que "science" no coincida dentro de
    "social sciences" ni "micro" dentro de "microsystems".
    """
    return re.search(rf"\b{re.escape(patron)}\b", nombre) is not None

# ---------------------------------------------------------------------------
# EXACTOS: el nombre normalizado del venue debe ser IGUAL al patrón.
#
# Aquí van los nombres genéricos y los acrónimos. Si estos se buscaran por
# subcadena, "science" (la revista Science, 0.98) le daría 0.98 a "Humanities
# and Social Sciences Communications", y "micro" se la daría a
# "Microprocessors and Microsystems". Pasó de verdad en la primera corrida.
# ---------------------------------------------------------------------------
EXACTOS: dict[str, float] = {
    "nature": 1.00,
    "science": 0.98,
    "information": 0.55,
    "computers": 0.58,
    "electronics": 0.55,
    "sensors": 0.60,
    "mathematics": 0.50,
    "applied sciences": 0.55,
    "ieee access": 0.62,
    "plos one": 0.60,
    "scientific reports": 0.70,
    "internet of things": 0.88,
    # Acrónimos de conferencias
    "osdi": 0.98, "sosp": 0.98, "asplos": 0.96, "isca": 0.96, "micro": 0.95,
    "eurosys": 0.94, "nsdi": 0.94, "hpca": 0.94, "fast": 0.92, "ppopp": 0.90,
    "mlsys": 0.92, "sensys": 0.90, "ipsn": 0.88, "mobicom": 0.93,
    "mobisys": 0.91, "ubicomp": 0.87, "percom": 0.82, "iccad": 0.85,
    "dac": 0.88, "date": 0.82, "codes": 0.80, "rtss": 0.88, "emsoft": 0.86,
    "cidr": 0.92, "sigmod": 0.97, "vldb": 0.96, "icde": 0.94, "edbt": 0.85,
    "pods": 0.93, "neurips": 0.96, "icml": 0.96, "iclr": 0.96, "acl": 0.95,
    "emnlp": 0.94, "naacl": 0.92, "eacl": 0.88, "cvpr": 0.94, "aaai": 0.90,
    "ijcai": 0.90, "coling": 0.84, "www": 0.90, "kdd": 0.94, "sigir": 0.93,
    "cikm": 0.85, "wsdm": 0.88, "iswc": 0.88, "eswc": 0.80,
}

# ---------------------------------------------------------------------------
# CONTIENE: se busca como frase completa, con límites de palabra. Solo nombres
# largos y distintivos, donde la coincidencia parcial no puede confundirse.
# ---------------------------------------------------------------------------
TABLA: dict[str, float] = {
    # --- Cima absoluta -------------------------------------------------
    "nature machine intelligence": 1.00,
    "nature communications": 0.95,
    "communications of the acm": 0.90,

    # --- Journals objetivo de la tesis ---------------------------------
    "ieee internet of things journal": 0.95,
    "acm transactions on internet of things": 0.92,
    "journal of systems architecture": 0.88,
    "ieee transactions on parallel and distributed systems": 0.93,
    "ieee transactions on computers": 0.92,
    "ieee transactions on mobile computing": 0.91,
    "acm transactions on computer systems": 0.93,
    "acm transactions on embedded computing systems": 0.87,
    "ieee transactions on knowledge and data engineering": 0.92,
    "acm transactions on database systems": 0.93,
    "the vldb journal": 0.92,
    "future generation computer systems": 0.85,
    "information fusion": 0.88,
    "knowledge based systems": 0.84,
    "expert systems with applications": 0.80,
    "information processing and management": 0.84,
    "journal of web semantics": 0.84,
    "semantic web": 0.80,
    "data and knowledge engineering": 0.78,
    "computational linguistics": 0.90,
    "transactions of the association for computational linguistics": 0.92,
    "ieee transactions on neural networks and learning systems": 0.89,
    "ieee transactions on pattern analysis and machine intelligence": 0.95,
    "journal of machine learning research": 0.92,
    "acm computing surveys": 0.90,

    # --- Conferencias, nombre largo (los acrónimos van en EXACTOS) ------
    "usenix annual technical": 0.93,
    "international conference on architectural support": 0.96,
    "international symposium on computer architecture": 0.96,
    "international symposium on microarchitecture": 0.95,
    "conference on file and storage technologies": 0.92,
    "design automation conference": 0.88,
    "real time systems symposium": 0.88,
    "conference on innovative data systems research": 0.92,
    "international conference on very large data bases": 0.96,
    "international conference on data engineering": 0.94,
    "international conference on management of data": 0.97,
    "extending database technology": 0.85,

    # --- NLP y aprendizaje ------------------------------------------------
    "advances in neural information processing": 0.96,
    "international conference on machine learning": 0.96,
    "international conference on learning representations": 0.96,
    "annual meeting of the association for computational linguistics": 0.95,
    "empirical methods in natural language processing": 0.94,
    "north american chapter of the association for computational": 0.92,
    "conference on computer vision and pattern recognition": 0.94,
    "findings of the association for computational linguistics": 0.80,

    # --- Web, recuperación y grafos ---------------------------------------
    "the web conference": 0.92,
    "international semantic web conference": 0.88,
    "extended semantic web conference": 0.80,
    "knowledge discovery and data mining": 0.94,
    "research and development in information retrieval": 0.93,

    # --- Aceptables, alto volumen ------------------------------------------
    "peerj computer science": 0.62,
    "frontiers in artificial intelligence": 0.58,
    "frontiers in neuroscience": 0.55,

    # --- Preprints ----------------------------------------------------------
    "arxiv": 0.45, "biorxiv": 0.40, "techrxiv": 0.42,
    "research square": 0.35, "preprints org": 0.30,
}

# Por defecto según el tipo, cuando el nombre no está en la tabla.
POR_TIPO = {
    "journal": 0.58,
    "conference": 0.55,
    "preprint": 0.45,
    "book": 0.45,
    "otro": 0.45,
}

# Editoriales depredadoras o de calidad dudosa: castigo fuerte y explícito.
LISTA_NEGRA = ("scirp", "hindawi", "omics", "iiste", "academia journal")


# Cuando no hay nombre de venue, el prefijo del DOI al menos dice quién lo
# publicó. OpenAlex deja sin venue muchas actas de ACM e IEEE.
POR_EDITORIAL_DOI = {
    "10.1145": (0.68, "ACM"),
    "10.1109": (0.68, "IEEE"),
    "10.1016": (0.62, "Elsevier"),
    "10.1007": (0.60, "Springer"),
    "10.1002": (0.58, "Wiley"),
    "10.3390": (0.55, "MDPI"),
    "10.48550": (0.45, "arXiv"),
    "10.5281": (0.35, "Zenodo"),
    "10.54254": (0.30, "editorial de bajo filtro"),
}


def puntuar(venue: str, tipo_venue: str = "otro", doi: str = "") -> tuple[float, str]:
    """Devuelve (puntaje 0..1, explicación corta)."""
    nombre = normalizar_texto(venue or "")
    if not nombre:
        prefijo = (doi or "").split("/")[0].strip().lower()
        if prefijo in POR_EDITORIAL_DOI:
            valor, editorial = POR_EDITORIAL_DOI[prefijo]
            return valor, f"sin nombre de venue, publicado por {editorial}"
        base = POR_TIPO.get(tipo_venue, 0.45)
        return base, f"venue desconocido ({tipo_venue})"

    for marca in LISTA_NEGRA:
        if _contiene_frase(nombre, marca):
            return 0.10, f"editorial de calidad dudosa: {venue}"

    # 1. Coincidencia exacta: para genéricos y acrónimos.
    if nombre in EXACTOS:
        valor = EXACTOS[nombre]
        return valor, f"{venue} (exacto: {valor:.2f})"

    # 2. Frase completa con límites de palabra. La más larga gana, para que
    #    "ieee transactions on computers" le gane a una entrada más corta.
    mejor_patron = ""
    mejor_valor = 0.0
    for patron, valor in TABLA.items():
        if len(patron) > len(mejor_patron) and _contiene_frase(nombre, patron):
            mejor_patron, mejor_valor = patron, valor

    if mejor_patron:
        return mejor_valor, f"{venue} (tabla: {mejor_valor:.2f})"

    # Sin coincidencia en la tabla, el prefijo del DOI afina la base.
    prefijo = (doi or "").split("/")[0].strip().lower()
    if prefijo in POR_EDITORIAL_DOI:
        valor, editorial = POR_EDITORIAL_DOI[prefijo]
        return valor, f"{venue} (sin tabla, {editorial} {valor:.2f})"

    base = POR_TIPO.get(tipo_venue, 0.45)
    return base, f"{venue} (sin tabla, base {tipo_venue} {base:.2f})"
