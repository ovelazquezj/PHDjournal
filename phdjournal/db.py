"""Base de datos local de PHDjournal (SQLite).

Guarda todo lo que la app necesita recordar entre corridas:

* qué papers ya se mostraron, para no repetir ninguno nunca;
* el resumen generado y si lo generó una IA (trazabilidad de integridad);
* qué marcaste como útil y qué se exportó a Zotero;
* la cola de exportación pendiente cuando Zotero no estaba disponible.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DIR_DATOS

log = logging.getLogger(__name__)

RUTA_DB = DIR_DATOS / "phdjournal.sqlite"


ESQUEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    id              TEXT PRIMARY KEY,
    doi             TEXT,
    arxiv_id        TEXT,
    titulo          TEXT NOT NULL,
    autores         TEXT NOT NULL DEFAULT '[]',
    resumen_origen  TEXT,
    anio            INTEGER,
    fecha_pub       TEXT,
    venue           TEXT,
    tipo_venue      TEXT,
    url             TEXT,
    url_pdf         TEXT,
    citas           INTEGER DEFAULT 0,
    fuentes         TEXT NOT NULL DEFAULT '[]',
    crudo           TEXT NOT NULL DEFAULT '{}',
    visto_primera   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_arxiv ON papers(arxiv_id);

CREATE TABLE IF NOT EXISTS corridas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    franja       TEXT NOT NULL,          -- 'manana' | 'tarde' | 'manual'
    inicio       TEXT NOT NULL,
    fin          TEXT,
    n_candidatos INTEGER DEFAULT 0,
    n_mostrados  INTEGER DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS seleccion (
    corrida_id  INTEGER NOT NULL REFERENCES corridas(id) ON DELETE CASCADE,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    puesto      INTEGER NOT NULL,
    puntaje     REAL NOT NULL,
    desglose    TEXT NOT NULL DEFAULT '{}',
    trabajo     TEXT,                    -- clave de trabajos.json, o NULL
    PRIMARY KEY (corrida_id, paper_id)
);

CREATE TABLE IF NOT EXISTS resumenes (
    paper_id     TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    idioma       TEXT NOT NULL,
    modelo       TEXT NOT NULL,
    generado_en  TEXT NOT NULL,
    generado_por_ia INTEGER NOT NULL DEFAULT 1,
    contenido    TEXT NOT NULL,          -- JSON estructurado
    tokens_in    INTEGER DEFAULT 0,
    tokens_out   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS estado (
    paper_id         TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    leido            INTEGER NOT NULL DEFAULT 0,
    marcado          INTEGER NOT NULL DEFAULT 0,
    descartado       INTEGER NOT NULL DEFAULT 0,
    ruta_pdf         TEXT,
    ruta_audio       TEXT,
    exportado_zotero TEXT,
    notas            TEXT
);

CREATE TABLE IF NOT EXISTS cola_zotero (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    carga       TEXT NOT NULL,
    creado_en   TEXT NOT NULL,
    enviado_en  TEXT,
    intentos    INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conexion() -> Iterator[sqlite3.Connection]:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUTA_DB, timeout=15.0)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inicializar() -> None:
    _migrar()
    with conexion() as con:
        con.executescript(ESQUEMA)


# ---------------------------------------------------------------------------
# Migraciones
# ---------------------------------------------------------------------------

def _migrar() -> None:
    """Lleva bases viejas al esquema actual, con respaldo antes de tocar nada.

    Migración 1: ``seleccion.paper_tesis`` pasa a ``seleccion.trabajo``. La
    columna nació atada a "los papers de la tesis", que eran datos de una
    persona incrustados en el código; ahora los trabajos son configurables.
    """
    if not RUTA_DB.exists():
        return

    con = sqlite3.connect(RUTA_DB, timeout=15.0)
    try:
        cols = {
            f[1] for f in con.execute("PRAGMA table_info(seleccion)").fetchall()
        }
        if not cols or "paper_tesis" not in cols or "trabajo" in cols:
            return
    except sqlite3.Error:
        return
    finally:
        con.close()

    import shutil

    respaldo = RUTA_DB.with_suffix(f".sqlite.bak-{datetime.now():%Y%m%d%H%M%S}")
    shutil.copy2(RUTA_DB, respaldo)
    log.info("Respaldo de la base antes de migrar: %s", respaldo.name)

    con = sqlite3.connect(RUTA_DB, timeout=15.0)
    try:
        con.execute("ALTER TABLE seleccion RENAME COLUMN paper_tesis TO trabajo")
        con.commit()
        log.info("Migración: seleccion.paper_tesis -> seleccion.trabajo")
    except sqlite3.Error as exc:
        con.rollback()
        log.error("Falló la migración (%s). La base quedó intacta y hay respaldo "
                  "en %s", exc, respaldo.name)
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------

def guardar_paper(con: sqlite3.Connection, paper: Any) -> None:
    """Inserta o fusiona un paper. Los campos vacíos no pisan a los llenos."""
    fila = con.execute("SELECT * FROM papers WHERE id = ?", (paper.id,)).fetchone()
    if fila is None:
        con.execute(
            """INSERT INTO papers
               (id, doi, arxiv_id, titulo, autores, resumen_origen, anio,
                fecha_pub, venue, tipo_venue, url, url_pdf, citas, fuentes,
                crudo, visto_primera)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                paper.id, paper.doi, paper.arxiv_id, paper.titulo,
                json.dumps(paper.autores, ensure_ascii=False),
                paper.resumen, paper.anio, paper.fecha_pub, paper.venue,
                paper.tipo_venue, paper.url, paper.url_pdf, paper.citas,
                json.dumps(sorted(paper.fuentes), ensure_ascii=False),
                json.dumps(paper.crudo, ensure_ascii=False)[:200000],
                ahora(),
            ),
        )
        return

    fuentes = set(json.loads(fila["fuentes"])) | set(paper.fuentes)
    con.execute(
        """UPDATE papers SET
             doi = COALESCE(NULLIF(?, ''), doi),
             arxiv_id = COALESCE(NULLIF(?, ''), arxiv_id),
             resumen_origen = COALESCE(NULLIF(?, ''), resumen_origen),
             venue = COALESCE(NULLIF(?, ''), venue),
             tipo_venue = COALESCE(NULLIF(?, ''), tipo_venue),
             url_pdf = COALESCE(NULLIF(?, ''), url_pdf),
             citas = MAX(citas, ?),
             fuentes = ?
           WHERE id = ?""",
        (
            paper.doi or "", paper.arxiv_id or "", paper.resumen or "",
            paper.venue or "", paper.tipo_venue or "", paper.url_pdf or "",
            paper.citas or 0,
            json.dumps(sorted(fuentes), ensure_ascii=False),
            paper.id,
        ),
    )


def ids_ya_mostrados(con: sqlite3.Connection) -> set[str]:
    filas = con.execute("SELECT DISTINCT paper_id FROM seleccion").fetchall()
    return {f["paper_id"] for f in filas}


# ---------------------------------------------------------------------------
# Corridas y selección
# ---------------------------------------------------------------------------

def abrir_corrida(con: sqlite3.Connection, franja: str) -> int:
    cur = con.execute(
        "INSERT INTO corridas (franja, inicio) VALUES (?, ?)", (franja, ahora())
    )
    return int(cur.lastrowid)


def cerrar_corrida(
    con: sqlite3.Connection,
    corrida_id: int,
    n_candidatos: int,
    n_mostrados: int,
    error: str | None = None,
) -> None:
    con.execute(
        "UPDATE corridas SET fin=?, n_candidatos=?, n_mostrados=?, error=? WHERE id=?",
        (ahora(), n_candidatos, n_mostrados, error, corrida_id),
    )


def registrar_seleccion(
    con: sqlite3.Connection,
    corrida_id: int,
    paper_id: str,
    puesto: int,
    puntaje: float,
    desglose: dict,
    trabajo: str | None,
) -> None:
    con.execute(
        """INSERT OR REPLACE INTO seleccion
           (corrida_id, paper_id, puesto, puntaje, desglose, trabajo)
           VALUES (?,?,?,?,?,?)""",
        (
            corrida_id, paper_id, puesto, puntaje,
            json.dumps(desglose, ensure_ascii=False), trabajo,
        ),
    )
    con.execute(
        "INSERT OR IGNORE INTO estado (paper_id) VALUES (?)", (paper_id,)
    )


def ultima_corrida(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM corridas WHERE fin IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()


def papers_de_corrida(con: sqlite3.Connection, corrida_id: int) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT p.*, s.puesto, s.puntaje, s.desglose, s.trabajo,
                  e.leido, e.marcado, e.ruta_pdf, e.ruta_audio, e.exportado_zotero,
                  r.contenido AS resumen_json, r.modelo AS resumen_modelo,
                  r.generado_por_ia
           FROM seleccion s
           JOIN papers p ON p.id = s.paper_id
           LEFT JOIN estado e ON e.paper_id = s.paper_id
           LEFT JOIN resumenes r ON r.paper_id = s.paper_id
           WHERE s.corrida_id = ?
           ORDER BY s.puesto""",
        (corrida_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Resúmenes
# ---------------------------------------------------------------------------

def guardar_resumen(
    con: sqlite3.Connection,
    paper_id: str,
    idioma: str,
    modelo: str,
    contenido: dict,
    tokens_in: int = 0,
    tokens_out: int = 0,
    generado_por_ia: bool = True,
) -> None:
    con.execute(
        """INSERT OR REPLACE INTO resumenes
           (paper_id, idioma, modelo, generado_en, generado_por_ia, contenido,
            tokens_in, tokens_out)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            paper_id, idioma, modelo, ahora(), int(generado_por_ia),
            json.dumps(contenido, ensure_ascii=False), tokens_in, tokens_out,
        ),
    )


def leer_resumen(con: sqlite3.Connection, paper_id: str) -> dict | None:
    fila = con.execute(
        "SELECT contenido FROM resumenes WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    return json.loads(fila["contenido"]) if fila else None


# ---------------------------------------------------------------------------
# Estado por paper
# ---------------------------------------------------------------------------

def marcar(con: sqlite3.Connection, paper_id: str, campo: str, valor: Any) -> None:
    permitidos = {
        "leido", "marcado", "descartado", "ruta_pdf", "ruta_audio",
        "exportado_zotero", "notas",
    }
    if campo not in permitidos:
        raise ValueError(f"campo no permitido: {campo}")
    con.execute("INSERT OR IGNORE INTO estado (paper_id) VALUES (?)", (paper_id,))
    con.execute(f"UPDATE estado SET {campo} = ? WHERE paper_id = ?", (valor, paper_id))


# ---------------------------------------------------------------------------
# Cola de Zotero
# ---------------------------------------------------------------------------

def encolar_zotero(con: sqlite3.Connection, paper_id: str, carga: dict) -> int:
    cur = con.execute(
        "INSERT INTO cola_zotero (paper_id, carga, creado_en) VALUES (?,?,?)",
        (paper_id, json.dumps(carga, ensure_ascii=False), ahora()),
    )
    return int(cur.lastrowid)


def cola_zotero_pendiente(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM cola_zotero WHERE enviado_en IS NULL ORDER BY id"
    ).fetchall()


def cerrar_item_cola(
    con: sqlite3.Connection, item_id: int, ok: bool, error: str | None = None
) -> None:
    if ok:
        con.execute(
            "UPDATE cola_zotero SET enviado_en=?, ultimo_error=NULL WHERE id=?",
            (ahora(), item_id),
        )
    else:
        con.execute(
            "UPDATE cola_zotero SET intentos=intentos+1, ultimo_error=? WHERE id=?",
            (error, item_id),
        )


# ---------------------------------------------------------------------------
# Clave/valor
# ---------------------------------------------------------------------------

def kv_get(con: sqlite3.Connection, clave: str, defecto: str = "") -> str:
    fila = con.execute("SELECT valor FROM kv WHERE clave = ?", (clave,)).fetchone()
    return fila["valor"] if fila else defecto


def kv_set(con: sqlite3.Connection, clave: str, valor: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO kv (clave, valor) VALUES (?, ?)", (clave, valor)
    )
