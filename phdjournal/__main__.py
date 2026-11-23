"""Punto de entrada.

    python -m phdjournal                     abre la ventana
    python -m phdjournal --minimizado        arranca solo en la bandeja
    python -m phdjournal --buscar            hace una corrida por consola y sale
    python -m phdjournal --resumir-faltantes rellena los resúmenes que faltan
    python -m phdjournal --analizar RUTA...  importa PDFs locales (archivos o
                                             carpetas) y los resume; con
                                             --sin-resumen solo los importa
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import DIR_DATOS


def _dpi_por_monitor() -> None:
    """Per-Monitor-V2 antes de crear cualquier ventana.

    Sin esto, Qt se ve borroso al mover la ventana entre la pantalla de la
    laptop y un monitor externo con escalado distinto.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            pass


def _configurar_log() -> None:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-28s %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    archivo = RotatingFileHandler(
        DIR_DATOS / "phdjournal.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setFormatter(formato)

    consola = logging.StreamHandler()
    consola.setFormatter(formato)

    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(archivo)
    raiz.addHandler(consola)

    # httpx es muy hablador con cada petición.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _resumir_faltantes() -> int:
    """Genera los resúmenes de los papers ya mostrados que se quedaron sin uno.

    Útil cuando una corrida se ejecutó antes de cargar la clave de la API: una
    búsqueda nueva trae papers nuevos, nunca rellena los viejos.
    """
    import json

    from . import db, pipeline, summarize
    from .config import Config
    from .ranking import Puntaje

    cfg = Config.cargar()
    if not cfg.tiene_clave():
        print("No hay clave de Claude. Cárgala en Configuración > Claude.")
        return 1

    db.inicializar()
    with db.conexion() as con:
        filas = con.execute(
            """SELECT DISTINCT p.*, s.puntaje, s.desglose, s.trabajo
                 FROM seleccion s
                 JOIN papers p ON p.id = s.paper_id
                 LEFT JOIN resumenes r ON r.paper_id = p.id
                WHERE r.paper_id IS NULL
                ORDER BY s.corrida_id, s.puesto"""
        ).fetchall()

    if not filas:
        print("No falta ningún resumen.")
        return 0

    print(f"{len(filas)} papers sin resumen. Generando con {cfg.modelo_claude}...\n")
    p_in, p_out = summarize.PRECIOS.get(cfg.modelo_claude, (0.0, 0.0))
    total_costo = 0.0
    fallos = 0

    for i, fila in enumerate(filas, start=1):
        paper = pipeline.paper_desde_fila(fila)
        desglose = json.loads(fila["desglose"] or "{}")
        puntaje = Puntaje(
            total=fila["puntaje"],
            relevancia=desglose.get("relevancia", 0.0),
            trabajo=fila["trabajo"],
            terminos_encontrados=desglose.get("terminos", []),
        )
        print(f"[{i}/{len(filas)}] {paper.titulo[:66]}")
        try:
            resumen, t_in, t_out = summarize.resumir(paper, puntaje, cfg)
            with db.conexion() as con:
                db.guardar_resumen(
                    con, paper.id, cfg.idioma_resumen, cfg.modelo_claude,
                    resumen, t_in, t_out, generado_por_ia=True,
                )
            costo = t_in / 1e6 * p_in + t_out / 1e6 * p_out
            total_costo += costo
            print(f"        {resumen['veredicto']}, {costo*100:.2f} centavos")
        except Exception as exc:
            fallos += 1
            print(f"        falló: {exc}")

    print(f"\nListo. {len(filas) - fallos} resúmenes, {total_costo*100:.1f} centavos USD.")
    if fallos:
        print(f"{fallos} fallaron.")
    return 0


def _analizar(rutas: list[str], resumir: bool) -> int:
    """Importa documentos locales desde la consola. No toca la búsqueda diaria."""
    from . import locales, summarize
    from .config import Config

    cfg = Config.cargar()
    pdfs = locales.buscar_pdfs(rutas)
    if not pdfs:
        print("No se encontró ningún PDF en las rutas indicadas.")
        return 1
    if resumir and not cfg.tiene_clave():
        print("Sin clave de Claude: se importan sin resumen.")
        resumir = False

    print(f"{len(pdfs)} PDFs.", end=" ")
    if resumir:
        print(f"Resumir cuesta {summarize.costo_documentos(cfg.modelo_claude, len(pdfs))}.")
    else:
        print()

    cuenta: dict[str, int] = {}
    for i, ruta in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] {ruta.name[:70]}")
        try:
            r = locales.importar(ruta, cfg, resumir)
        except Exception as exc:
            r = locales.Resultado(ruta, "error", str(exc))
        cuenta[r.estado] = cuenta.get(r.estado, 0) + 1
        marca = "DOI verificado" if r.verificado else "sin DOI verificado"
        print(f"        {r.estado}: {r.mensaje}" + (f" ({marca})" if r.estado == "nuevo" else ""))

    print()
    print("Listo. " + ", ".join(f"{v} {k}" for k, v in cuenta.items()) + ".")
    return 0


def main() -> int:
    _dpi_por_monitor()
    _configurar_log()

    if "--resumir-faltantes" in sys.argv:
        return _resumir_faltantes()

    if "--analizar" in sys.argv:
        rutas = [a for a in sys.argv[sys.argv.index("--analizar") + 1:]
                 if not a.startswith("--")]
        if not rutas:
            print("Uso: python -m phdjournal --analizar RUTA [RUTA...] [--sin-resumen]")
            return 2
        return _analizar(rutas, "--sin-resumen" not in sys.argv)

    if "--buscar" in sys.argv:
        from . import pipeline
        from .config import Config

        cfg = Config.cargar()
        resultado = pipeline.ejecutar(
            cfg, "manual", progreso=lambda m, p: print(f"[{p:3d}%] {m}")
        )
        print(
            f"\nCorrida {resultado.corrida_id}: {resultado.n_mostrados} papers "
            f"de {resultado.n_candidatos} candidatos."
        )
        for fuente, estado in resultado.estado_fuentes.items():
            print(f"  {fuente}: {estado}")
        for error in resultado.errores_resumen:
            print(f"  aviso: {error}")
        return 0

    from .ui.app import main as app_main

    return app_main(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
