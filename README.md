# N.E.X.U.S. — AI Personal Assistant

[![CI](https://github.com/Barbarel001/nexus/actions/workflows/ci.yml/badge.svg)](https://github.com/Barbarel001/nexus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

A personal AI assistant built in **Python** on top of the **Claude API (Anthropic)**.
It is a real **tool-using agent**: it holds a conversation, **remembers things across
sessions**, tracks real freelance job listings, searches the web, and can read/write
files and run commands on your machine (always with your confirmation).

It ships with **two interfaces**: a classic **terminal** client and a **web HUD**
(browser) with streaming responses, conversation history, and voice in/out.

> This is what's actually behind the "AI that does everything" hype: a language model
> wired to a set of tools through an agentic loop. A copilot, not a magic money machine.

---

## Why this project

It's a compact but complete example of an **agentic application**, demonstrating:

- **Agentic tool-use loop** — the model decides which tool to call, the app executes
  it, feeds the result back, and repeats until the task is done.
- **Function calling / tool definitions** against the Anthropic API.
- **Persistent memory** across sessions (long-term notes the agent writes itself).
- **Streaming** responses over **Server-Sent Events (SSE)** in the web UI.
- **Adaptive thinking**, safe-by-default permissions, and a clean separation between
  the terminal (full tools) and web (read-only tools) surfaces.

## Features

| Area | What it does |
|---|---|
| 🧠 **Persistent memory** | Remembers your name, preferences, goals and project facts between runs (`memoria.json`). |
| 🛠️ **Tool use** | `recordar`, `rastrear_ofertas`, `web_search`, `run_command`, `read_file`, `write_file`, `list_directory`. |
| 💼 **Job tracker** | Pulls **real** remote/freelance listings from Remotive and RemoteOK by keyword. |
| 🌐 **Web HUD** | Flask + SSE streaming, sidebar with conversation history (open/delete), markdown rendering. |
| 🎙️ **Voice** | Text-to-speech (reads answers aloud) and speech-to-text (dictate by mic) via the Web Speech API. |
| 🖥️ **Terminal client** | Full agent with the complete tool set and an iteration safety cap per turn. |
| 🔒 **Safe by default** | Confirms before running commands or writing files; the web UI disables system-level tools entirely. |

## Architecture

```
nexus.py          → Terminal agent: agentic loop + tool dispatch + adaptive thinking
nexus_web.py      → Flask server: SSE streaming, conversation persistence, web-safe tools
web/index.html    → HUD front-end: streaming render, history sidebar, voice (TTS/STT)
memoria.json      → Long-term memory (git-ignored; personal)
conversaciones.json → Web chat history (git-ignored; personal)
```

The web layer **reuses** the agent logic and tool implementations from `nexus.py`,
exposing only the read-only tools (`recordar`, `rastrear_ofertas`, `read_file`,
`list_directory`) — `run_command` and `write_file` are disabled in the browser for safety.

## Tech stack

- **Python 3.9+** (developed on 3.12)
- **`anthropic`** SDK — Claude API, tool use, streaming, adaptive thinking
- **Flask** — web server and SSE endpoint
- Vanilla JS front-end + **Web Speech API** for voice

---

## Getting started

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Set your Anthropic API key** (get one at https://console.anthropic.com)
```bash
setx ANTHROPIC_API_KEY "sk-ant-..."   # Windows — reopen the terminal afterwards
# export ANTHROPIC_API_KEY="sk-ant-..."  # macOS / Linux
```

The key is read **only** from the environment variable — it is never stored in the code.

**3. Run it**
```bash
python nexus_web.py   # web HUD at http://127.0.0.1:5000 (recommended)
python nexus.py       # terminal client (full tool set)
```

## Example prompts

- "Track freelance jobs for Python and Telegram bots."
- "Remember that my rate is 20 USD/hour."
- "How much free RAM do I have right now?"
- "Search the web for the latest Godot 4 news and summarize it."

## Configuration

Edit the `CONFIGURACION` section in `nexus.py`:

| Variable | Purpose |
|---|---|
| `MODEL` | Claude model to use (`claude-opus-4-8` default; `sonnet`/`haiku` are cheaper) |
| `MAX_TOKENS` | Max length per response |
| `PEDIR_CONFIRMACION` | `False` runs commands without asking (⚠️ use with care) |

## Tests

The suite covers the pure logic without hitting the network or the Claude API
(job-listing parsing is tested with a mocked HTTP layer; memory and conversation
persistence with temp files):

```bash
pip install -r requirements-dev.txt
pytest
```

CI runs the full suite on every push via GitHub Actions.

## Security

Nexus can run commands and write files on your machine, so it **asks for confirmation**
before doing so. Read the command before approving. In the web UI those tools are
disabled entirely. Personal data (`memoria.json`, `conversaciones.json`) is git-ignored
and never published.

## Roadmap

- [x] Test suite (pytest) + CI (GitHub Actions)
- [x] Context-window trimming for long sessions
- [ ] More job sources (Workana, Upwork, r/forhire)
- [ ] In-browser confirmation modal for system actions
- [ ] Screenshots / demo GIF
- [ ] Persist full tool-use history in the web UI across reloads

---

*Built with the Claude API. UI text is in Spanish; the assistant converses in Spanish.*
