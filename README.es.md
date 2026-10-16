# PHDjournal

**[English](README.md) · [Español](README.es.md)**

Un lector de novedades científicas que busca papers de tu campo dos veces al
día, los resume en tu idioma y te lee los resúmenes en voz alta.

Vive en la bandeja de Windows. A las horas que fijes consulta cuatro fuentes
abiertas, puntúa todo lo que encuentra contra tus temas, se queda con los
mejores, los resume con Claude y te avisa con una notificación. Al hacer clic
en la notificación se abre el lector.

> Viene con un perfil de ejemplo de **NLP en el borde**. En el primer arranque
> te pregunta si quieres usarlo, generar uno para tu propio campo, o empezar
> vacío.

---

## Qué hace

| | |
|---|---|
| **Busca** | arXiv, OpenAlex, Semantic Scholar y Crossref, dos veces al día |
| **Ordena** | Un puntaje híbrido que tú controlas: relevancia, calidad del venue, velocidad de citas, novedad |
| **Resume** | Resúmenes estructurados con la API de Claude, en tu idioma |
| **Habla** | Voz neuronal, con respaldo local sin conexión |
| **Lee** | Descarga los PDF de acceso abierto, detecta las secciones, y puede resumir y leer cada una |
| **Archiva** | Exporta a Zotero con el resumen como nota y el PDF adjunto |
| **Recuerda** | Nunca te muestra dos veces el mismo paper |

---

## Instalación

Requiere Windows y Python 3.11 o superior.

```powershell
git clone https://github.com/ovelazquezj/PHDjournal.git
cd PHDjournal
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -CrearEntorno
```

`-CrearEntorno` crea un entorno virtual e instala las dependencias. Quítalo si
ya tienes uno: el instalador lo encuentra solo, buscando en `.venv`, en un
conda o virtualenv activo, en un entorno conda llamado `phdjournal`, y por
último en el `PATH`. También puedes señalarlo directo con
`-Python "C:\ruta\a\pythonw.exe"`.

El instalador crea el acceso directo del menú Inicio, el arranque automático y
dos tareas de respaldo que levantan la app si la cerraste.

### Dos cosas que hay que preparar

1. **Una clave de la API de Claude**, en Configuración, pestaña Claude. Sin
   ella la app igual busca y ordena, solo que muestra los abstracts originales
   en vez de resúmenes, y no hay nada que escuchar. Ver
   [Cuenta de Claude](#cuenta-de-claude) más abajo.
2. **Una colección de Zotero**, si quieres la exportación. El conector de
   Zotero no puede crear colecciones, así que se crea una vez a mano y se
   nombra en Configuración, pestaña Zotero.

### Cuenta de Claude

La app llama directo a la **API de Claude**, así que necesita una clave de la
Claude Console. Una suscripción de Claude.ai (Pro, Max, Team) **no** incluye
acceso a la API; se cobran por separado.

1. Crea una cuenta en [platform.claude.com](https://platform.claude.com)
   (la Claude Console).
2. En **Billing**, agrega un método de pago y compra créditos prepagados. Con
   saldo en cero la API rechaza las peticiones, aunque la clave sea válida.
3. En **API keys**, crea una clave. Empieza con `sk-ant-` y se muestra una
   sola vez: cópiala en ese momento.
4. En la app: Configuración, pestaña Claude. Pega la clave, pulsa **Probar
   clave**, elige un modelo y guarda.

Qué usa Claude, y cuándo:

| Función | Llamadas |
|---|---|
| Resúmenes de papers | Una por cada paper que se queda, en cada corrida |
| Resúmenes de secciones | Solo cuando pulsas *Resumir* en el lector de PDF |
| Asistente de temas | Solo cuando le pides que proponga un tema |

Costo aproximado de los resúmenes diarios, con los 10 papers por corrida de
fábrica y dos corridas al día (la pestaña Claude muestra la misma estimación
con tu configuración):

| Modelo | Por día | Por mes |
|---|---|---|
| `claude-haiku-4-5`, el más barato | ~0.10 USD | ~3 USD |
| `claude-sonnet-5`, equilibrado | ~0.20 USD | ~6 USD |
| `claude-opus-5`, el más capaz (por defecto) | ~0.49 USD | ~15 USD |

Los resúmenes de secciones y el asistente de temas se suman aparte, solo
cuando los usas. Conviene fijar un límite de gasto mensual en la Console, en
**Limits**.

La clave se guarda cifrada con DPAPI de Windows en `data/config.json`, atada a
tu cuenta de Windows; copiada a otra máquina no se puede descifrar. Si la
variable de entorno `ANTHROPIC_API_KEY` está puesta, tiene prioridad sobre la
clave guardada, lo que sirve para probar sin tocar tu configuración.

---

## Cómo decide qué mostrarte

### Temas

Un tema es un vocabulario con nombre. Cada uno decide tres cosas: si un paper
**entra**, cuánto **pesa**, y qué **consultas** se mandan a las fuentes.
Apagar un tema también deja de buscarlo.

Hay una regla que importa más que las demás: **no todos los temas pueden meter
un paper por sí solos**. En el perfil de ejemplo, el tema del borde no abre la
puerta, porque el borde es el *escenario* y el lenguaje es el *tema*. Sin esa
distinción entra cualquier TinyML. Lo mismo con el tema de eficiencia, cuyo
vocabulario (`quantization`, `distillation`, `pruning`) pertenece a cualquier
red neuronal pequeña, no solo a las de lenguaje.

Las dos exclusiones salieron de medir, no de teorizar. Con el tema del borde
abriendo entraron dos papers de reconocimiento de actividad humana con
acelerómetros. Con el de eficiencia abriendo entraron clasificación de tráfico
de red y modelos hiperespectrales.

### Puntaje

```
puntaje = 0.60 relevancia + 0.20 venue + 0.12 citas + 0.08 novedad
```

Los cuatro pesos son editables.

- **Relevancia**: suma los pesos de los términos encontrados en los temas
  detectados, con el título valiendo el triple. Dos filtros duros: la puerta
  de temas, y un veto para dominios ajenos que comparten vocabulario sin
  compartir el problema.
- **Venue**: tabla curada. Los nombres genéricos y los acrónimos exigen
  coincidencia exacta, porque la coincidencia por subcadena una vez le dio a
  *Humanities and Social Sciences Communications* el puntaje de la revista
  *Science*.
- **Citas**: velocidad, no total. Un paper de hace un mes con tres citas va
  más rápido que uno de hace cuatro años con cuarenta.
- **Novedad**: decae con los días.

Cada ficha explica por qué salió ese paper, componente por componente.

### Editarlo todo

Configuración, pestaña Temas. Encender y apagar temas, cambiar pesos, editar
términos uno a uno, decidir cuáles abren la puerta, y crear temas nuevos.

**Temas nuevos con asistente.** Describe un tema en una frase y Claude propone
los términos, los pesos y las consultas. Tú revisas la lista y quitas lo que
no encaja. Unos quince segundos y bastante menos de un centavo.

**Banco de pruebas.** *Probar cambios* rankea los candidatos de la última
corrida con tu perfil editado y enseña qué entraría y qué saldría, **sin tocar
la red y sin gastar nada**. Existe porque durante el desarrollo la puerta se
configuró mal dos veces y cada error costó una corrida real para descubrirlo.

### Mis trabajos

Tus propios papers y proyectos en curso, para que la app etiquete cada novedad
con el trabajo tuyo al que toca. **No influyen en el puntaje ni en la
búsqueda**, solo etiquetan, y quedarse sin etiqueta es perfectamente normal.

---

## Dónde vive tu información

Todo lo personal se queda en `data/`, que nunca se versiona:

| Archivo | Qué guarda |
|---|---|
| `config.json` | Configuración. Las claves de API van cifradas con DPAPI de Windows, atadas a tu cuenta |
| `temas.json` | Tus cambios de temas, aplicados encima del perfil de fábrica |
| `trabajos.json` | Tus trabajos propios |
| `phdjournal.sqlite` | Historial de corridas, resúmenes, estado de lectura |
| `biblioteca/`, `audio/` | PDF descargados y audio generado |

Los cambios de temas se guardan como **diferencial**, no como reemplazo. Si el
perfil de fábrica mejora en una versión posterior, recibes la mejora sin
perder tus ajustes.

---

## Integridad académica

Todo resumen se guarda marcado como generado por inteligencia artificial, con
el modelo que lo produjo. La nota que se exporta a Zotero lleva un aviso
explícito de no citar ese texto y verificar contra el original.

---

## Uso

| Acción | Cómo |
|---|---|
| Abrir el lector | Menú Inicio, o doble clic en el icono de la bandeja |
| Buscar ahora | `Ctrl+B`, o el botón de la barra |
| Escuchar un resumen | Selecciona el paper, *Escuchar el resumen* |
| Escuchar todos | *Escuchar todos* |
| Leer completo | *Leer completo* descarga el PDF y abre el lector por secciones |
| Guardar en Zotero | *Marcar útil y enviar a Zotero* |
| Recargar tras buscar por consola | `F5` |
| Ayuda | `F1` |

Desde la consola:

```powershell
python -m phdjournal --buscar              # una corrida y sale
python -m phdjournal --resumir-faltantes   # rellena resúmenes que falten
python -m phdjournal --minimizado          # arranca en la bandeja
```

Cerrar la ventana no cierra la app, la esconde. Para salir de verdad, menú del
icono de la bandeja.

---

## Estructura

```
phdjournal/
  profile.py      perfil de temas de ejemplo, el de fábrica
  temas.py        superposición del usuario: fusión, guardado, consultas
  trabajos.py     tus trabajos propios
  ranking.py      puntaje híbrido y puerta de temas
  venues.py       tabla de calidad de venues
  sources/        arxiv, openalex, semantic_scholar, crossref, deduplicación
  summarize.py    resúmenes estructurados con la API de Claude
  tts.py          voz: edge-tts con respaldo SAPI5
  zotero.py       conector local, lanzamiento, guardado dirigido, adjuntos
  pdf.py          biblioteca de PDF y partición en secciones
  db.py           SQLite: historial, estado, cola de Zotero
  scheduler.py    las dos franjas diarias, con recuperación
  pipeline.py     la corrida completa
  notify.py       toast nativo con respaldo a la bandeja
  ui/             ventana, ficha, lector de PDF, configuración, temas, bandeja, ayuda
scripts/          instalar.ps1, desinstalar.ps1
```

---

## Licencia

MIT. Ver [LICENSE](LICENSE).

Copyright © 2026 Omar Francisco Velazquez Juarez
