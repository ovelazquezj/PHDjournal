"""Documentos locales: PDFs que ya tienes en tu disco.

Es un flujo aparte de la búsqueda diaria, a propósito:

* no pasa por las fuentes de descubrimiento ni por el ranking;
* no cuenta como "ya mostrado", así que nunca le quita un lugar a un paper
  nuevo de la búsqueda;
* se guarda en tablas propias (``documentos``, ``resumenes_documentos``).

Lo único que sale a la red es la resolución del DOI (doi.org, con Crossref de
respaldo) para completar los metadatos, y la API de Claude para el resumen.

Metadatos completos, en este orden de confianza:

1. **DOI verificado.** Se busca el DOI en las primeras páginas y en los
   metadatos del PDF; un id de arXiv también vale, porque arXiv registra DOIs
   (``10.48550/arXiv.XXXX``). El DOI se resuelve y **se verifica**: el título
   que devuelve tiene que aparecer en la portada. Sin esa verificación, un DOI
   citado en la primera página (pasa mucho) le pondría al documento los
   metadatos de otro trabajo.
2. **Lo que lee Claude en la portada**, si no hubo DOI. Queda marcado como no
   verificado y la ficha pide el DOI a mano.
3. **Los metadatos embebidos del PDF**, si tampoco hay clave de Claude.

El PDF se copia a ``data/biblioteca/locales``: si borras o mueves el original,
la app sigue teniendo el suyo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from . import db, ranking, summarize
from . import pdf as pdf_mod
from .config import Config
from .sources.base import Paper, normalizar_arxiv, normalizar_doi, normalizar_texto

log = logging.getLogger(__name__)

Progreso = Callable[[str], None]

# Menos texto que esto en todo el PDF es casi seguro un escaneo sin capa de
# texto. El OCR queda fuera de alcance.
MIN_CHARS_TEXTO = 800

# Cuántas páginas cuentan como "portada" para buscar el DOI y verificar.
PAGINAS_PORTADA = 2

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.IGNORECASE)
_ARXIV = re.compile(r"arxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ETIQUETAS = re.compile(r"<[^>]+>")

# Tipos de CSL (doi.org) y de Crossref, al vocabulario de la app.
_TIPOS = {
    "article-journal": "journal", "journal-article": "journal",
    "paper-conference": "conference", "proceedings-article": "conference",
    "posted-content": "preprint", "article": "preprint",
    "chapter": "book", "book-chapter": "book", "book": "book", "monograph": "book",
    "thesis": "thesis", "dissertation": "thesis",
    "report": "report",
}


class ErrorDocumento(RuntimeError):
    pass


@dataclass
class Resultado:
    ruta: Path
    estado: str                 # nuevo | duplicado | sin_texto | error
    mensaje: str
    doc_id: str | None = None
    verificado: bool = False
    resumido: bool = False


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------

def buscar_pdfs(rutas: list[Path | str]) -> list[Path]:
    """Expande carpetas (recursivo) y filtra a PDFs, sin repetir."""
    vistos: set[Path] = set()
    salida: list[Path] = []
    for r in rutas:
        r = Path(r)
        candidatos = (
            sorted(p for p in r.rglob("*") if p.suffix.lower() == ".pdf")
            if r.is_dir() else [r]
        )
        for p in candidatos:
            if p.is_file() and p.suffix.lower() == ".pdf":
                clave = p.resolve()
                if clave not in vistos:
                    vistos.add(clave)
                    salida.append(p)
    return salida


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def dir_locales(cfg: Config) -> Path:
    ruta = cfg.dir_biblioteca / "locales"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


@dataclass
class Extraido:
    texto: str
    portada: str
    n_paginas: int
    meta_pdf: dict


def extraer(ruta: Path) -> Extraido:
    try:
        import pymupdf
    except ImportError:  # PyMuPDF viejo
        import fitz as pymupdf  # type: ignore

    with pymupdf.open(ruta) as doc:
        paginas = [p.get_text() for p in doc]
        meta = dict(doc.metadata or {})
    return Extraido(
        texto="\n".join(paginas),
        portada="\n".join(paginas[:PAGINAS_PORTADA]),
        n_paginas=len(paginas),
        meta_pdf=meta,
    )


# ---------------------------------------------------------------------------
# DOI: detección, resolución y verificación
# ---------------------------------------------------------------------------

def candidatos_doi(portada: str, meta_pdf: dict) -> list[str]:
    """DOIs posibles, en orden de aparición. El de arXiv al final."""
    fuentes = " ".join(
        str(meta_pdf.get(k) or "") for k in ("doi", "subject", "keywords", "title")
    )
    salida: list[str] = []
    for texto in (fuentes, portada):
        for m in _DOI.finditer(texto):
            doi = normalizar_doi(m.group(1).rstrip(".,;:)]}'"))
            if doi and doi not in salida:
                salida.append(doi)
    m = _ARXIV.search(portada)
    if m:
        doi = f"10.48550/arxiv.{normalizar_arxiv(m.group(1))}"
        if doi not in salida:
            salida.append(doi)
    return salida


def resolver_doi(doi: str, cfg: Config, timeout: float = 25.0) -> dict | None:
    """Metadatos crudos (CSL-JSON) del DOI, o None si no resuelve.

    doi.org con negociación de contenido cubre Crossref, DataCite (arXiv) y
    las demás agencias de registro. La API de Crossref es el respaldo.
    """
    ua = (
        f"PHDjournal/1.0 (mailto:{cfg.email_contacto})"
        if cfg.email_contacto else "PHDjournal/1.0"
    )
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": ua}) as cli:
        try:
            r = cli.get(
                f"https://doi.org/{doi}",
                headers={"Accept": "application/vnd.citationstyles.csl+json"},
            )
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
        except Exception as exc:
            log.info("doi.org no resolvió %s: %s", doi, exc)
        try:
            r = cli.get(f"https://api.crossref.org/works/{doi}")
            if r.status_code == 200:
                return r.json().get("message")
        except Exception as exc:
            log.info("Crossref no resolvió %s: %s", doi, exc)
    return None


def _primero(valor) -> str:
    if isinstance(valor, list):
        valor = valor[0] if valor else ""
    return _ETIQUETAS.sub("", str(valor or "")).strip()


def _limpiar_abstract(crudo: str) -> str:
    """Crossref manda el abstract en JATS, con su propio encabezado 'Abstract'."""
    texto = re.sub(r"\s+", " ", _ETIQUETAS.sub(" ", crudo)).strip()
    return re.sub(r"^(abstract|summary|resumen)\s*[:.]?\s+", "", texto, flags=re.IGNORECASE)


def titulo_coincide(titulo: str, portada: str) -> bool:
    """¿El título aparece en la portada? Tolerante a cortes de línea y guiones.

    Se compara por palabras, no por subcadena: el texto del PDF parte el
    título en varias líneas y a veces separa sílabas con guion.
    """
    palabras = [p for p in normalizar_texto(titulo).split() if len(p) > 2]
    if len(palabras) < 2:
        return False
    texto = normalizar_texto(portada.replace("-\n", ""))
    presentes = set(texto.split())
    return sum(p in presentes for p in palabras) / len(palabras) >= 0.8


def metadatos_desde_csl(csl: dict, doi: str) -> dict:
    """Convierte CSL-JSON (o un registro de Crossref) en columnas de la base."""
    autores = []
    for a in csl.get("author") or []:
        nombre = " ".join(x for x in (a.get("given"), a.get("family")) if x)
        nombre = nombre or a.get("literal") or a.get("name") or ""
        if nombre:
            autores.append(nombre.strip())

    partes = ((csl.get("issued") or csl.get("published") or {}).get("date-parts") or [[]])[0]
    partes = [p for p in partes if p]
    anio = int(partes[0]) if partes and str(partes[0]).isdigit() else None
    fecha = "-".join(
        f"{int(p):02d}" if i else str(p) for i, p in enumerate(partes[:3])
    ) if partes else ""

    tipo = _TIPOS.get(csl.get("type", ""), "otro")
    doi = normalizar_doi(csl.get("DOI") or doi)
    arxiv = ""
    if doi.startswith("10.48550/arxiv."):
        tipo = "preprint"
        arxiv = normalizar_arxiv(doi.split("arxiv.", 1)[1])

    venue = _primero(csl.get("container-title"))
    if not venue and tipo == "preprint":
        venue = csl.get("publisher") or "arXiv"

    extra = {
        "volume": csl.get("volume"),
        "issue": csl.get("issue"),
        "pages": csl.get("page") or csl.get("article-number"),
        "ISSN": _primero(csl.get("ISSN")),
        "ISBN": _primero(csl.get("ISBN")),
        "publisher": csl.get("publisher"),
        "language": csl.get("language"),
        "journalAbbreviation": _primero(csl.get("container-title-short")),
        "conferenceName": _primero(csl.get("event") if isinstance(csl.get("event"), str)
                                   else (csl.get("event") or {}).get("name")),
        "university": csl.get("publisher") if tipo == "thesis" else None,
        "institution": csl.get("publisher") if tipo == "report" else None,
    }

    return {
        "titulo": _primero(csl.get("title")),
        "autores": autores,
        "anio": anio,
        "fecha_pub": fecha,
        "venue": venue,
        "tipo_venue": tipo,
        "doi": doi,
        "arxiv_id": arxiv,
        "url": f"https://doi.org/{doi}",
        "resumen_origen": _limpiar_abstract(csl.get("abstract") or ""),
        "extra": {k: str(v) for k, v in extra.items() if v},
    }


def verificar_doi(doi: str, portada: str, cfg: Config) -> tuple[dict | None, str]:
    """Resuelve y comprueba contra la portada. Devuelve (metadatos o None, motivo)."""
    csl = resolver_doi(doi, cfg)
    if not csl:
        return None, f"el DOI {doi} no resolvió"
    meta = metadatos_desde_csl(csl, doi)
    if not meta["titulo"]:
        return None, f"el DOI {doi} no trae título"
    if not titulo_coincide(meta["titulo"], portada):
        return None, (
            f"el DOI {doi} es de «{meta['titulo'][:80]}», que no aparece en la "
            "portada (probablemente es una referencia citada)"
        )
    return meta, "verificado"


def _titulos_iguales(a: str, b: str) -> bool:
    """Mismo título, salvo puntuación y mayúsculas. Exigente a propósito."""
    pa, pb = normalizar_texto(a).split(), normalizar_texto(b).split()
    if not pa or not pb:
        return False
    if pa == pb:
        return True
    comunes = len(set(pa) & set(pb))
    return comunes / len(set(pa)) >= 0.9 and comunes / len(set(pb)) >= 0.9


def buscar_version_arxiv(titulo: str, portada: str, cfg: Config) -> dict | None:
    """Para documentos sin DOI propio (actas de ICML, NeurIPS...): su versión en arXiv.

    Se busca por título exacto en arXiv. Si la entrada trae el DOI de la
    versión publicada, se prueba primero ese; si no, el DOI de arXiv. En los
    dos casos el DOI pasa por la misma verificación contra la portada, así que
    un título parecido de otro trabajo no se cuela. Lo que se use queda
    marcado (``extra["_via"]``) porque puede ser otra versión del trabajo.
    """
    from .sources import arxiv as fuente_arxiv
    import xml.etree.ElementTree as ET

    palabras = normalizar_texto(titulo).split()
    if len(palabras) < 4:
        return None
    try:
        r = httpx.get(
            fuente_arxiv.BASE,
            params={"search_query": f'ti:"{" ".join(palabras[:25])}"', "max_results": "5"},
            headers={"User-Agent": "PHDjournal/1.0"},
            timeout=30.0,
            follow_redirects=True,
        )
        r.raise_for_status()
        raiz = ET.fromstring(r.content)
    except Exception as exc:
        log.info("arXiv no respondió a la búsqueda por título: %s", exc)
        return None

    for entrada in raiz.findall("atom:entry", fuente_arxiv.NS):
        paper = fuente_arxiv._parsear_entrada(entrada)
        if paper is None or not _titulos_iguales(paper.titulo, titulo):
            continue
        dois = [d for d in (paper.doi, f"10.48550/arxiv.{paper.arxiv_id}") if d]
        for doi in dois:
            meta, motivo = verificar_doi(doi, portada, cfg)
            if meta:
                meta["extra"]["_via"] = "arxiv-titulo"
                log.info("Versión de arXiv encontrada por título: %s", doi)
                return meta
            log.info("DOI de la versión de arXiv descartado: %s", motivo)
    return None


def _primer_doi_valido(candidatos: list[str], portada: str, cfg: Config) -> dict | None:
    for doi in candidatos[:6]:
        meta, motivo = verificar_doi(doi, portada, cfg)
        if meta:
            log.info("DOI %s verificado", doi)
            return meta
        log.info("DOI candidato descartado: %s", motivo)
    return None


# ---------------------------------------------------------------------------
# Metadatos de respaldo
# ---------------------------------------------------------------------------

def _metadatos_pdf(ext: Extraido, ruta: Path) -> dict:
    titulo = (ext.meta_pdf.get("title") or "").strip()
    basura = ("microsoft word", "untitled", ".doc", ".pdf", "latex")
    if len(titulo) < 12 or any(b in titulo.lower() for b in basura):
        titulo = ruta.stem
    autores = [
        a.strip() for a in re.split(r";| and |,", ext.meta_pdf.get("author") or "")
        if a.strip()
    ]
    return {
        "titulo": titulo, "autores": autores, "anio": None, "fecha_pub": "",
        "venue": "", "tipo_venue": "otro", "doi": "", "arxiv_id": "", "url": "",
        "resumen_origen": "", "extra": {},
    }


def _metadatos_ia(m: dict, base: dict) -> dict:
    """Los metadatos que Claude leyó en la portada, sobre los de respaldo."""
    anio = m.get("anio") or ""
    salida = dict(base)
    salida.update({
        "titulo": m.get("titulo") or base["titulo"],
        "autores": m.get("autores") or base["autores"],
        "anio": int(anio[:4]) if anio[:4].isdigit() else base["anio"],
        "fecha_pub": anio[:4] if anio[:4].isdigit() else base["fecha_pub"],
        "venue": m.get("venue") or base["venue"],
        "tipo_venue": m.get("tipo") or base["tipo_venue"],
        "resumen_origen": base["resumen_origen"] or m.get("abstract") or "",
    })
    return salida


def _abstract_heuristico(texto: str) -> str:
    for titulo, cuerpo in pdf_mod.partir_en_secciones(texto[:30000]):
        if titulo.lower() == "abstract":
            return cuerpo[:3000].strip()
    return ""


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------

def _temas(meta: dict, texto: str) -> dict:
    base = meta["resumen_origen"] or texto[:3000]
    return ranking.detectar_temas(meta["titulo"], base)


def _copiar(ruta: Path, meta: dict, verificado: bool, sha: str, cfg: Config) -> Path:
    if verificado:
        p = Paper(titulo=meta["titulo"], autores=meta["autores"], anio=meta["anio"])
        nombre = pdf_mod.nombre_archivo(p)
    else:
        nombre = ruta.name
    destino = dir_locales(cfg) / nombre
    if destino.exists() and sha256_de(destino) != sha:
        destino = destino.with_name(f"{destino.stem} ({sha[:6]}).pdf")
    if not destino.exists():
        shutil.copy2(ruta, destino)
    return destino


def _a_columnas(meta: dict) -> dict:
    return {
        "titulo": meta["titulo"],
        "autores": json.dumps(meta["autores"], ensure_ascii=False),
        "resumen_origen": meta["resumen_origen"],
        "anio": meta["anio"],
        "fecha_pub": meta["fecha_pub"],
        "venue": meta["venue"],
        "tipo_venue": meta["tipo_venue"],
        "doi": meta["doi"],
        "arxiv_id": meta["arxiv_id"],
        "url": meta["url"],
        "extra": json.dumps(meta["extra"], ensure_ascii=False),
    }


def importar(
    ruta: Path, cfg: Config, resumir: bool = True, progreso: Progreso | None = None
) -> Resultado:
    """Importa un PDF: metadatos, copia, etiquetas de tema y resumen."""
    progreso = progreso or (lambda _m: None)
    ruta = Path(ruta)
    db.inicializar()

    sha = sha256_de(ruta)
    with db.conexion() as con:
        previo = db.documento_por_hash(con, sha)
    if previo:
        return Resultado(ruta, "duplicado", f"ya estaba importado como «{previo['titulo'][:70]}»",
                         previo["id"])

    progreso(f"Leyendo {ruta.name}...")
    try:
        ext = extraer(ruta)
    except Exception as exc:
        return Resultado(ruta, "error", f"no se pudo abrir el PDF: {exc}")
    if len(ext.texto.strip()) < MIN_CHARS_TEXTO:
        return Resultado(
            ruta, "sin_texto",
            "sin texto extraíble; parece un escaneo (el OCR no está soportado)",
        )

    progreso(f"Buscando el DOI de {ruta.name}...")
    meta = _primer_doi_valido(candidatos_doi(ext.portada, ext.meta_pdf), ext.portada, cfg)
    if meta is None:
        respaldo = _metadatos_pdf(ext, ruta)
        if respaldo["titulo"] != ruta.stem:
            progreso(f"Sin DOI en la portada; buscando {ruta.name} en arXiv...")
            meta = buscar_version_arxiv(respaldo["titulo"], ext.portada, cfg)
    verificado = meta is not None
    if not verificado:
        meta = _metadatos_pdf(ext, ruta)
    if not meta["resumen_origen"]:
        meta["resumen_origen"] = _abstract_heuristico(ext.texto)

    if meta["doi"]:
        with db.conexion() as con:
            mismo = con.execute(
                "SELECT titulo FROM documentos WHERE doi = ?", (meta["doi"],)
            ).fetchone()
        if mismo:
            return Resultado(
                ruta, "duplicado",
                f"ya hay un documento con el DOI {meta['doi']} («{mismo['titulo'][:60]}»)",
            )

    temas = _temas(meta, ext.texto)
    destino = _copiar(ruta, meta, verificado, sha, cfg)
    doc_id = "local:" + sha[:20]

    with db.conexion() as con:
        db.guardar_documento(con, {
            "id": doc_id,
            "sha256": sha,
            "nombre_original": ruta.name,
            "ruta_original": str(ruta.resolve()),
            "ruta_pdf": str(destino),
            **_a_columnas(meta),
            "metadatos_origen": "doi" if verificado else "pdf",
            "n_paginas": ext.n_paginas,
            "desglose": json.dumps(temas, ensure_ascii=False),
            "trabajo": temas.get("trabajo"),
            "importado_en": db.ahora(),
        })

    res = Resultado(ruta, "nuevo", "importado", doc_id, verificado)
    if resumir and cfg.tiene_clave():
        progreso(f"Resumiendo {ruta.name} con {cfg.modelo_claude}...")
        try:
            resumir_documento(doc_id, cfg, texto=ext.texto)
            res.resumido = True
        except Exception as exc:
            log.warning("No se pudo resumir %s: %s", ruta.name, exc)
            res.mensaje = f"importado, pero el resumen falló: {exc}"

    with db.conexion() as con:
        res.verificado = db.leer_documento(con, doc_id)["metadatos_origen"] == "doi"
    if not res.verificado and res.mensaje == "importado":
        res.mensaje = "importado sin DOI verificado; indícalo a mano en la ficha"
    return res


def resumir_documento(doc_id: str, cfg: Config, texto: str | None = None) -> dict:
    """(Re)genera el resumen. Si los metadatos no estaban verificados, los mejora."""
    with db.conexion() as con:
        fila = db.leer_documento(con, doc_id)
    if fila is None:
        raise ErrorDocumento("El documento ya no existe.")
    if texto is None:
        texto = extraer(Path(fila["ruta_pdf"])).texto

    verificado = fila["metadatos_origen"] == "doi"
    conocidos = None
    if verificado:
        conocidos = {
            "título": fila["titulo"],
            "autores": ", ".join(json.loads(fila["autores"] or "[]")[:8]),
            "año": fila["anio"], "venue": fila["venue"], "DOI": fila["doi"],
        }
    desglose = json.loads(fila["desglose"] or "{}")
    resumen, t_in, t_out = summarize.resumir_documento(
        texto, cfg, conocidos, desglose.get("nombres_dominios"), fila["trabajo"],
    )

    with db.conexion() as con:
        db.guardar_resumen_documento(
            con, doc_id, cfg.idioma_resumen, cfg.modelo_claude, resumen, t_in, t_out
        )

    if not verificado:
        _mejorar_con_ia(fila, resumen.get("metadatos") or {}, texto, cfg)
    return resumen


def _mejorar_con_ia(fila, m: dict, texto: str, cfg: Config) -> None:
    """Sin DOI verificado: probar el DOI que leyó Claude, o usar su lectura."""
    portada = "\n".join(texto.split("\n")[:400])
    if m.get("doi"):
        meta, motivo = verificar_doi(normalizar_doi(m["doi"]), portada, cfg)
        if meta:
            _aplicar_metadatos(fila["id"], meta, "doi", texto)
            return
        log.info("El DOI que leyó Claude no sirvió: %s", motivo)

    # Sin DOI propio: la versión de arXiv, buscada con el título que leyó
    # Claude, que es más fiable que el de las propiedades del PDF.
    titulo = m.get("titulo") or fila["titulo"]
    meta = buscar_version_arxiv(titulo, portada, cfg)
    if meta:
        _aplicar_metadatos(fila["id"], meta, "doi", texto)
        return

    base = {
        "titulo": fila["titulo"], "autores": json.loads(fila["autores"] or "[]"),
        "anio": fila["anio"], "fecha_pub": fila["fecha_pub"] or "",
        "venue": fila["venue"] or "", "tipo_venue": fila["tipo_venue"] or "otro",
        "doi": "", "arxiv_id": "", "url": "",
        "resumen_origen": fila["resumen_origen"] or "", "extra": {},
    }
    _aplicar_metadatos(fila["id"], _metadatos_ia(m, base), "ia", texto)


def _aplicar_metadatos(doc_id: str, meta: dict, origen: str, texto: str) -> None:
    temas = _temas(meta, texto)
    with db.conexion() as con:
        db.actualizar_documento(
            con, doc_id, **_a_columnas(meta), metadatos_origen=origen,
            desglose=json.dumps(temas, ensure_ascii=False), trabajo=temas.get("trabajo"),
        )


def completar_por_doi(
    doc_id: str, doi: str, cfg: Config, forzar: bool = False
) -> tuple[bool, str]:
    """El DOI que escribió el usuario. Verifica contra la portada salvo ``forzar``.

    Devuelve (aplicado, mensaje). Si no coincide y no se fuerza, no toca nada
    y el mensaje explica por qué, para que la interfaz pregunte.
    """
    doi = normalizar_doi(doi)
    if not _DOI.fullmatch(doi):
        return False, f"«{doi}» no tiene forma de DOI (10.xxxx/...)."
    with db.conexion() as con:
        fila = db.leer_documento(con, doc_id)
    ext = extraer(Path(fila["ruta_pdf"]))

    meta, motivo = verificar_doi(doi, ext.portada, cfg)
    if meta is None and forzar:
        csl = resolver_doi(doi, cfg)
        if csl:
            meta = metadatos_desde_csl(csl, doi)
    if meta is None:
        return False, motivo
    if not meta["resumen_origen"]:
        meta["resumen_origen"] = fila["resumen_origen"] or ""
    _aplicar_metadatos(doc_id, meta, "doi", ext.texto)
    return True, f"Metadatos completados desde el DOI {doi}."


# ---------------------------------------------------------------------------
# Hacia el resto de la app
# ---------------------------------------------------------------------------

def paper_de_documento(fila) -> Paper:
    extra = json.loads(fila["extra"] or "{}")
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
        crudo={"zotero": extra},
    )


def item_zotero(fila, cfg: Config) -> dict:
    from . import zotero

    resumen = json.loads(fila["resumen_json"]) if fila["resumen_json"] else None
    etiquetas = ["origen:local"]
    if fila["metadatos_origen"] != "doi":
        etiquetas.append("metadatos-sin-verificar")
    elif json.loads(fila["extra"] or "{}").get("_via") == "arxiv-titulo":
        etiquetas.append("metadatos-version-arxiv")
    return zotero.construir_item(
        paper_de_documento(fila), resumen,
        fila["resumen_modelo"] or cfg.modelo_claude, fila["trabajo"],
        pdf_local=Path(fila["ruta_pdf"]),
        base_resumen="el texto completo del PDF",
        etiquetas_extra=etiquetas,
    )
