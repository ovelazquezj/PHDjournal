"""Resúmenes en español con la API de Claude.

Cada resumen es un objeto con campos fijos (salida estructurada, no texto
libre) para que la interfaz pueda mostrarlos siempre igual y para que el campo
``texto_para_voz`` sea un párrafo limpio, sin viñetas ni citas, que suene bien
leído en voz alta.

Trazabilidad: todo lo que sale de aquí se marca en la base como generado por
IA, con el modelo que lo produjo, y la nota que viaja a Zotero lleva un aviso
explícito de no citar el resumen sin verificar contra el original.

Para quién escribe Claude sale de la configuración, no del código. Antes
estaba incrustado aquí el perfil de una persona concreta, con el título de su
tesis; era un error que ataba la herramienta a su primer usuario.
"""

from __future__ import annotations

import json
import logging
import re

import anthropic

from .config import Config
from .ranking import Puntaje
from .sources.base import Paper

log = logging.getLogger(__name__)

# Precio por millón de tokens (entrada, salida). Solo para estimar el gasto
# en la pantalla de configuración.
PRECIOS = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# `effort` no existe en toda la familia: Haiku 4.5 devuelve
# 400 "This model does not support the effort parameter". Solo se manda a los
# modelos que lo aceptan; para el resto se omite y ya.
MODELOS_CON_EFFORT = {
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-sonnet-4-6", "claude-fable-5", "claude-fable-5-1",
}


def _output_config(modelo: str, formato: dict | None = None) -> dict | None:
    """Arma output_config según lo que el modelo admita."""
    cfg: dict = {}
    if formato is not None:
        cfg["format"] = formato
    if modelo in MODELOS_CON_EFFORT:
        # Resumir un abstract no es tarea difícil; effort bajo recorta el
        # gasto sin bajar de modelo.
        cfg["effort"] = "low"
    return cfg or None

ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo_es": {
            "type": "string",
            "description": "El título traducido al español, técnico y fiel.",
        },
        "que_hace": {
            "type": "string",
            "description": "Dos o tres frases: qué problema ataca y qué propone.",
        },
        "metodo": {
            "type": "string",
            "description": "Una o dos frases sobre cómo lo hace, con el hardware o los datos si vienen.",
        },
        "hallazgo": {
            "type": "string",
            "description": "El resultado principal, con cifras si el resumen las da.",
        },
        "por_que_te_importa": {
            "type": "string",
            "description": (
                "Dos o tres frases conectando el paper con la investigación del "
                "lector. Conéctalo primero con sus TEMAS. Menciona uno de sus "
                "trabajos propios por su clave solo si el encaje es real; si el "
                "paper es de interés general para su campo, dilo así y no fuerces "
                "la conexión. Di si confirma, contradice o complementa."
            ),
        },
        "limitaciones": {
            "type": "string",
            "description": "Una frase con la debilidad más seria o lo que el trabajo no cubre.",
        },
        "veredicto": {
            "type": "string",
            "enum": ["leer completo", "hojear", "solo el abstract"],
            "description": "Cuánta atención merece.",
        },
        "texto_para_voz": {
            "type": "string",
            "description": (
                "El resumen completo como UN SOLO párrafo corrido de 120 a 180 "
                "palabras, pensado para escucharse. Sin viñetas, sin títulos de "
                "sección, sin citas bibliográficas, sin siglas sin explicar, sin "
                "URLs ni números de DOI. Frases cortas. Que se entienda de oído."
            ),
        },
    },
    "required": [
        "titulo_es", "que_hace", "metodo", "hallazgo", "por_que_te_importa",
        "limitaciones", "veredicto", "texto_para_voz",
    ],
    "additionalProperties": False,
}

SISTEMA_BASE = """Eres el asistente de lectura de un investigador.

{perfil}

Escribe en español, con los términos técnicos en inglés cuando esa sea la
forma en que se usan en la literatura: edge, knowledge graph, small language
model, quantization, retrieval-augmented generation, latency. No traduzcas
forzadamente lo que nadie traduce.

Reglas de estilo:
- Directo y sin relleno. Nada de "este artículo presenta" ni "los autores proponen".
- No uses guión largo. Usa coma.
- No inventes cifras ni resultados que no estén en el material que recibes.
- Si el material es pobre, dilo en las limitaciones en lugar de rellenar.
- En por_que_te_importa sé concreto y honesto: si el paper no le sirve, dilo."""


def _perfil_investigador(cfg: Config) -> str:
    """El párrafo que le dice a Claude para quién escribe.

    Sale de la configuración. Si está vacío, se arma con los temas activos y
    los trabajos declarados, para que la app dé resúmenes razonables recién
    instalada sin obligar a llenar nada.
    """
    from . import temas, trabajos as trabajos_mod

    partes = []
    propio = (cfg.perfil_investigador or "").strip()
    if propio:
        partes.append(propio)
    else:
        perfil = temas.construir()
        nombres = [d.nombre for d in perfil.dominios.values()]
        if nombres:
            partes.append(
                "Su investigación cubre estos temas: " + ", ".join(nombres) + "."
            )
        else:
            partes.append(
                "No ha declarado su campo todavía; escribe para un investigador "
                "técnico general."
            )

    trabajos = {c: t for c, t in trabajos_mod.cargar().items() if t.activo}
    if trabajos:
        lineas = [
            f"- {c}: {t.nombre}" + (f" ({t.nota})" if t.nota else "")
            for c, t in trabajos.items()
        ]
        partes.append(
            "Sus trabajos propios en curso, que puedes citar por su clave "
            "cuando un paper los toque de verdad:\n" + "\n".join(lineas)
        )

    return "\n\n".join(partes)


def sistema(cfg: Config) -> str:
    return SISTEMA_BASE.format(perfil=_perfil_investigador(cfg))


class ErrorResumen(RuntimeError):
    pass


def _cliente(cfg: Config) -> anthropic.Anthropic:
    clave = cfg.get_clave_claude()
    if not clave:
        raise ErrorResumen(
            "No hay clave de la API de Claude. Cárgala en la pantalla de configuración."
        )
    return anthropic.Anthropic(api_key=clave, max_retries=3)


def _prompt(paper: Paper, puntaje: Puntaje) -> str:
    autores = ", ".join(paper.autores[:6])
    if len(paper.autores) > 6:
        autores += " y otros"
    partes = [
        f"Título: {paper.titulo}",
        f"Autores: {autores}" if autores else "",
        f"Venue: {paper.venue or 'sin dato'} ({paper.tipo_venue})",
        f"Fecha: {paper.fecha_pub or paper.anio or 'sin dato'}",
        f"Citas registradas: {paper.citas}",
        f"DOI: {paper.doi}" if paper.doi else "",
        "",
        "Resumen original:",
        paper.resumen,
        "",
        "Señales del buscador (contexto, no las repitas literalmente):",
        f"- Temas detectados: {', '.join(puntaje.nombres_dominios) or 'ninguno'}",
        (
            f"- Encaje con un trabajo propio: {puntaje.trabajo}"
            if puntaje.trabajo
            else "- Encaje con un trabajo propio: ninguno claro, es de interés general"
        ),
        f"- Términos detectados: {', '.join(puntaje.terminos_encontrados[:15]) or 'ninguno'}",
    ]
    return "\n".join(p for p in partes if p != "")


def resumir(paper: Paper, puntaje: Puntaje, cfg: Config) -> tuple[dict, int, int]:
    """Devuelve (resumen estructurado, tokens_entrada, tokens_salida)."""
    cliente = _cliente(cfg)
    formato = {"type": "json_schema", "schema": ESQUEMA}

    def _llamar(con_effort: bool):
        extra = {}
        salida = _output_config(cfg.modelo_claude if con_effort else "", formato)
        if salida:
            extra["output_config"] = salida
        return cliente.messages.create(
            model=cfg.modelo_claude,
            max_tokens=cfg.resumen_max_tokens,
            system=sistema(cfg),
            messages=[{"role": "user", "content": _prompt(paper, puntaje)}],
            **extra,
        )

    try:
        try:
            respuesta = _llamar(con_effort=True)
        except anthropic.BadRequestError as exc:
            # Red de seguridad para modelos nuevos que tampoco acepten effort.
            if "effort" not in str(exc):
                raise
            log.info("El modelo %s rechazó 'effort'; se reintenta sin él", cfg.modelo_claude)
            respuesta = _llamar(con_effort=False)
    except anthropic.NotFoundError as exc:
        raise ErrorResumen(f"Modelo no encontrado: {cfg.modelo_claude}") from exc
    except anthropic.AuthenticationError as exc:
        raise ErrorResumen("La clave de la API fue rechazada.") from exc
    except anthropic.RateLimitError as exc:
        raise ErrorResumen("Límite de peticiones alcanzado, intenta más tarde.") from exc
    except anthropic.APIStatusError as exc:
        raise ErrorResumen(f"La API respondió {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise ErrorResumen("No hubo conexión con la API de Claude.") from exc

    if respuesta.stop_reason == "refusal":
        raise ErrorResumen("El modelo declinó resumir este material.")

    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    if not texto:
        raise ErrorResumen("La respuesta vino vacía.")

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ErrorResumen(f"La respuesta no era JSON válido: {exc}") from exc

    faltantes = [c for c in ESQUEMA["required"] if not datos.get(c)]
    if faltantes:
        raise ErrorResumen(f"Al resumen le faltan campos: {', '.join(faltantes)}")

    uso = respuesta.usage
    return datos, int(uso.input_tokens or 0), int(uso.output_tokens or 0)


# ---------------------------------------------------------------------------
# Documentos locales
# ---------------------------------------------------------------------------

# Cuánto del documento se manda. ~40 mil caracteres son ~10 mil tokens: cubre
# un paper de conferencia entero y la mitad de uno de revista largo, que es
# donde están el problema, el método y los resultados.
DOCUMENTO_MAX_CHARS = 40_000

# Aproximado: tokens de entrada y salida por documento local.
TOKENS_DOCUMENTO = (11_000, 1_100)

ESQUEMA_DOCUMENTO = {
    "type": "object",
    "properties": {
        **ESQUEMA["properties"],
        "hallazgo": {
            "type": "string",
            "description": "El resultado principal, con las cifras que da el documento.",
        },
        "metadatos": {
            "type": "object",
            "description": (
                "Los datos bibliográficos tal como aparecen en la portada del "
                "documento. Cadena vacía en lo que no aparezca. No adivines."
            ),
            "properties": {
                "titulo": {"type": "string", "description": "Título original, sin traducir."},
                "autores": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nombre y apellido de cada autor, en orden.",
                },
                "anio": {"type": "string", "description": "Año de publicación, cuatro dígitos."},
                "venue": {"type": "string", "description": "Revista, congreso o repositorio."},
                "tipo": {
                    "type": "string",
                    "enum": [
                        "journal", "conference", "preprint", "book", "thesis",
                        "report", "otro",
                    ],
                },
                "doi": {
                    "type": "string",
                    "description": "El DOI de ESTE documento, no el de una referencia.",
                },
                "abstract": {
                    "type": "string",
                    "description": "El abstract copiado literal, en su idioma original.",
                },
            },
            "required": ["titulo", "autores", "anio", "venue", "tipo", "doi", "abstract"],
            "additionalProperties": False,
        },
    },
    "required": [*ESQUEMA["required"], "metadatos"],
    "additionalProperties": False,
}

_REFERENCIAS = re.compile(
    r"^\s*(?:\d+\.?\s+)?(references|bibliography|referencias|bibliografía)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _recortar_documento(texto: str) -> str:
    """Quita las referencias y recorta al tope.

    Las referencias son la parte más larga de muchos papers y no aportan nada
    al resumen; peor, traen títulos de otros trabajos que confunden al modelo
    sobre de qué trata este. Se corta en el último encabezado de referencias,
    siempre que esté en la segunda mitad (si aparece antes, es otra cosa).
    """
    cortes = list(_REFERENCIAS.finditer(texto))
    if cortes and cortes[-1].start() > len(texto) * 0.5:
        texto = texto[: cortes[-1].start()]
    if len(texto) > DOCUMENTO_MAX_CHARS:
        texto = texto[:DOCUMENTO_MAX_CHARS] + "\n\n[... documento recortado ...]"
    return texto


def resumir_documento(
    texto: str,
    cfg: Config,
    metadatos_conocidos: dict | None = None,
    temas_detectados: list[str] | None = None,
    trabajo: str | None = None,
) -> tuple[dict, int, int]:
    """Resume un PDF local a partir de su texto completo.

    Devuelve (resumen con campo ``metadatos``, tokens_entrada, tokens_salida).
    Los metadatos verificados por DOI se mandan como contexto, pero el modelo
    igual devuelve los que lee en la portada: sin DOI, son la mejor fuente que
    hay.
    """
    cliente = _cliente(cfg)
    partes = []
    if metadatos_conocidos:
        partes.append(
            "Metadatos verificados por DOI (contexto):\n"
            + "\n".join(f"- {k}: {v}" for k, v in metadatos_conocidos.items() if v)
        )
    partes.append(
        "Señales del buscador (contexto, no las repitas literalmente):\n"
        f"- Temas detectados: {', '.join(temas_detectados or []) or 'ninguno'}\n"
        + (
            f"- Encaje con un trabajo propio: {trabajo}"
            if trabajo
            else "- Encaje con un trabajo propio: ninguno claro"
        )
    )
    partes.append(
        "Este es el TEXTO COMPLETO de un documento que el investigador tiene en "
        "su disco, extraído de un PDF (puede traer cortes de línea, encabezados "
        "de página y fórmulas rotas). Resúmelo. Tienes más que un abstract, así "
        "que el método y el hallazgo deben ser concretos.\n\n"
        "<documento>\n" + _recortar_documento(texto) + "\n</documento>"
    )
    prompt = "\n\n".join(partes)

    def _llamar(con_effort: bool):
        extra = {}
        salida = _output_config(
            cfg.modelo_claude if con_effort else "",
            {"type": "json_schema", "schema": ESQUEMA_DOCUMENTO},
        )
        if salida:
            extra["output_config"] = salida
        return cliente.messages.create(
            model=cfg.modelo_claude,
            max_tokens=max(cfg.resumen_max_tokens, 3000),
            system=sistema(cfg),
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )

    try:
        try:
            respuesta = _llamar(con_effort=True)
        except anthropic.BadRequestError as exc:
            if "effort" not in str(exc):
                raise
            respuesta = _llamar(con_effort=False)
    except anthropic.NotFoundError as exc:
        raise ErrorResumen(f"Modelo no encontrado: {cfg.modelo_claude}") from exc
    except anthropic.AuthenticationError as exc:
        raise ErrorResumen("La clave de la API fue rechazada.") from exc
    except anthropic.RateLimitError as exc:
        raise ErrorResumen("Límite de peticiones alcanzado, intenta más tarde.") from exc
    except anthropic.APIStatusError as exc:
        raise ErrorResumen(f"La API respondió {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise ErrorResumen("No hubo conexión con la API de Claude.") from exc

    if respuesta.stop_reason == "refusal":
        raise ErrorResumen("El modelo declinó resumir este documento.")
    if respuesta.stop_reason == "max_tokens":
        raise ErrorResumen("El resumen se cortó por longitud; sube el tope de tokens.")

    texto_r = next((b.text for b in respuesta.content if b.type == "text"), "")
    try:
        datos = json.loads(texto_r)
    except json.JSONDecodeError as exc:
        raise ErrorResumen(f"La respuesta no era JSON válido: {exc}") from exc

    faltantes = [c for c in ESQUEMA["required"] if not datos.get(c)]
    if faltantes:
        raise ErrorResumen(f"Al resumen le faltan campos: {', '.join(faltantes)}")

    uso = respuesta.usage
    return datos, int(uso.input_tokens or 0), int(uso.output_tokens or 0)


def costo_documentos(modelo: str, n: int) -> str:
    """Estimación para confirmar antes de resumir un lote de documentos."""
    precios = PRECIOS.get(modelo)
    if not precios:
        return "sin estimación de costo para este modelo"
    t_in, t_out = TOKENS_DOCUMENTO
    total = n * (t_in / 1e6 * precios[0] + t_out / 1e6 * precios[1])
    plural = "s" if n != 1 else ""
    return f"~{total:.2f} USD con {modelo} ({n} documento{plural})"


def resumir_seccion(titulo_seccion: str, texto: str, cfg: Config) -> str:
    """Resume una sección del PDF completo, en un párrafo apto para escuchar."""
    cliente = _cliente(cfg)
    prompt = (
        f"Sección: {titulo_seccion}\n\n{texto[:24000]}\n\n"
        "Resume esta sección en un solo párrafo de 100 a 150 palabras, escrito "
        "para escucharse en voz alta. Sin viñetas, sin citas, sin URLs."
    )
    def _llamar(con_effort: bool):
        extra = {}
        salida = _output_config(cfg.modelo_claude if con_effort else "")
        if salida:
            extra["output_config"] = salida
        return cliente.messages.create(
            model=cfg.modelo_claude,
            max_tokens=1200,
            system=sistema(cfg),
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )

    try:
        respuesta = _llamar(con_effort=True)
    except anthropic.BadRequestError as exc:
        if "effort" not in str(exc):
            raise
        respuesta = _llamar(con_effort=False)

    if respuesta.stop_reason == "refusal":
        raise ErrorResumen("El modelo declinó resumir esta sección.")
    return "".join(b.text for b in respuesta.content if b.type == "text").strip()


ESQUEMA_TEMA = {
    "type": "object",
    "properties": {
        "nombre": {
            "type": "string",
            "description": "Nombre corto del tema en español, 2 a 5 palabras.",
        },
        "capa": {
            "type": "string",
            "enum": ["nucleo", "puente", "soporte"],
            "description": (
                "nucleo si el tema define la especialidad del investigador; "
                "puente si conecta su especialidad con otra área; soporte si es "
                "metodología o contexto."
            ),
        },
        # OJO: la salida estructurada solo admite minItems 0 o 1. Pedir "entre
        # 12 y 40" en el esquema devuelve 400; va en la descripción.
        "terminos": {
            "type": "array",
            "description": "Entre 12 y 40 términos. Menos de 12 y el tema no discrimina.",
            "items": {
                "type": "object",
                "properties": {
                    "termino": {
                        "type": "string",
                        "description": (
                            "Término técnico EN INGLÉS, como aparece en la "
                            "literatura. Prefiere frases de dos o tres palabras: "
                            "un token suelto y ambiguo trae ruido."
                        ),
                    },
                    "peso": {
                        "type": "number",
                        "description": (
                            "1.0 a 3.5. Usa 3.0 o más solo para términos que por "
                            "sí solos identifican el tema sin ambigüedad."
                        ),
                    },
                },
                "required": ["termino", "peso"],
                "additionalProperties": False,
            },
        },
        "consultas_texto": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "De 2 a 5 consultas en lenguaje natural para OpenAlex y Crossref."
            ),
        },
        "consultas_arxiv": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                'De 2 a 5 consultas con sintaxis de arXiv, p. ej. abs:"federated learning".'
            ),
        },
        "advertencia": {
            "type": "string",
            "description": (
                "Una frase sobre el riesgo de ruido de este tema, o cadena vacía "
                "si no hay riesgo notable. Sé honesto: si los términos son "
                "genéricos y van a traer basura, dilo."
            ),
        },
    },
    "required": [
        "nombre", "capa", "terminos", "consultas_texto", "consultas_arxiv",
        "advertencia",
    ],
    "additionalProperties": False,
}

SISTEMA_TEMA = """Construyes perfiles de búsqueda bibliográfica.

{perfil}

Va a usar tu lista de términos para filtrar papers de arXiv, OpenAlex,
Semantic Scholar y Crossref.

Cómo se usan los términos: se buscan como subcadena en el título y el resumen
ya normalizados (minúsculas, sin acentos, sin puntuación). Un término en el
título pesa el triple. Los pesos de los términos hallados se suman, y el tema
"cuenta" a partir de 3.0 puntos.

Consecuencias que debes respetar:
- Un término de una sola palabra común ("model", "edge", "graph") es veneno:
  captura cualquier cosa. Usa frases.
- No incluyas términos que ya identifiquen otro campo entero, salvo que el
  tema sea justamente ese.
- Los términos van en inglés, que es el idioma de los papers. El nombre del
  tema va en español.
- No uses guión largo."""


def generar_tema(descripcion: str, cfg: Config) -> dict:
    """Convierte la descripción de un tema en términos, pesos y consultas."""
    cliente = _cliente(cfg)
    prompt = (
        f"El investigador quiere seguir este tema:\n\n{descripcion}\n\n"
        "Genera el perfil de búsqueda: nombre, capa, términos con pesos y "
        "consultas. Si el tema es demasiado amplio o ambiguo, dilo en la "
        "advertencia en lugar de inventar términos genéricos."
    )

    def _llamar(con_effort: bool):
        extra = {}
        salida = _output_config(
            cfg.modelo_claude if con_effort else "",
            {"type": "json_schema", "schema": ESQUEMA_TEMA},
        )
        if salida:
            extra["output_config"] = salida
        return cliente.messages.create(
            model=cfg.modelo_claude,
            max_tokens=4000,
            system=SISTEMA_TEMA.format(perfil=_perfil_investigador(cfg)),
            messages=[{"role": "user", "content": prompt}],
            **extra,
        )

    try:
        try:
            respuesta = _llamar(con_effort=True)
        except anthropic.BadRequestError as exc:
            if "effort" not in str(exc):
                raise
            respuesta = _llamar(con_effort=False)
    except anthropic.APIStatusError as exc:
        raise ErrorResumen(f"La API respondió {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise ErrorResumen("No hubo conexión con la API de Claude.") from exc

    if respuesta.stop_reason == "refusal":
        raise ErrorResumen("El modelo declinó generar este tema.")

    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    if not texto:
        raise ErrorResumen("La respuesta vino vacía.")
    try:
        return json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ErrorResumen(f"La respuesta no era JSON válido: {exc}") from exc


def costo_estimado(modelo: str, papers_por_dia: int = 10) -> str:
    """Texto para la pantalla de configuración."""
    precios = PRECIOS.get(modelo)
    if not precios:
        return "modelo sin precio en tabla"
    p_in, p_out = precios
    # Medido con los prompts reales: ~1.4k tokens de entrada, ~700 de salida.
    tok_in = 1400 * papers_por_dia
    tok_out = 700 * papers_por_dia
    dia = tok_in / 1e6 * p_in + tok_out / 1e6 * p_out
    return f"~{dia:.2f} USD/día, ~{dia * 30:.2f} USD/mes con {papers_por_dia} papers al día"
