# DONNA client

The open-source voice client. Captures audio, extracts legal intents,
routes to the DONNA runtime or your self-hosted stack, plays back confirmation.

**Status:** v0.3 — full voice pipeline: audio capture + VAD + Whisper STT + TTS confirmation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  DONNA client (this repo, AGPLv3)                       │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────────┐│
│  │  Audio   │──►│  VAD     │──►│  Intent Extractor    ││
│  │  Capture │   │ (Silero) │   │  (LLM + prompts)     ││
│  └──────────┘   └──────────┘   └──────────┬───────────┘│
│                                            │            │
│  ┌─────────────────────────────────────────▼───────────┐│
│  │  Router                                             ││
│  │  ├── time-entry   → billing integration             ││
│  │  ├── task-delegate → task management integration    ││
│  │  └── clarify      → clarifying-question flow        ││
│  └─────────────────────────────────────────────────────┘│
│                                            │            │
│  ┌─────────────────────────────────────────▼───────────┐│
│  │  Local cache (SQLite) — offline-first               ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
                             │
                             ▼ (optional)
                  hosted runtime (domain TBD)
                  or self-hosted backend
```

---

## Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Audio capture | PyAudio / sounddevice | Cross-platform |
| Voice activity detection | webrtcvad | Local, lightweight C extension |
| Speech-to-text | OpenAI Whisper API or local openai-whisper | Pluggable via `STT_BACKEND` |
| Intent extraction | OpenAI-compatible API + voice-prompts/ | Prompts are open |
| TTS confirmation | OpenAI TTS (`tts-1`, voice `nova`) | Reads back what was logged |
| Local store | SQLite | Offline-first; syncs when online |
| Integrations | Plugin interface | Clio, Linear, Xero — community-built |

---

## Setup (v0.3)

**Prerequisites:** Python 3.11+, a microphone, an OpenAI API key

```bash
cd client
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env: set LLM_API_KEY (also used for Whisper + TTS)

# Text REPL
python main.py

# Voice mode (microphone → Whisper → router → spoken confirmation)
python main.py --voice

# Voice mode without TTS
python main.py --voice --no-tts

# Pipe mode (stdin → stdout JSON)
python main.py --pipe
```

**Self-host:** Point `DONNA_RUNTIME_URL` to your own backend.
Leave it unset to use the hosted runtime at https://donnaoss.com (free during pre-alpha).

---

## Integrations

DONNA routes extracted intents to integrations you configure.

| Integration | Status | What DONNA sends |
|------------|--------|-----------------|
| Clio | scaffold v0.10 (mock-mode) | OAuth2 + REST + per-mutation IDR; needs sandbox token via macOS Keychain entry `grip-clio-<tenant_id>` |
| Linear | planned v0.2 | task with assignee + deadline |
| Xero | planned v0.3 | time entry for invoicing |
| Custom webhook | v0.1 | raw JSON intent — wire it yourself |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | required | OpenAI API key — used for intent extraction, Whisper STT, and TTS |
| `LLM_BASE_URL` | OpenAI | Override for local model (e.g. Ollama at `http://localhost:11434/v1`) |
| `DONNA_RUNTIME_URL` | hosted | Self-hosted runtime URL |
| `PROMPT_DIR` | `../voice-prompts` | Path to prompt library (use your own fork) |
| `CONFIDENCE_THRESHOLD` | `0.7` | Below this, DONNA asks a clarifying question |
| `SAMPLE_RATE` | `16000` | Audio sample rate in Hz |
| `VAD_AGGRESSIVENESS` | `2` | webrtcvad aggressiveness 0–3 (higher = less sensitive) |
| `STT_BACKEND` | `api` | `api` (Whisper API) or `local` (local openai-whisper) |
| `CACHE_DB` | `~/.donna/cache.db` | SQLite path for offline-first local store |
| `DONNA_PII_SHIELD` | on | PII Shield is wired default-on; set `0`/`false`/`off` to disable |
| `PII_LOCAL_LLM_BASE_URL` | `http://localhost:11434/v1` | Layer-2 redaction model — **local host only** (cloud URLs refused, fail-closed) |
| `PII_LOCAL_LLM_MODEL` | `llama3.2` | Local model for the layer-2 PII pass |

---

## Privacy: the PII Shield

The PII Shield (`donna/pii_shield.py`) is **wired default-on**. Every
extraction in the runtime path runs through it before any cloud LLM call —
unless you explicitly set `DONNA_PII_SHIELD=0`.

Two layers (defence-in-depth):

1. **Regex** — fast, deterministic: suffixed org names, multi-token person
   names, case references → stable placeholders (`ORG_1`, `PERSON_1`, …).
2. **Local inference** — an OpenAI-compatible model on *your own machine*
   (default `http://localhost:11434/v1`) catches what regex cannot: single
   names, suffix-less orgs, addresses, amounts, account numbers.

The narrative is de-anonymised before it is stored locally, so your entries
keep real names; only the cloud LLM sees placeholders.

**Local-only and fail-closed by construction:** the layer-2 detector refuses
any non-local endpoint, and if the local model is unreachable the shield
raises instead of forwarding partially-redacted text — the cloud call does
not happen. There is deliberately no cloud fallback for redaction.

No client-side redaction is provably exhaustive against free-form speech.
The strongest guarantee is to run the model layer itself locally: point
`LLM_BASE_URL` at Ollama and nothing leaves your infrastructure at all.

## The prompt library

DONNA's intelligence comes from the prompts in `../voice-prompts/`.
Those prompts are open (AGPLv3). Tune them for your jurisdiction, firm type,
or practice area — and if you distribute your changes, you share back.

That's the flywheel: the community tunes the prompts; DONNA gets smarter for everyone.
