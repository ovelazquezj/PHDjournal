"""Ranking híbrido (opción D).

    puntaje = 0.60 relevancia + 0.20 venue + 0.12 citas + 0.08 novedad

Los cuatro pesos son editables en la pantalla de configuración. Cada
componente devuelve 0..1 y guarda su explicación, de modo que la ficha de
cada paper puede responder "por qué me estás mostrando esto".

**La relevancia la deciden los temas, no los trabajos propios.** La puerta de
entrada pregunta "¿esto es de mi campo?", no "¿esto encaja en algo que estoy
escribiendo?". Un paper de tokenización subléxica para español entra por el
tema de NLP aunque no toque ningún trabajo en curso.

La etiqueta de trabajo propio es informativa y **no altera el puntaje**.
Cuando el encaje no es claro, el paper sale sin etiqueta y no pasa nada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from . import profile, temas, trabajos, venues
from .config import Config
from .sources.base import Paper, normalizar_texto

# Constante de saturación de la relevancia. Con la red abierta a diez
# dominios, los puntajes brutos son más altos que antes, así que K también.
K_SATURACION = 18.0

# Un término en el título pesa el triple que en el resumen.
FACTOR_TITULO = 3.0


@dataclass
class Puntaje:
    total: float = 0.0
    relevancia: float = 0.0
    venue: float = 0.0
    citas: float = 0.0
    novedad: float = 0.0
    trabajo: str | None = None
    dominios: list[str] = field(default_factory=list)      # ["D1", "D3"]
    nombres_dominios: list[str] = field(default_factory=list)
    terminos_encontrados: list[str] = field(default_factory=list)
    explicacion: dict[str, str] = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "total": round(self.total, 4),
            "relevancia": round(self.relevancia, 4),
            "venue": round(self.venue, 4),
            "citas": round(self.citas, 4),
            "novedad": round(self.novedad, 4),
            "trabajo": self.trabajo,
            "dominios": self.dominios,
            "nombres_dominios": self.nombres_dominios,
            "terminos": self.terminos_encontrados[:25],
            "explicacion": self.explicacion,
        }


def _puntos_de_terminos(
    texto: str, titulo: str, terminos: dict[str, float]
) -> tuple[float, list[str]]:
    puntos = 0.0
    encontrados: list[str] = []
    for termino, peso in terminos.items():
        t = normalizar_texto(termino)
        if not t:
            continue
        if t in titulo:
            puntos += peso * FACTOR_TITULO
            encontrados.append(termino)
        elif t in texto:
            puntos += peso
            encontrados.append(termino)
    return puntos, encontrados


def _etiquetar(texto: str, titulo: str, trabajos_cargados=None) -> str | None:
    """Devuelve la clave del trabajo propio que encaja, o None.

    No participa en el puntaje: es una etiqueta informativa. Antes esta función
    elegía entre cuatro papers de tesis incrustados en el código; ahora los
    trabajos son dato del usuario.
    """
    cargados = trabajos_cargados if trabajos_cargados is not None else trabajos.cargar()
    return trabajos.etiquetar(texto, titulo, cargados, _puntos_de_terminos)


def _relevancia(
    paper: Paper, perfil: "temas.Perfil"
) -> tuple[float, list[str], list[str], list[str], str]:
    """Devuelve (relevancia, claves de dominio, nombres, términos, detalle)."""
    texto = paper.texto_busqueda
    titulo = normalizar_texto(paper.titulo)

    # Veto por dominio ajeno antes que nada: no vale la pena puntuar un paper
    # de segmentación de imágenes por mucho que diga "transformer".
    castigo, castigados = _puntos_de_terminos(texto, titulo, perfil.penalizaciones)
    if castigo >= perfil.umbral_veto:
        return 0.0, [], [], [], f"dominio ajeno ({', '.join(castigados[:3])}), descartado"

    # Puntaje por dominio
    por_dominio: dict[str, float] = {}
    terminos: list[str] = []
    for clave, dom in perfil.dominios.items():
        puntos, hallados = _puntos_de_terminos(texto, titulo, dom.terminos)
        if puntos > 0:
            por_dominio[clave] = puntos
            terminos.extend(hallados)

    detectados = [c for c, p in por_dominio.items() if p >= perfil.umbral_dominio]

    # La puerta: hace falta un tema que abra por sí solo. El borde (D3) no
    # abre: es el escenario, no el tema.
    abre = [c for c in detectados if c in perfil.abren]
    if not abre:
        if detectados:
            nombres = ", ".join(perfil.nombre(c) for c in detectados)
            return 0.0, [], [], [], (
                f"toca {nombres} pero ningún tema de los que abren, descartado"
            )
        mejor = max(por_dominio.values(), default=0.0)
        return 0.0, [], [], [], (
            f"ningún tema alcanza el umbral (máximo {mejor:.1f} de "
            f"{perfil.umbral_dominio}), descartado"
        )

    # Relevancia: suma ponderada por el peso de cada dominio detectado.
    bruto = sum(por_dominio[c] * perfil.dominios[c].peso for c in detectados)
    neto = max(0.0, bruto - castigo)
    rel = neto / (neto + K_SATURACION)

    # Bono por amplitud: un paper que cruza dos temas de núcleo es justo lo
    # que se busca (NLP en el borde es D1 x D3).
    nucleo = [c for c in detectados if perfil.dominios[c].capa == profile.NUCLEO]
    if len(nucleo) >= 2:
        rel = min(1.0, rel * 1.15)

    detectados.sort(key=lambda c: por_dominio[c], reverse=True)
    nombres = [perfil.nombre(c) for c in detectados]

    detalle = f"{neto:.1f} pts en " + ", ".join(
        f"{c} {por_dominio[c]:.0f}" for c in detectados
    )
    if len(nucleo) >= 2:
        detalle += ", cruza dos dominios de núcleo (+15%)"
    if castigados:
        detalle += f", castigo {castigo:.1f} por {', '.join(castigados[:2])}"

    return rel, detectados, nombres, sorted(set(terminos)), detalle


def _citas(paper: Paper, hoy: date) -> tuple[float, str]:
    """Velocidad de citas, no conteo bruto."""
    if paper.citas <= 0:
        return 0.0, "sin citas todavía"
    f = paper.fecha
    if f is None:
        return 0.0, "sin fecha, no se puede calcular velocidad"
    meses = max((hoy - f).days / 30.44, 0.5)
    velocidad = paper.citas / meses
    valor = min(1.0, math.log1p(velocidad) / math.log1p(10.0))
    return valor, f"{paper.citas} citas en {meses:.1f} meses ({velocidad:.2f}/mes)"


def _novedad(paper: Paper, hoy: date) -> tuple[float, str]:
    f = paper.fecha
    if f is None:
        return 0.3, "sin fecha"
    dias = (hoy - f).days
    if dias < -90:
        # Crossref y OpenAlex tienen registros con fechas imposibles. Sin esta
        # guarda, un paper fechado en 2114 se lleva la novedad máxima.
        return 0.2, f"fecha futura sospechosa ({f.isoformat()})"
    if dias < -7:
        # Fecha adelantada: revistas que ponen la fecha de portada del número
        # que aún no sale. Sin esto, `max(dias, 0)` le daba novedad 1.00, la
        # misma que a un paper de hoy. Se midió: 11 registros de una ventana
        # de 21 días venían fechados hasta 77 días en el futuro.
        return 0.45, f"fecha adelantada ({f.isoformat()}), número futuro de la revista"
    dias = max(dias, 0)
    valor = math.exp(-dias / 30.0)
    return valor, f"{dias} días desde publicación"


def puntuar(
    paper: Paper,
    cfg: Config,
    hoy: date | None = None,
    perfil: "temas.Perfil | None" = None,
) -> Puntaje:
    hoy = hoy or date.today()
    pesos = cfg.pesos_normalizados()
    perfil = perfil if perfil is not None else temas.construir()

    rel, dominios, nombres, terminos, det_rel = _relevancia(paper, perfil)
    ven, det_ven = venues.puntuar(paper.venue, paper.tipo_venue, paper.doi)
    cit, det_cit = _citas(paper, hoy)
    nov, det_nov = _novedad(paper, hoy)

    total = (
        pesos["relevancia"] * rel
        + pesos["venue"] * ven
        + pesos["citas"] * cit
        + pesos["novedad"] * nov
    )
    # Un paper que no pasó la puerta no se rescata por venue ni por citas.
    if rel <= 0:
        total = 0.0

    # La etiqueta va al final y a propósito: no participa en el puntaje.
    etiqueta = None
    if rel > 0:
        etiqueta = _etiquetar(paper.texto_busqueda, normalizar_texto(paper.titulo))

    return Puntaje(
        total=total,
        relevancia=rel,
        venue=ven,
        citas=cit,
        novedad=nov,
        trabajo=etiqueta,
        dominios=dominios,
        nombres_dominios=nombres,
        terminos_encontrados=terminos,
        explicacion={
            "relevancia": det_rel,
            "venue": det_ven,
            "citas": det_cit,
            "novedad": det_nov,
            "etiqueta": (
                f"toca tu trabajo {etiqueta}" if etiqueta
                else "no toca ninguno de tus trabajos, es de interés general"
            ),
            "pesos": (
                f"rel {pesos['relevancia']:.2f} / venue {pesos['venue']:.2f} / "
                f"citas {pesos['citas']:.2f} / nov {pesos['novedad']:.2f}"
            ),
        },
    )


def ordenar(
    papers: list[Paper],
    cfg: Config,
    excluir: set[str] | None = None,
    hoy: date | None = None,
    perfil: "temas.Perfil | None" = None,
) -> list[tuple[Paper, Puntaje]]:
    """Puntúa, descarta lo ya visto y lo que no pasó la puerta, y ordena."""
    excluir = excluir or set()
    perfil = perfil if perfil is not None else temas.construir()
    salida: list[tuple[Paper, Puntaje]] = []
    for paper in papers:
        if paper.id in excluir:
            continue
        if len(paper.resumen) < 80:
            # Sin resumen no hay nada que resumir ni que puntuar bien.
            continue
        p = puntuar(paper, cfg, hoy, perfil)
        if p.total <= 0:
            continue
        salida.append((paper, p))
    salida.sort(key=lambda par: par[1].total, reverse=True)
    return salida


def detectar_temas(
    titulo: str, texto: str, perfil: "temas.Perfil | None" = None
) -> dict:
    """Qué temas y qué trabajo propio toca un documento, sin puerta ni puntaje.

    Es para los documentos locales: ya los elegiste tú, así que no hay nada
    que filtrar. Solo se etiquetan. Se usan las mismas reglas de términos que
    el ranking (umbral por tema, título triple), pero ningún tema "abre" ni
    "cierra" nada y no hay veto: un documento tuyo de otro campo simplemente
    sale sin temas.

    ``texto`` debe ser el título más el abstract, no el documento completo:
    los umbrales están calibrados para abstracts, y un PDF entero de veinte
    páginas toca casi todos los temas por pura acumulación.
    """
    perfil = perfil if perfil is not None else temas.construir()
    texto_n = normalizar_texto(f"{titulo} {texto}")
    titulo_n = normalizar_texto(titulo)

    por_dominio: dict[str, float] = {}
    terminos: list[str] = []
    for clave, dom in perfil.dominios.items():
        puntos, hallados = _puntos_de_terminos(texto_n, titulo_n, dom.terminos)
        if puntos >= perfil.umbral_dominio:
            por_dominio[clave] = puntos
            terminos.extend(hallados)

    detectados = sorted(por_dominio, key=lambda c: por_dominio[c], reverse=True)
    etiqueta = _etiquetar(texto_n, titulo_n) if detectados else None
    return {
        "dominios": detectados,
        "nombres_dominios": [perfil.nombre(c) for c in detectados],
        "terminos": sorted(set(terminos))[:25],
        "trabajo": etiqueta,
    }
