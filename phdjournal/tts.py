"""Síntesis de voz.

Dos motores:

* ``edge``: voces neuronales de Microsoft vía ``edge-tts``. Gratis, requieren
  conexión. Suenan bien en español de México, que es lo que importa cuando vas
  a escuchar diez resúmenes seguidos.
* ``sapi``: SAPI5 local vía ``pyttsx3``. Funciona sin conexión, suena peor.
  Es el respaldo automático cuando ``edge`` falla.

El audio se cachea por paper: si ya generaste el audio de un resumen, no se
vuelve a sintetizar aunque reabras la ficha.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

VOCES_SUGERIDAS = [
    ("es-MX-JorgeNeural", "México, masculina"),
    ("es-MX-DaliaNeural", "México, femenina"),
    ("es-ES-AlvaroNeural", "España, masculina"),
    ("es-ES-ElviraNeural", "España, femenina"),
    ("es-AR-TomasNeural", "Argentina, masculina"),
    ("es-CO-GonzaloNeural", "Colombia, masculina"),
]

# Cosas que se leen fatal en voz alta.
_URL = re.compile(r"https?://\S+")
_DOI = re.compile(r"\b10\.\d{4,9}/\S+\b")
_CITA = re.compile(r"\[\d+(?:,\s*\d+)*\]")
_ESPACIOS = re.compile(r"\s+")

_SIGLAS = {
    "SLM": "ese ele eme",
    "KG": "ka ge",
    "LLM": "ele ele eme",
    "RAG": "rag",
    "QA": "cu a",
    "NER": "ner",
    "IoT": "i o te",
    "GPU": "ge pe u",
    "CPU": "ce pe u",
    "INT4": "int cuatro",
    "INT8": "int ocho",
    "GGUF": "ge ge u efe",
    "NVMe": "ene ve eme e",
    "RPi": "erre pi",
}


def limpiar_para_voz(texto: str) -> str:
    """Quita lo que no se puede escuchar y deletrea las siglas duras."""
    texto = _URL.sub(" ", texto)
    texto = _DOI.sub(" ", texto)
    texto = _CITA.sub(" ", texto)
    for sigla, lectura in _SIGLAS.items():
        texto = re.sub(rf"\b{re.escape(sigla)}\b", lectura, texto)
    texto = texto.replace("—", ", ").replace("–", ", ")
    return _ESPACIOS.sub(" ", texto).strip()


def ruta_audio(dir_audio: Path, clave: str, voz: str, motor: str) -> Path:
    h = hashlib.sha1(f"{clave}|{voz}|{motor}".encode("utf-8")).hexdigest()[:16]
    ext = "mp3" if motor == "edge" else "wav"
    return dir_audio / f"{h}.{ext}"


# ---------------------------------------------------------------------------
# edge-tts
# ---------------------------------------------------------------------------

def _sintetizar_edge(texto: str, destino: Path, voz: str, velocidad: str, volumen: int) -> None:
    import edge_tts

    async def _correr() -> None:
        com = edge_tts.Communicate(
            texto,
            voice=voz,
            rate=velocidad or "+0%",
            volume=f"{max(0, min(100, volumen)) - 100:+d}%",
        )
        await com.save(str(destino))

    # edge-tts es asíncrono; se corre en un bucle propio dentro de este hilo.
    bucle = asyncio.new_event_loop()
    try:
        bucle.run_until_complete(_correr())
    finally:
        bucle.close()


# ---------------------------------------------------------------------------
# SAPI5 local
# ---------------------------------------------------------------------------

_bloqueo_sapi = threading.Lock()


def _sintetizar_sapi(texto: str, destino: Path, velocidad: str, volumen: int) -> None:
    import pyttsx3

    # pyttsx3 no es seguro entre hilos; se serializa.
    with _bloqueo_sapi:
        motor = pyttsx3.init()
        try:
            # velocidad viene como '+10%' o '-20%'; SAPI usa palabras por minuto.
            base = motor.getProperty("rate") or 200
            try:
                delta = int(str(velocidad).replace("%", "").replace("+", "") or 0)
            except ValueError:
                delta = 0
            motor.setProperty("rate", int(base * (1 + delta / 100.0)))
            motor.setProperty("volume", max(0.0, min(1.0, volumen / 100.0)))

            for voz in motor.getProperty("voices") or []:
                if "spanish" in (voz.name or "").lower() or "es-" in (voz.id or "").lower():
                    motor.setProperty("voice", voz.id)
                    break

            motor.save_to_file(texto, str(destino))
            motor.runAndWait()
        finally:
            try:
                motor.stop()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def sintetizar(
    texto: str,
    clave_cache: str,
    dir_audio: Path,
    motor: str = "edge",
    voz: str = "es-MX-JorgeNeural",
    velocidad: str = "+0%",
    volumen: int = 80,
    forzar: bool = False,
) -> tuple[Path, str]:
    """Genera (o reutiliza) el audio. Devuelve (ruta, motor realmente usado)."""
    texto = limpiar_para_voz(texto)
    if not texto:
        raise ValueError("No hay texto que sintetizar")

    dir_audio.mkdir(parents=True, exist_ok=True)

    if motor == "edge":
        destino = ruta_audio(dir_audio, clave_cache, voz, "edge")
        if destino.exists() and destino.stat().st_size > 1024 and not forzar:
            return destino, "edge"
        try:
            _sintetizar_edge(texto, destino, voz, velocidad, volumen)
            if destino.exists() and destino.stat().st_size > 1024:
                return destino, "edge"
            raise RuntimeError("edge-tts produjo un archivo vacío")
        except Exception as exc:
            log.warning("edge-tts falló (%s), se cae a SAPI local", exc)
            destino.unlink(missing_ok=True)

    destino = ruta_audio(dir_audio, clave_cache, "sapi", "sapi")
    if destino.exists() and destino.stat().st_size > 1024 and not forzar:
        return destino, "sapi"
    _sintetizar_sapi(texto, destino, velocidad, volumen)
    if not destino.exists() or destino.stat().st_size <= 1024:
        raise RuntimeError("No se pudo sintetizar el audio con ningún motor")
    return destino, "sapi"
