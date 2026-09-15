"""Configuración de PHDjournal.

La configuración vive en un JSON dentro de ``data/``. La clave de la API de
Claude NO se guarda en ese JSON en texto plano: se cifra con DPAPI de Windows,
que ata el secreto a la cuenta de usuario de Windows. Si alguien copia el
archivo a otra máquina o a otra cuenta, el blob no se puede descifrar.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:  # pywin32, presente en Windows
    import win32crypt  # type: ignore
except ImportError:  # pragma: no cover - fuera de Windows
    win32crypt = None  # type: ignore


RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
RUTA_CONFIG = DIR_DATOS / "config.json"

# Entropía adicional de DPAPI. No es un secreto, es un separador de dominio:
# impide que otro programa de la misma cuenta descifre este blob por accidente.
def _entropia(dominio: str) -> bytes:
    return f"PHDjournal/{dominio}/v1".encode("utf-8")


def _cifrar(valor: str, dominio: str) -> str:
    """Cifra con DPAPI y devuelve base64. Cadena vacía si no hay valor."""
    valor = (valor or "").strip()
    if not valor:
        return ""
    if win32crypt is None:
        raise RuntimeError(
            "pywin32 no está instalado; no se puede cifrar el secreto con DPAPI"
        )
    blob = win32crypt.CryptProtectData(
        valor.encode("utf-8"), "PHDjournal", _entropia(dominio), None, None, 0
    )
    return base64.b64encode(blob).decode("ascii")


def _descifrar(blob_b64: str, dominio: str) -> str:
    """Descifra. Devuelve cadena vacía si no hay, si falla o si es de otra cuenta."""
    if not blob_b64 or win32crypt is None:
        return ""
    try:
        blob = base64.b64decode(blob_b64)
        _descripcion, datos = win32crypt.CryptUnprotectData(
            blob, _entropia(dominio), None, None, 0
        )
        return datos.decode("utf-8")
    except Exception:
        return ""


@dataclass
class Config:
    """Todo lo que la pantalla de configuración puede tocar."""

    # --- Horarios de búsqueda -------------------------------------------
    horario_manana: str = "05:30"
    horario_tarde: str = "18:30"
    papers_por_corrida: int = 10

    # --- Ranking híbrido (opción D). Deben sumar 1.0 --------------------
    # Relevancia subida de 0.50 a 0.60 el 15 sep 2026: con la red abierta a
    # diez dominios entran ~1,300 candidatos por corrida y los puntajes salían
    # apretados (0.571 a 0.589 en una corrida real). El 0.10 se tomó de los
    # otros tres en proporción, para no alterar su orden relativo.
    peso_relevancia: float = 0.60
    peso_venue: float = 0.20
    peso_citas: float = 0.12
    peso_novedad: float = 0.08

    # --- Búsqueda --------------------------------------------------------
    ventana_dias: int = 21
    candidatos_por_fuente: int = 60
    fuentes_activas: list[str] = field(
        default_factory=lambda: ["arxiv", "openalex", "semantic_scholar", "crossref"]
    )
    # Correo para el "polite pool" de OpenAlex y Crossref. Les da prioridad de
    # cola. No se manda a ningún otro lado.
    email_contacto: str = ""
    # Clave gratuita de Semantic Scholar. Opcional: sin ella la fuente suele
    # responder 429 y se salta sola.
    clave_s2_cifrada: str = ""

    # --- Claude ----------------------------------------------------------
    modelo_claude: str = "claude-opus-5"
    clave_claude_cifrada: str = ""
    resumen_max_tokens: int = 2000
    # Un párrafo describiendo quién eres y qué investigas. Se inyecta en el
    # prompt para que los resúmenes respondan "por qué te importa a TI".
    # Si queda vacío, la app lo arma con los temas activos y los trabajos
    # declarados, así que funciona recién instalada sin escribir nada.
    perfil_investigador: str = ""

    # --- Voz --------------------------------------------------------------
    motor_voz: str = "edge"  # "edge" (neuronal, en línea) o "sapi" (local)
    voz: str = "es-MX-JorgeNeural"
    velocidad_voz: str = "+0%"
    volumen_voz: int = 80

    # --- Zotero -----------------------------------------------------------
    zotero_exe: str = r"C:\Program Files\Zotero\zotero.exe"
    zotero_datos: str = ""  # se autodetecta si queda vacío
    # Coleccion destino. Vacio como padre significa "en la raiz de la
    # biblioteca". Cambialos a los tuyos en Configuracion, pestana Zotero.
    zotero_coleccion_padre: str = ""
    zotero_subcoleccion: str = "PHDjournal"
    zotero_auto_lanzar: bool = True
    zotero_puerto: int = 23119

    # --- Otros -------------------------------------------------------------
    # Falso hasta que el asistente de bienvenida corre una vez. Evita heredar
    # el campo de investigacion de otra persona sin darse cuenta.
    primer_arranque_hecho: bool = False
    arranque_con_windows: bool = True
    notificaciones: bool = True
    idioma_resumen: str = "es"

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    @classmethod
    def cargar(cls) -> "Config":
        if not RUTA_CONFIG.exists():
            cfg = cls()
            cfg.guardar()
            return cfg
        datos = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
        conocidos = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in datos.items() if k in conocidos})

    def guardar(self) -> None:
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        tmp = RUTA_CONFIG.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(RUTA_CONFIG)

    # ------------------------------------------------------------------
    # Clave de la API, cifrada con DPAPI
    # ------------------------------------------------------------------

    def set_clave_claude(self, clave: str) -> None:
        """Cifra y guarda la clave. Una cadena vacía la borra."""
        self.clave_claude_cifrada = _cifrar(clave, "claude-api-key")

    def get_clave_claude(self) -> str:
        """Descifra la clave.

        Si la variable de entorno ANTHROPIC_API_KEY está puesta, gana: sirve
        para correr la app en modo prueba sin tocar la configuración guardada.
        """
        del_entorno = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if del_entorno:
            return del_entorno
        return _descifrar(self.clave_claude_cifrada, "claude-api-key")

    def tiene_clave(self) -> bool:
        return bool(self.get_clave_claude())

    def set_clave_s2(self, clave: str) -> None:
        """Clave opcional de Semantic Scholar, solo sube el límite de peticiones."""
        self.clave_s2_cifrada = _cifrar(clave, "semantic-scholar-key")

    def get_clave_s2(self) -> str:
        return _descifrar(self.clave_s2_cifrada, "semantic-scholar-key")

    # ------------------------------------------------------------------
    # Derivados
    # ------------------------------------------------------------------

    @property
    def dir_biblioteca(self) -> Path:
        ruta = DIR_DATOS / "biblioteca"
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    @property
    def dir_audio(self) -> Path:
        ruta = DIR_DATOS / "audio"
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    def pesos_normalizados(self) -> dict[str, float]:
        """Devuelve los cuatro pesos sumando exactamente 1.0."""
        crudo = {
            "relevancia": max(0.0, self.peso_relevancia),
            "venue": max(0.0, self.peso_venue),
            "citas": max(0.0, self.peso_citas),
            "novedad": max(0.0, self.peso_novedad),
        }
        total = sum(crudo.values())
        if total <= 0:
            return {"relevancia": 0.5, "venue": 0.25, "citas": 0.15, "novedad": 0.10}
        return {k: v / total for k, v in crudo.items()}
