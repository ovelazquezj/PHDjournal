# PHDjournal

**[English](README.md) · [Español](README.es.md)**

A desktop research feed that finds new papers in your field twice a day,
summarises them in your language, and reads the summaries out loud.

It lives in the Windows system tray. At the times you choose it queries four
open sources, scores everything it finds against your topics, keeps the best,
summarises them with Claude, and raises a notification. Clicking the
notification opens the reader.

> Ships with an example profile for **NLP on the edge**. On first launch it
> asks whether to use it, generate one for your own field, or start empty.

---

## What it does

| | |
|---|---|
| **Finds** | arXiv, OpenAlex, Semantic Scholar and Crossref, twice daily |
| **Ranks** | A hybrid score you control: relevance, venue quality, citation velocity, recency |
| **Summarises** | Structured summaries via the Claude API, in your language |
| **Speaks** | Neural text to speech, or an offline fallback |
| **Reads** | Downloads open-access PDFs, splits them into sections, can summarise and read each one |
| **Files** | Exports to Zotero with the summary as a note and the PDF attached |
| **Remembers** | Never shows you the same paper twice |

---

## Install

Requires Windows and Python 3.11 or newer.

```powershell
git clone https://github.com/ovelazquezj/PHDjournal.git
cd PHDjournal
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -CrearEntorno
```

`-CrearEntorno` creates a virtual environment and installs the dependencies.
Drop it if you already have one; the installer finds it on its own, looking at
`.venv`, an active conda or virtualenv, a conda environment named
`phdjournal`, and finally the `PATH`. You can also point at it directly with
`-Python "C:\path\to\pythonw.exe"`.

The installer adds a Start Menu shortcut, an autostart entry, and two backup
scheduled tasks that wake the app if you closed it.

### Two things to set up

1. **A Claude API key**, in Settings, Claude tab. Without it the app still
   searches and ranks, it just shows the original abstracts instead of
   summaries, and there is nothing to listen to. See
   [Claude account](#claude-account) below.
2. **A Zotero collection**, if you want the export. The Zotero connector
   cannot create collections, so make it once by hand and name it in
   Settings, Zotero tab.

### Claude account

The app calls the **Claude API** directly, so it needs an API key from the
Claude Console. A Claude.ai subscription (Pro, Max, Team) **does not**
include API access; the two are billed separately.

1. Create an account at [platform.claude.com](https://platform.claude.com)
   (the Claude Console).
2. Under **Billing**, add a payment method and buy prepaid credits. The API
   refuses requests while the balance is zero, even with a valid key.
3. Under **API keys**, create a key. It starts with `sk-ant-` and is shown
   only once; copy it then.
4. In the app: Settings, Claude tab. Paste the key, press **Probar clave**
   (test key), pick a model, save.

What uses Claude, and when:

| Feature | Calls |
|---|---|
| Paper summaries | One per paper kept, on every run |
| Section summaries | Only when you press *Resumir* in the PDF reader |
| Topic assistant | Only when you ask it to propose a topic |

Approximate cost of the daily summaries, with the default 10 papers per run
and two runs a day (the Claude tab shows the same estimate for your own
settings):

| Model | Per day | Per month |
|---|---|---|
| `claude-haiku-4-5`, cheapest | ~0.10 USD | ~3 USD |
| `claude-sonnet-5`, balanced | ~0.20 USD | ~6 USD |
| `claude-opus-5`, most capable (default) | ~0.49 USD | ~15 USD |

Section summaries and the topic assistant add on top, only when you use them.
Setting a monthly spend limit in the Console, under **Limits**, is a good
idea.

The key is stored encrypted with Windows DPAPI in `data/config.json`, tied to
your Windows account; copied to another machine it cannot be decrypted. If the
`ANTHROPIC_API_KEY` environment variable is set, it takes precedence over the
saved key, which is handy for testing without touching your settings.

---

## How it decides what to show you

### Topics

A topic is a named vocabulary. Each one decides three things: whether a paper
gets **in**, how much it **weighs**, and which **queries** get sent to the
sources. Turning a topic off also stops searching for it.

One rule matters more than the rest: **not every topic can let a paper in on
its own**. In the example profile, the edge-computing topic does not open the
gate, because edge is the *setting* and language is the *subject*. Without
that distinction, any TinyML paper qualifies. The same goes for the
efficiency topic, whose vocabulary (`quantization`, `distillation`, `pruning`)
belongs to every small neural network, not just language models.

Both exclusions were found by measurement, not theory. With the edge topic
opening, two human-activity-recognition papers came in. With the efficiency
topic opening, so did network traffic classification and hyperspectral models.

### Scoring

```
score = 0.60 relevance + 0.20 venue + 0.12 citations + 0.08 recency
```

All four weights are editable.

- **Relevance** sums the weights of matched terms across detected topics, with
  the title counting triple. Two hard filters: the topic gate above, and a
  veto for foreign domains that share vocabulary without sharing the problem.
- **Venue** comes from a curated table. Generic names and acronyms require an
  exact match, because substring matching once gave *Humanities and Social
  Sciences Communications* the score meant for the journal *Science*.
- **Citations** measure velocity, not the total. A month-old paper with three
  citations is moving faster than a four-year-old one with forty.
- **Recency** decays over days.

Every card explains why that paper showed up, component by component.

### Editing all of it

Settings, Topics tab. Turn topics on and off, change weights, edit terms one
by one, decide which ones open the gate, and create new topics.

**New topics with an assistant.** Describe a topic in one sentence and Claude
proposes the terms, weights and search queries. You review the list and drop
what does not belong. About fifteen seconds and well under a cent.

**Test bench.** *Test changes* re-ranks the candidates from the last run with
your edited profile and shows what would come in and what would drop out,
**without touching the network or spending anything**. It exists because the
gate was misconfigured twice during development and each mistake cost a real
run to discover.

### My works

Your own papers and projects in progress, so the app can tag each incoming
paper with the work of yours it touches. They **do not affect the score or the
search**, they only label, and having no label is a perfectly normal answer.

---

## Where your data lives

Everything personal stays in `data/`, which is never committed:

| File | What it holds |
|---|---|
| `config.json` | Settings. API keys inside are encrypted with Windows DPAPI, tied to your account |
| `temas.json` | Your topic changes, applied on top of the shipped profile |
| `trabajos.json` | Your own works |
| `phdjournal.sqlite` | Run history, summaries, reading state |
| `biblioteca/`, `audio/` | Downloaded PDFs and generated speech |

Topic edits are stored as a **diff**, not a replacement. If the shipped
profile improves in a later version, you get the improvement without losing
your adjustments.

---

## Academic integrity

Every summary is stored marked as AI-generated, with the model that produced
it. The note exported to Zotero carries an explicit warning not to cite that
text and to verify against the original.

---

## Usage

| Action | How |
|---|---|
| Open the reader | Start Menu, or double-click the tray icon |
| Search now | `Ctrl+B`, or the toolbar button |
| Listen to one summary | Select a paper, *Escuchar el resumen* |
| Listen to all of them | *Escuchar todos* |
| Read in full | *Leer completo* downloads the PDF and opens the section reader |
| Save to Zotero | *Marcar útil y enviar a Zotero* |
| Reload after a console run | `F5` |
| Help | `F1` |

From the console:

```powershell
python -m phdjournal --buscar              # one run, then exit
python -m phdjournal --resumir-faltantes   # backfill missing summaries
python -m phdjournal --minimizado          # start in the tray
```

Closing the window does not quit the app, it hides it. Quit from the tray
icon's menu.

---

## Layout

```
phdjournal/
  profile.py      shipped example topic profile
  temas.py        user overlay: merge, save, query generation
  trabajos.py     your own works
  ranking.py      hybrid scoring and the topic gate
  venues.py       venue quality table
  sources/        arxiv, openalex, semantic_scholar, crossref, dedup
  summarize.py    structured summaries via the Claude API
  tts.py          speech: edge-tts with a SAPI5 fallback
  zotero.py       local connector, launching, targeted saving, attachments
  pdf.py          PDF library and section splitting
  db.py           SQLite: history, state, Zotero queue
  scheduler.py    the two daily slots, with catch-up
  pipeline.py     a full run
  notify.py       native toast with a tray fallback
  ui/             window, card, PDF reader, settings, topics, tray, help
scripts/          instalar.ps1, desinstalar.ps1
```

The interface is in Spanish; the code and this document are the reference for
everything else.

---

## License

MIT. See [LICENSE](LICENSE).

Copyright © 2026 Omar Francisco Velazquez Juarez
