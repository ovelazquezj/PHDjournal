"""Integración con Zotero.

Contexto de diseño, porque condiciona todo lo que hay aquí:

1. Con una biblioteca **local, sin cuenta de sincronización**, la API web de
   zotero.org no sirve: sería la única vía capaz de escribir con Zotero
   cerrado, pero exige sincronización.
2. La única vía que escribe directo es el **servidor local del conector**, en
   127.0.0.1:23119, el mismo que usa el botón del navegador. Ese servidor solo
   existe mientras Zotero corre. De ahí que la app lo lance por su cuenta.
3. ``saveItems`` guarda en la colección seleccionada, pero ``updateSession``
   permite moverla al destino que uno quiera. Se usan los dos en secuencia, así
   que **no importa qué tenga seleccionado el usuario**.
4. Declarar un adjunto en ``saveItems`` no hace que Zotero lo descargue. Hay
   que bajar el archivo y subirlo por ``saveAttachment``, con el **id de
   sesión** del ítem padre en los metadatos. Con la clave de Zotero responde
   500; con el id de sesión, 201.
5. El conector **no tiene endpoint para crear colecciones**. La subcolección
   destino se crea una vez a mano.

Todo verificado empíricamente contra Zotero 7 el 15 de septiembre de 2026; la
documentación pública del protocolo del conector es escasa.

Red de seguridad: todo ítem lleva la etiqueta ``PHDjournal`` y la del trabajo
propio con el que encaje. Aunque algo caiga en la colección equivocada, se
encuentra por etiqueta.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx2 as httpx  # anthropic 1.x trae httpx2; no mezclar con httpx

from .config import Config
from .sources.base import Paper

log = logging.getLogger(__name__)

CABECERAS = {
    "Content-Type": "application/json",
    "X-Zotero-Connector-API-Version": "3",
    "User-Agent": "PHDjournal/1.0",
}

TIPO_ITEM = {
    "journal": "journalArticle",
    "conference": "conferencePaper",
    "preprint": "preprint",
    "book": "bookSection",
    "thesis": "thesis",
    "report": "report",
    "otro": "journalArticle",
}

# Campos bibliográficos que cada tipo de Zotero admite, de los que trae un
# DOI resuelto. Mandar un campo que el tipo no tiene hace que Zotero lo
# descarte en silencio o rechace el ítem, según la versión; mejor filtrar.
CAMPOS_POR_TIPO = {
    "journalArticle": {"volume", "issue", "pages", "ISSN", "journalAbbreviation", "language"},
    "conferencePaper": {"volume", "pages", "publisher", "place", "conferenceName", "ISBN", "language"},
    "preprint": {"publisher", "number", "language"},
    "bookSection": {"volume", "pages", "publisher", "place", "ISBN", "language"},
    "thesis": {"university", "place", "thesisType", "numPages", "language"},
    "report": {"institution", "place", "reportNumber", "pages", "language"},
}


class ErrorZotero(RuntimeError):
    pass


class ZoteroCerrado(ErrorZotero):
    """Zotero no responde y no se pudo (o no se quiso) abrir."""


class SubcoleccionFaltante(ErrorZotero):
    """La subcolección destino no existe todavía en la biblioteca."""

    def __init__(self, padre: str, hijo: str) -> None:
        self.padre = padre
        self.hijo = hijo
        if padre:
            msg = (
                f"Falta la subcolección '{hijo}' dentro de '{padre}'. "
                f"En Zotero: clic derecho sobre '{padre}', Nueva subcolección, "
                f"y escribe '{hijo}'."
            )
        else:
            msg = (
                f"Falta la colección '{hijo}' en tu biblioteca. "
                f"En Zotero: clic derecho sobre la biblioteca, Nueva colección, "
                f"y escribe '{hijo}'."
            )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------

def puerto_abierto(puerto: int = 23119, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=timeout):
            return True
    except OSError:
        return False


def ping(puerto: int = 23119, timeout: float = 3.0) -> bool:
    if not puerto_abierto(puerto, timeout=1.0):
        return False
    try:
        r = httpx.post(
            f"http://127.0.0.1:{puerto}/connector/ping",
            json={},
            headers=CABECERAS,
            timeout=timeout,
        )
        return r.status_code == 200
    except Exception:
        return False


def lanzar(cfg: Config, espera_max: float = 40.0) -> bool:
    """Abre Zotero minimizado y espera a que el conector responda."""
    exe = Path(cfg.zotero_exe)
    if not exe.exists():
        raise ErrorZotero(f"No se encontró el ejecutable de Zotero en {exe}")

    log.info("Lanzando Zotero minimizado desde %s", exe)
    inicio = None
    if os.name == "nt":
        inicio = subprocess.STARTUPINFO()
        inicio.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        inicio.wShowWindow = 7  # SW_SHOWMINNOACTIVE: minimizado y sin robar foco

    subprocess.Popen(
        [str(exe)],
        startupinfo=inicio,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )

    limite = time.monotonic() + espera_max
    while time.monotonic() < limite:
        if ping(cfg.zotero_puerto, timeout=2.0):
            log.info("Zotero respondió al conector")
            return True
        time.sleep(1.5)
    return False


def asegurar_disponible(cfg: Config) -> bool:
    if ping(cfg.zotero_puerto):
        return True
    if not cfg.zotero_auto_lanzar:
        raise ZoteroCerrado(
            "Zotero está cerrado y el arranque automático está desactivado."
        )
    if lanzar(cfg):
        return True
    raise ZoteroCerrado(
        "Zotero se lanzó pero el conector no respondió a tiempo. "
        "Puede estar pidiendo actualizar o esperando en un diálogo."
    )


# ---------------------------------------------------------------------------
# Colección seleccionada
# ---------------------------------------------------------------------------

def coleccion_seleccionada(cfg: Config) -> dict:
    """Lee la selección actual y, de paso, el árbol completo de colecciones.

    La respuesta trae un campo ``targets`` con toda la jerarquía y un id por
    colección (``C10``, ``C53``...). Ese id es lo que permite dirigir el
    guardado sin depender de lo que el usuario tenga seleccionado.
    """
    try:
        r = httpx.post(
            f"http://127.0.0.1:{cfg.zotero_puerto}/connector/getSelectedCollection",
            json={},
            headers=CABECERAS,
            timeout=8.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        raise ErrorZotero(f"No se pudo leer la colección seleccionada: {exc}") from exc


def resolver_target(cfg: Config) -> tuple[str | None, str]:
    """Busca el id de destino de ``padre > hijo`` en el árbol del conector.

    Devuelve (id o None, explicación). El árbol viene plano con un campo
    ``level`` que marca la profundidad, así que se reconstruye la ascendencia
    con una pila.
    """
    datos = coleccion_seleccionada(cfg)
    objetivos = datos.get("targets") or []
    if not objetivos:
        return None, "el conector no devolvió el árbol de colecciones"

    padre_buscado = cfg.zotero_coleccion_padre.strip().lower()
    hijo_buscado = cfg.zotero_subcoleccion.strip().lower()

    ascendencia: dict[int, str] = {}
    for entrada in objetivos:
        nivel = int(entrada.get("level") or 0)
        nombre = (entrada.get("name") or "").strip()
        ascendencia[nivel] = nombre.lower()
        # Limpiar niveles más profundos que ya no aplican.
        for mas_hondo in [k for k in ascendencia if k > nivel]:
            del ascendencia[mas_hondo]

        if nombre.lower() != hijo_buscado:
            continue
        # Sin padre configurado, vale cualquier coleccion de primer nivel:
        # el nivel 0 es la biblioteca, no una coleccion.
        if not padre_buscado:
            if nivel == 1:
                return str(entrada.get("id")), f"{nombre} (id {entrada.get('id')})"
            continue
        if ascendencia.get(nivel - 1) == padre_buscado:
            return str(entrada.get("id")), (
                f"{cfg.zotero_coleccion_padre} > {nombre} (id {entrada.get('id')})"
            )

    donde = (
        f"dentro de '{cfg.zotero_coleccion_padre}'"
        if cfg.zotero_coleccion_padre else "en la raiz de tu biblioteca"
    )
    return None, f"no existe '{cfg.zotero_subcoleccion}' {donde}"


def _ruta_datos(cfg: Config) -> Path:
    if cfg.zotero_datos:
        return Path(cfg.zotero_datos)
    return Path.home() / "Zotero"


def _abrir_base_zotero(db: Path) -> sqlite3.Connection:
    """Abre zotero.sqlite para lectura, aunque Zotero la tenga bloqueada.

    Zotero mantiene un bloqueo exclusivo sobre su base mientras corre, así que
    abrirla en solo lectura falla con "database is locked". La salida es
    trabajar sobre una copia: los nombres de las colecciones cambian poco y
    una copia de hace un segundo sirve perfectamente para saber si existe una.
    """
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2.0)
        con.execute("SELECT 1 FROM collections LIMIT 1").fetchone()
        return con
    except sqlite3.Error:
        pass

    tmp = Path(tempfile.gettempdir()) / "phdjournal_zotero_lectura"
    tmp.mkdir(parents=True, exist_ok=True)
    copia = tmp / "zotero.sqlite"
    shutil.copy2(db, copia)
    # El WAL guarda lo que aún no se ha consolidado; sin él la copia puede
    # quedarse sin las colecciones creadas hace un momento.
    for sufijo in ("-wal", "-shm"):
        origen = db.with_name(db.name + sufijo)
        if origen.exists():
            try:
                shutil.copy2(origen, copia.with_name(copia.name + sufijo))
            except OSError:
                pass
    return sqlite3.connect(copia, timeout=5.0)


def verificar_subcoleccion(cfg: Config) -> tuple[bool, str]:
    """Comprueba que exista ``padre > hijo`` en la biblioteca de Zotero."""
    db = _ruta_datos(cfg) / "zotero.sqlite"
    if not db.exists():
        return False, f"No se encontró la base de Zotero en {db}"

    try:
        con = _abrir_base_zotero(db)
    except (sqlite3.Error, OSError) as exc:
        return False, f"No se pudo leer la base de Zotero: {exc}"

    try:
        fila = con.execute(
            """SELECT h.collectionID
                 FROM collections h
                 JOIN collections p ON p.collectionID = h.parentCollectionID
                WHERE h.collectionName = ? AND p.collectionName = ?""",
            (cfg.zotero_subcoleccion, cfg.zotero_coleccion_padre),
        ).fetchone()
        if fila:
            return True, str(fila[0])

        padre = con.execute(
            "SELECT collectionID FROM collections WHERE collectionName = ?",
            (cfg.zotero_coleccion_padre,),
        ).fetchone()
        if not padre:
            return False, (
                f"No existe la colección '{cfg.zotero_coleccion_padre}' en tu biblioteca."
            )
        return False, (
            f"Falta la subcolección '{cfg.zotero_subcoleccion}' dentro de "
            f"'{cfg.zotero_coleccion_padre}'. En Zotero: clic derecho sobre "
            f"'{cfg.zotero_coleccion_padre}', Nueva subcolección, y escribe "
            f"'{cfg.zotero_subcoleccion}'."
        )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Construcción del ítem
# ---------------------------------------------------------------------------

def _creadores(autores: list[str]) -> list[dict]:
    salida = []
    for nombre in autores[:40]:
        nombre = (nombre or "").strip()
        if not nombre:
            continue
        partes = nombre.rsplit(" ", 1)
        if len(partes) == 2:
            salida.append(
                {"firstName": partes[0], "lastName": partes[1], "creatorType": "author"}
            )
        else:
            salida.append(
                {"lastName": nombre, "fieldMode": 1, "creatorType": "author"}
            )
    return salida


def _nota_resumen(
    resumen: dict,
    modelo: str,
    puntaje: dict | None,
    base: str = "el abstract del trabajo",
) -> str:
    """La nota deja constancia explícita de que el resumen lo generó una IA."""
    def esc(t: str) -> str:
        return (
            (t or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    bloques = [
        "<h2>Resumen de lectura, PHDjournal</h2>",
        f"<p><b>Qué hace:</b> {esc(resumen.get('que_hace', ''))}</p>",
        f"<p><b>Método:</b> {esc(resumen.get('metodo', ''))}</p>",
        f"<p><b>Hallazgo:</b> {esc(resumen.get('hallazgo', ''))}</p>",
        f"<p><b>Por qué importa:</b> {esc(resumen.get('por_que_te_importa', ''))}</p>",
        f"<p><b>Limitaciones:</b> {esc(resumen.get('limitaciones', ''))}</p>",
        f"<p><b>Veredicto:</b> {esc(resumen.get('veredicto', ''))}</p>",
    ]
    if puntaje:
        bloques.append(
            "<p><b>Puntaje del ranking:</b> "
            f"total {puntaje.get('total', 0):.3f}, "
            f"relevancia {puntaje.get('relevancia', 0):.2f}, "
            f"venue {puntaje.get('venue', 0):.2f}, "
            f"citas {puntaje.get('citas', 0):.2f}, "
            f"novedad {puntaje.get('novedad', 0):.2f}</p>"
        )
    bloques.append(
        "<hr><p><i>Aviso de procedencia: este resumen fue generado por "
        f"inteligencia artificial ({esc(modelo)}) a partir de {esc(base)}, "
        "no por el autor de la tesis. No citar este texto; verificar "
        "contra el original antes de usarlo en el manuscrito.</i></p>"
    )
    return "".join(bloques)


def construir_item(
    paper: Paper,
    resumen: dict | None,
    modelo: str,
    trabajo: str | None,
    puntaje: dict | None = None,
    adjuntar_pdf: bool = True,
    pdf_local: Path | None = None,
    base_resumen: str = "el abstract del trabajo",
    etiquetas_extra: list[str] | None = None,
) -> dict:
    """Arma el ítem para el conector.

    Con ``pdf_local`` el adjunto se sube desde el disco en lugar de bajarse de
    internet: es el caso de los documentos locales. Los campos bibliográficos
    finos (volumen, número, páginas, ISSN...) vienen en
    ``paper.crudo["zotero"]`` cuando el DOI se resolvió.
    """
    tipo = TIPO_ITEM.get(paper.tipo_venue, "journalArticle")

    item: dict = {
        # El id es de la sesión, no de Zotero. Es la referencia que usa
        # saveAttachment para saber a qué ítem colgar el PDF.
        "id": f"phdj-{abs(hash(paper.id)) % 10**12}",
        "itemType": tipo,
        "title": paper.titulo,
        "creators": _creadores(paper.autores),
        "date": paper.fecha_pub or (str(paper.anio) if paper.anio else ""),
        "abstractNote": paper.resumen,
        "url": paper.url or (f"https://doi.org/{paper.doi}" if paper.doi else ""),
        "accessDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "libraryCatalog": "PHDjournal",
        "tags": [{"tag": "PHDjournal"}],
        "attachments": [],
        "notes": [],
    }

    if paper.doi:
        item["DOI"] = paper.doi
    if tipo == "journalArticle":
        item["publicationTitle"] = paper.venue or ""
    elif tipo == "conferencePaper":
        item["proceedingsTitle"] = paper.venue or ""
    elif tipo == "preprint":
        item["repository"] = paper.venue or "arXiv"
        if paper.arxiv_id:
            item["archiveID"] = f"arXiv:{paper.arxiv_id}"
    elif tipo == "bookSection":
        item["bookTitle"] = paper.venue or ""

    permitidos = CAMPOS_POR_TIPO.get(tipo, set())
    for campo, valor in (paper.crudo.get("zotero") or {}).items():
        if campo in permitidos and valor:
            item[campo] = str(valor)

    for etiqueta in etiquetas_extra or []:
        item["tags"].append({"tag": etiqueta})

    if trabajo:
        item["tags"].append({"tag": trabajo})
    for fuente in sorted(paper.fuentes):
        item["tags"].append({"tag": f"fuente:{fuente}"})
    if resumen:
        item["tags"].append({"tag": f"veredicto:{resumen.get('veredicto', 'sin veredicto')}"})
        item["tags"].append({"tag": "resumen-IA"})
        item["notes"].append(
            {"note": _nota_resumen(resumen, modelo, puntaje, base_resumen)}
        )

    if adjuntar_pdf and pdf_local is not None:
        item["attachments"].append(
            {
                "id": f"{item['id']}-pdf",
                "title": "PDF",
                "ruta_local": str(pdf_local),
                "url": item["url"] or Path(pdf_local).as_uri(),
                "mimeType": "application/pdf",
            }
        )
    elif adjuntar_pdf and paper.url_pdf:
        item["attachments"].append(
            {
                "id": f"{item['id']}-pdf",
                "title": "PDF de acceso abierto",
                "url": paper.url_pdf,
                "mimeType": "application/pdf",
            }
        )

    return item


def _subir_adjunto(cfg: Config, sesion: str, item: dict, adjunto: dict) -> bool:
    """Descarga el PDF y lo sube a Zotero como archivo, no como enlace.

    Declarar el adjunto en ``saveItems`` no basta: Zotero no lo descarga solo.
    El conector del navegador baja el archivo él mismo y lo sube por
    ``saveAttachment``, con el id de sesión del ítem padre en los metadatos.
    Con la clave de Zotero en ``parentItemID`` responde 500; con el id de
    sesión, 201.
    """
    url = adjunto.get("url") or ""
    ruta_local = adjunto.get("ruta_local") or ""
    if ruta_local:
        try:
            contenido = Path(ruta_local).read_bytes()
        except OSError as exc:
            log.info("No se pudo leer el PDF local %s: %s", ruta_local, exc)
            return False
        return _enviar_adjunto(cfg, sesion, item, adjunto, contenido, url)
    if not url:
        return False

    try:
        with httpx.Client(
            timeout=120.0, follow_redirects=True,
            headers={"User-Agent": "PHDjournal/1.0 (lector personal de papers)"},
        ) as cli:
            r = cli.get(url)
            r.raise_for_status()
            contenido = r.content
    except Exception as exc:
        log.info("No se pudo descargar el PDF de %s: %s", url, exc)
        return False

    if not contenido.startswith(b"%PDF"):
        # Muro de pago o página de aterrizaje disfrazada de PDF.
        log.info("Lo descargado de %s no es un PDF; no se adjunta", url)
        return False
    return _enviar_adjunto(cfg, sesion, item, adjunto, contenido, url)


def _enviar_adjunto(
    cfg: Config, sesion: str, item: dict, adjunto: dict, contenido: bytes, url: str
) -> bool:
    """Sube los bytes de un PDF por ``saveAttachment``, colgado del ítem padre."""
    if not contenido.startswith(b"%PDF"):
        log.info("El adjunto no es un PDF; no se sube")
        return False

    metadatos = {
        "sessionID": sesion,
        "id": adjunto.get("id") or f"{item['id']}-pdf",
        "url": url,
        "contentType": adjunto.get("mimeType", "application/pdf"),
        "title": adjunto.get("title", "PDF"),
        "parentItemID": item["id"],
    }
    cabeceras = {
        "Content-Type": "application/pdf",
        "X-Metadata": json.dumps(metadatos),
        "X-Zotero-Connector-API-Version": "3",
        "User-Agent": "PHDjournal/1.0",
    }
    try:
        r = httpx.post(
            f"http://127.0.0.1:{cfg.zotero_puerto}/connector/saveAttachment",
            content=contenido,
            headers=cabeceras,
            timeout=180.0,
        )
    except Exception as exc:
        log.info("Falló la subida del PDF a Zotero: %s", exc)
        return False

    if r.status_code in (200, 201):
        log.info("PDF adjuntado (%.0f KB)", len(contenido) / 1024)
        return True
    log.info("Zotero rechazó el adjunto: %s %s", r.status_code, r.text[:200])
    return False


# ---------------------------------------------------------------------------
# Guardado
# ---------------------------------------------------------------------------

def guardar_items(cfg: Config, items: list[dict], dirigir: bool = True) -> dict:
    """Manda los ítems al Zotero abierto, dirigidos a la subcolección destino.

    El guardado va en dos pasos, que es como funciona el conector del
    navegador: ``saveItems`` crea la sesión y guarda, y ``updateSession`` mueve
    lo guardado al destino elegido. Gracias al segundo paso no importa qué
    colección tenga seleccionada el usuario en ese momento.
    """
    asegurar_disponible(cfg)

    target = None
    destino = "la colección seleccionada"
    if dirigir:
        target, detalle = resolver_target(cfg)
        if target is None:
            raise SubcoleccionFaltante(
                cfg.zotero_coleccion_padre, cfg.zotero_subcoleccion
            )
        destino = detalle

    sesion = str(uuid.uuid4())
    base = f"http://127.0.0.1:{cfg.zotero_puerto}/connector"

    try:
        r = httpx.post(
            f"{base}/saveItems",
            json={"items": items, "sessionID": sesion, "uri": "https://phdjournal.local/"},
            headers=CABECERAS,
            timeout=90.0,
        )
    except Exception as exc:
        raise ErrorZotero(f"Falló el envío a Zotero: {exc}") from exc

    if r.status_code not in (200, 201):
        raise ErrorZotero(f"Zotero respondió {r.status_code}: {r.text[:300]}")

    dirigido = False
    if target is not None:
        try:
            r2 = httpx.post(
                f"{base}/updateSession",
                json={"sessionID": sesion, "target": target, "tags": ""},
                headers=CABECERAS,
                timeout=30.0,
            )
            dirigido = r2.status_code in (200, 201)
            if not dirigido:
                log.warning(
                    "updateSession respondió %s: %s", r2.status_code, r2.text[:200]
                )
        except Exception as exc:
            log.warning("No se pudo dirigir el ítem a la subcolección: %s", exc)

    # Los PDFs se suben después de dirigir la sesión, para que el adjunto
    # nazca ya dentro de la colección correcta.
    adjuntados = 0
    for item in items:
        for adjunto in item.get("attachments") or []:
            if _subir_adjunto(cfg, sesion, item, adjunto):
                adjuntados += 1

    return {
        "ok": True,
        "destino": destino if dirigido else "la colección seleccionada en Zotero",
        "dirigido": dirigido,
        "adjuntos": adjuntados,
        "sesion": sesion,
    }


def exportar_bibtex(papers: list[tuple[Paper, str | None]], destino: Path) -> Path:
    """Respaldo cuando Zotero no está disponible: un .bib importable a mano."""
    def clave(p: Paper) -> str:
        apellido = (p.autores[0].rsplit(" ", 1)[-1] if p.autores else "anon").lower()
        apellido = "".join(c for c in apellido if c.isalnum()) or "anon"
        return f"{apellido}{p.anio or 'sf'}"

    lineas = []
    usadas: set[str] = set()
    for paper, tag in papers:
        base = clave(paper)
        k, n = base, 1
        while k in usadas:
            n += 1
            k = f"{base}{chr(ord('a') + n - 2)}"
        usadas.add(k)

        tipo = "article" if paper.tipo_venue != "conference" else "inproceedings"
        campos = [
            f"  title = {{{paper.titulo}}}",
            f"  author = {{{' and '.join(paper.autores)}}}" if paper.autores else "",
            f"  year = {{{paper.anio}}}" if paper.anio else "",
            f"  journal = {{{paper.venue}}}" if paper.venue else "",
            f"  doi = {{{paper.doi}}}" if paper.doi else "",
            f"  url = {{{paper.url}}}" if paper.url else "",
            f"  keywords = {{PHDjournal{', ' + tag if tag else ''}}}",
        ]
        cuerpo = ",\n".join(c for c in campos if c)
        lineas.append(f"@{tipo}{{{k},\n{cuerpo}\n}}\n")

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino
