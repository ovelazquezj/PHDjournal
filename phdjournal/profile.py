"""Perfil de temas de investigacion: el ejemplo de fabrica.

Este archivo es la **base**, no la verdad. Define un perfil de ejemplo,
NLP en el borde, con diez temas y su vocabulario. Cualquiera que clone el
proyecto puede usarlo tal cual, editarlo desde la app o reemplazarlo entero
por el suyo.

Un tema agrupa el vocabulario de un area y decide tres cosas:

* si un paper **entra** al feed (la puerta),
* cuanto **pesa** en la relevancia,
* que **consultas** se lanzan a las fuentes.

Los cambios del usuario NO se escriben aqui. Van a ``data/temas.json``, que se
aplica encima de esta base (ver ``temas.py``). Asi, cuando la base mejora en
una actualizacion, esas mejoras llegan sin pisar los ajustes propios.

Perfil de ejemplo: **NLP en el borde**. La interseccion D1 x D3 es el centro
de gravedad y el resto orbita alrededor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Capa 1: DOMINIOS
# ---------------------------------------------------------------------------

NUCLEO = "nucleo"      # definen la especialidad, abren la puerta por sí solos
PUENTE = "puente"      # areas limitrofes propias, abren la puerta por si solas
SOPORTE = "soporte"    # metodología y contexto, NO abren la puerta solos


@dataclass(frozen=True)
class Dominio:
    clave: str
    nombre: str
    capa: str
    peso: float                      # multiplica lo que aporta a la relevancia
    terminos: dict[str, float] = field(default_factory=dict)


D1 = Dominio(
    "D1", "NLP", NUCLEO, 1.0,
    {
        "natural language processing": 3.0,
        "computational linguistics": 2.5,
        "language model": 2.0,
        "large language model": 2.0,
        "tokenization": 3.0,
        "tokenizer": 3.0,
        "subword": 3.0,
        "byte pair encoding": 3.0,
        "morphology": 2.5,
        "morphological": 2.5,
        "lemmatization": 2.5,
        "named entity recognition": 3.0,
        "entity linking": 2.5,
        "relation extraction": 2.5,
        "information extraction": 2.5,
        "dependency parsing": 2.5,
        "syntactic": 2.0,
        "semantic parsing": 2.5,
        "coreference": 2.5,
        "question answering": 2.5,
        "text classification": 2.0,
        "summarization": 2.0,
        "machine translation": 2.0,
        "multilingual": 2.5,
        "low-resource language": 3.0,
        "cross-lingual": 2.5,
        "spanish": 2.5,
        "word embedding": 2.5,
        "sentence embedding": 2.5,
        "contextual representation": 2.0,
        "transformer": 1.5,
        "attention mechanism": 1.5,
        "in-context learning": 2.0,
        "instruction tuning": 2.0,
        "prompt engineering": 1.5,
        "text generation": 2.0,
        "hallucination": 2.0,
        "perplexity": 2.0,
        "corpus": 1.5,
        "annotation": 1.5,
    },
)

D2 = Dominio(
    "D2", "Modelos pequeños y eficientes", NUCLEO, 1.0,
    {
        "small language model": 3.5,
        "slm": 2.0,
        "compact model": 2.5,
        "efficient inference": 3.0,
        "model compression": 3.0,
        "knowledge distillation": 3.0,
        "distillation": 2.5,
        "pruning": 3.0,
        "sparsity": 2.5,
        "quantization": 3.0,
        "quantisation": 3.0,
        "quantized": 3.0,
        "post-training quantization": 3.0,
        "int4": 3.0,
        "int8": 2.5,
        "4-bit": 3.0,
        "8-bit": 2.5,
        "ternary": 2.5,
        "binary neural network": 2.5,
        "gptq": 3.0,
        "awq": 3.0,
        "speculative decoding": 3.5,
        "early exit": 2.5,
        "mixture of experts": 2.5,
        "mixture-of-experts": 2.5,
        "state space model": 2.5,
        "mamba": 2.5,
        "linear attention": 2.5,
        "kv cache": 3.0,
        "key-value cache": 3.0,
        "lora": 2.0,
        "parameter-efficient": 2.5,
        "flash attention": 2.0,
        "scaling law": 2.5,
        "inverse scaling": 3.0,
        "inverted scaling": 3.0,
        "parameter count": 1.5,
        "model size": 1.5,
    },
)

D3 = Dominio(
    "D3", "Inferencia en el borde", NUCLEO, 1.0,
    {
        "edge computing": 3.0,
        "edge device": 3.0,
        "edge devices": 3.0,
        "edge inference": 3.5,
        "edge hardware": 3.5,
        "edge ai": 3.0,
        "edge deployment": 3.0,
        "at the edge": 2.5,
        "on-device": 3.0,
        "on device": 3.0,
        "embedded device": 3.0,
        "embedded system": 2.5,
        "embedded hardware": 3.0,
        "microcontroller": 3.0,
        "tinyml": 3.5,
        "single-board computer": 3.0,
        "raspberry pi": 3.0,
        "jetson": 3.0,
        "esp32": 3.0,
        "cortex-m": 3.0,
        "cortex-a": 2.5,
        "risc-v": 2.5,
        "npu": 2.5,
        "neural processing unit": 2.5,
        "accelerator": 2.0,
        "system on chip": 2.0,
        "llama.cpp": 3.5,
        "gguf": 3.5,
        "onnx runtime": 2.5,
        "tensorrt": 2.5,
        "tflite": 3.0,
        "tensorflow lite": 3.0,
        "resource-constrained": 3.0,
        "resource constrained": 3.0,
        "limited-resource": 2.5,
        "low-power": 3.0,
        "low power": 3.0,
        "energy efficiency": 2.5,
        "energy consumption": 2.5,
        "memory footprint": 2.5,
        "inference latency": 3.0,
        "throughput": 1.5,
        "battery": 2.0,
        "offline": 2.5,
        "disconnected": 2.5,
        "air-gapped": 2.5,
        "intermittent connectivity": 2.5,
    },
)

D10 = Dominio(
    "D10", "Habla en el borde", NUCLEO, 1.0,
    {
        "speech recognition": 3.0,
        "automatic speech recognition": 3.5,
        "asr": 2.0,
        "speech-to-text": 3.0,
        "text-to-speech": 3.0,
        "speech synthesis": 3.0,
        "tts": 2.0,
        "voice assistant": 2.5,
        "keyword spotting": 3.0,
        "wake word": 3.0,
        "voice activity detection": 3.0,
        "speaker recognition": 2.5,
        "speaker verification": 2.5,
        "speaker diarization": 2.5,
        "whisper": 2.5,
        "streaming asr": 3.5,
        "phoneme": 2.5,
        "prosody": 2.5,
        "acoustic model": 2.5,
        "audio classification": 2.0,
        "spoken language understanding": 3.0,
        "voice interface": 2.5,
        "conversational agent": 2.0,
    },
)

D4 = Dominio(
    "D4", "Representación de conocimiento", PUENTE, 0.9,
    {
        "knowledge graph": 3.0,
        "ontology": 2.5,
        "ontologies": 2.5,
        "semantic web": 2.5,
        "rdf": 2.5,
        "sparql": 2.5,
        "triple store": 2.5,
        "knowledge base": 2.5,
        "entity resolution": 2.0,
        "graphrag": 3.5,
        "graph retrieval": 3.0,
        "retrieval-augmented generation": 3.0,
        "retrieval augmented": 3.0,
        "kg-augmented": 3.5,
        "vector search": 2.5,
        "dense retrieval": 2.5,
        "reranking": 2.0,
        "graph neural network": 2.0,
        "symbolic reasoning": 2.5,
        "neuro-symbolic": 3.0,
        "gazetteer": 2.5,
        "geospatial": 2.5,
        "geoparsing": 3.0,
        "toponym": 2.5,
    },
)

D5 = Dominio(
    "D5", "Sistemas de datos y almacenamiento", PUENTE, 0.9,
    {
        "data independence": 3.5,
        "learned index": 3.5,
        "index structure": 2.5,
        "physical design": 2.5,
        "storage engine": 2.5,
        "storage layout": 3.0,
        "query optimization": 2.0,
        "database architecture": 2.5,
        "embedded database": 3.0,
        "key-value store": 2.5,
        "lsm-tree": 2.5,
        "vector database": 2.5,
        "hnsw": 2.5,
        "schema evolution": 2.5,
        "concurrency control": 2.0,
        "file system": 2.5,
        "filesystem": 2.5,
        "nvme": 2.5,
        "flash storage": 2.5,
        "page cache": 2.5,
        "memory mapping": 2.0,
        "deterministic latency": 3.5,
        "tail latency": 3.0,
        "latency predictability": 3.5,
        "predictability": 2.0,
        "worst-case execution": 2.5,
        "real-time": 1.5,
    },
)

D6 = Dominio(
    "D6", "Evaluación y reproducibilidad", SOPORTE, 0.5,
    {
        "benchmark": 2.0,
        "evaluation framework": 2.5,
        "evaluation suite": 2.5,
        "benchmark contamination": 3.0,
        "data contamination": 3.0,
        "reproducibility": 2.5,
        "replication": 2.0,
        "pre-registration": 2.5,
        "ablation study": 2.0,
        "llm-as-a-judge": 2.5,
        "human evaluation": 2.0,
        "statistical significance": 2.0,
        "error analysis": 1.5,
        "leaderboard": 2.0,
    },
)

D7 = Dominio(
    "D7", "Cómputo paralelo y distribuido", SOPORTE, 0.5,
    {
        "distributed inference": 3.0,
        "model parallelism": 2.5,
        "pipeline parallelism": 2.5,
        "tensor parallelism": 2.5,
        "sharding": 2.0,
        "offloading": 2.5,
        "compute cluster": 2.0,
        "beowulf": 3.0,
        "mpi": 2.0,
        "federated learning": 2.0,
        "split computing": 3.0,
        "collaborative inference": 3.0,
        "edge-cloud": 2.5,
        "heterogeneous computing": 2.5,
    },
)

D8 = Dominio(
    "D8", "Fundamentos lingüísticos y cognitivos", SOPORTE, 0.5,
    {
        "psycholinguistic": 2.5,
        "cognitive science": 2.0,
        "language acquisition": 2.5,
        "compositionality": 2.5,
        "grounding": 2.5,
        "grounded language": 3.0,
        "embodied": 2.0,
        "neuroscience of language": 3.0,
        "brain decoding": 2.0,
        "distributional semantics": 2.5,
        "lexical semantics": 2.5,
        "pragmatics": 2.0,
        "discourse": 1.5,
    },
)

D9 = Dominio(
    "D9", "Ética, seguridad y gobernanza", SOPORTE, 0.5,
    {
        "on-device privacy": 3.0,
        "differential privacy": 2.0,
        "privacy-preserving": 2.5,
        "watermarking": 2.5,
        "content provenance": 2.5,
        "ai disclosure": 3.0,
        "model card": 2.0,
        "ai governance": 2.0,
        "ai act": 2.5,
        "prompt injection": 2.5,
        "jailbreak": 2.0,
        "adversarial attack": 1.5,
        "data sovereignty": 2.5,
    },
)

DOMINIOS: dict[str, Dominio] = {
    d.clave: d for d in (D1, D2, D3, D10, D4, D5, D6, D7, D8, D9)
}

# Un dominio se considera "detectado" a partir de este puntaje. Con el título
# valiendo el triple, un término fuerte en el título ya basta.
UMBRAL_DOMINIO = 3.0

# Qué dominios abren la puerta por sí solos.
#
# La regla de este perfil de ejemplo es: **tiene que haber lenguaje**, o ser de
# un área limítrofe propia. En "NLP en el borde" el borde es el *escenario* y
# el lenguaje es el *tema*.
#
# Ni D3 ni D2 abren solos, y las dos exclusiones costaron una corrida real cada
# una:
#
# * **D3 (borde)** dejaba entrar cualquier TinyML. Se colaron dos papers de
#   reconocimiento de actividad humana con acelerómetros: mismo hardware, otro
#   problema.
# * **D2 (eficiencia)** es peor de lo que parece, porque sus términos son
#   genéricos. "quantization", "distillation" y "pruning" los usa cualquier red
#   neuronal pequeña. Con D2 abriendo entraron clasificación de tráfico de red,
#   autenticación LoRaWAN y modelos hiperespectrales.
#
# Los dos siguen pesando mucho cuando acompañan a un dominio de tema, que es
# justo la intersección que interesa: D1 x D3 es "NLP en Edge".
#
# No hace falta listar D2 aquí para que entre un paper de SLM: "small language
# model" contiene "language model", que es término de D1.
#
# D4 y D5 sí abren solos: en este perfil, grafos de conocimiento y sistemas de
# datos son línea propia del investigador, y ahí el lenguaje puede no aparecer,
# como en un paper de learned index.
DOMINIOS_QUE_ABREN = {"D1", "D10", "D4", "D5"}


# ---------------------------------------------------------------------------
# NOTA: aquí vivía una "capa 2" con los papers de la tesis del autor original
# (P1..P4), con sus títulos y su estado de redacción. Era un error de diseño:
# publicaba la agenda de investigación de una persona junto con la herramienta,
# y obligaba a tocar el código fuente para cambiar algo que es puro dato.
#
# Esa capa ahora es `trabajos.py`, configurable desde la app y guardada en
# `data/trabajos.json`, que no se versiona.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Penalizaciones y veto
# ---------------------------------------------------------------------------

PENALIZACIONES: dict[str, float] = {
    # Visión por computadora: fuera por decisión explícita del usuario.
    # OJO: no se penaliza "multimodal" ni "vision-language", porque un VLM
    # pequeño corriendo en el borde sí es de este campo.
    "object detection": 2.5,
    "image segmentation": 2.5,
    "image classification": 2.0,
    "semantic segmentation": 2.5,
    "point cloud": 2.5,
    "optical flow": 3.0,
    "super-resolution": 2.5,
    "face recognition": 2.5,
    "facial": 2.5,
    "pose estimation": 2.5,
    "video surveillance": 3.0,
    "remote sensing": 2.5,
    "hyperspectral": 3.0,
    "medical imaging": 3.0,
    "histology": 3.0,
    "radiology": 3.0,

    # Otra liga: entrenamiento a gran escala en centro de datos
    "trillion parameter": 2.5,
    "pretraining corpus": 1.5,
    "h100": 2.0,
    "a100 cluster": 2.0,
    "datacenter scale": 2.0,

    # Aplicaciones de borde sin lenguaje: comparten el hardware, no el tema
    "human activity recognition": 3.0,
    "gesture recognition": 3.0,
    "wearable sensor": 2.5,
    "accelerometer": 2.5,
    "imu": 2.0,
    "predictive maintenance": 2.5,
    "structural health": 3.0,

    # Otros dominios que comparten vocabulario sin compartir el problema
    "clinical": 2.5,
    "clinical decision": 2.5,
    "drug discovery": 2.5,
    "patient": 2.0,
    "biomedical": 2.0,
    "protein": 2.5,
    "cultural heritage": 3.0,
    "humanities": 3.0,
    "ideological": 3.0,
    "curriculum": 2.0,
    "social media": 2.0,
    "recommender system": 1.5,
    "blockchain": 2.0,
    "stock market": 3.0,
    "agriculture": 2.0,
}

UMBRAL_VETO = 3.0


# ---------------------------------------------------------------------------
# Consultas por fuente
# ---------------------------------------------------------------------------

ARXIV_CATEGORIAS = [
    "cs.CL",   # computación y lenguaje
    "cs.AI", "cs.LG",
    "cs.DB",   # bases de datos
    "cs.DC",   # distribuido
    "cs.AR",   # arquitectura
    "cs.IR",   # recuperación
    "cs.SD",   # sonido
    "eess.AS",  # habla y audio
]

# Las consultas van POR TEMA a propósito: apagar un tema en la configuración
# también deja de buscarlo, no solo de puntuarlo. Antes eran dos listas
# globales y un tema apagado seguía gastando peticiones.
ARXIV_POR_DOMINIO: dict[str, list[str]] = {
    "D1": [
        'abs:"tokenization" OR abs:"subword" OR abs:"morphological segmentation"',
        'abs:"named entity recognition" OR abs:"relation extraction"',
        'abs:"low-resource language" OR abs:"cross-lingual transfer"',
        'abs:"multilingual" AND (abs:"efficient" OR abs:"compact")',
    ],
    "D2": [
        'abs:"small language model" AND (abs:"edge" OR abs:"on-device")',
        'abs:"quantization" AND abs:"language model"',
        'abs:"speculative decoding" OR abs:"early exit" OR abs:"KV cache"',
        'abs:"knowledge distillation" AND abs:"language model"',
        'abs:"pruning" OR abs:"model compression" OR abs:"sparsity"',
        'abs:"llama.cpp" OR abs:"GGUF" OR abs:"int4 quantization"',
    ],
    "D3": [
        'abs:"on-device" AND abs:"language model"',
        'abs:"language model" AND (abs:"microcontroller" OR abs:"embedded")',
        'abs:"tinyML" OR (abs:"microcontroller" AND abs:"neural")',
        'abs:"edge inference" AND (abs:"latency" OR abs:"energy")',
        'abs:"RISC-V" OR abs:"NPU" AND abs:"inference"',
    ],
    "D10": [
        'abs:"speech recognition" AND (abs:"edge" OR abs:"on-device" OR abs:"streaming")',
        'abs:"text-to-speech" AND (abs:"efficient" OR abs:"on-device" OR abs:"lightweight")',
        'abs:"keyword spotting" OR abs:"wake word" OR abs:"voice activity detection"',
    ],
    "D4": [
        'abs:"knowledge graph" AND (abs:"language model" OR abs:"LLM")',
        'abs:"GraphRAG" OR abs:"graph retrieval-augmented"',
        'abs:"retrieval-augmented generation" AND abs:"edge"',
        'abs:"geospatial" AND (abs:"question answering" OR abs:"named entity")',
    ],
    "D5": [
        'abs:"learned index" OR abs:"data independence"',
        'abs:"tail latency" OR abs:"deterministic latency"',
    ],
    "D6": ['abs:"benchmark contamination" OR abs:"data contamination"'],
    "D7": ['abs:"split computing" OR abs:"collaborative inference"'],
    "D8": ['abs:"grounded language" OR abs:"distributional semantics"'],
    "D9": ['abs:"prompt injection" OR abs:"on-device privacy"'],
}

TEXTO_POR_DOMINIO: dict[str, list[str]] = {
    "D1": [
        "subword tokenization morphology multilingual",
        "named entity recognition low resource language",
        "cross-lingual transfer compact model",
    ],
    "D2": [
        "small language model edge inference",
        "on-device language model quantization",
        "speculative decoding efficient inference",
        "knowledge distillation small language model",
        "model compression pruning sparsity language",
    ],
    "D3": [
        "language model microcontroller embedded",
        "tinyML microcontroller neural network",
        "edge AI energy efficient inference",
    ],
    "D10": [
        "streaming speech recognition on-device",
        "text to speech lightweight embedded",
        "keyword spotting wake word microcontroller",
    ],
    "D4": [
        "knowledge graph augmented language model",
        "graph retrieval augmented generation",
        "offline question answering knowledge graph",
        "geospatial named entity recognition question answering",
    ],
    "D5": [
        "learned index data independence storage",
        "deterministic latency edge inference predictability",
    ],
    "D6": ["benchmark contamination language model evaluation"],
    "D7": ["split computing edge cloud collaborative inference"],
    "D8": ["grounded language distributional semantics"],
    "D9": ["on-device privacy language model"],
}
