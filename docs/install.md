# Install — DONNA OSS

> Status: alpha. The instructions below describe the v0.1.0 shape. Some surfaces are scaffolds (see [ROADMAP.md](../ROADMAP.md) for the journey vector).

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer (for the MCP server)
- An MCP-compatible client: Claude Desktop, Claude Code, Cursor, or any IDE plug-in that speaks the Model Context Protocol

## Clone

```bash
git clone https://github.com/chiefofstaff-legal/donna.git
cd donna
```

## Verify the audit chain (60-second sanity check)

Before installing anything, verify the repository's own audit chain. DONNA's brand is the verb *probat* — the verb has to verify.

```bash
export DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08
python3 bin/notarise verify --chain PROBAT.md
```

Expected output:

```
OK: 3 record(s) verified (HMAC-SHA256)
```

If that fails, stop. The repository is not in a healthy state and the install instructions below are not safe to follow.

## Install the MCP server

The MCP server is the bridge between your AI client and DONNA's local Python brains.

```bash
cd mcp-servers/donna
npm install
npm run build
npm start
```

The server listens on `http://localhost:3102` by default. Set `DONNA_PORT` and `DONNA_AUTH_TOKEN` to override.

## Install the Python client

The client holds the voice surface, intent extractor, and local SQLite cache.

```bash
cd ../../client
python3 -m venv .venv
source .venv/bin/activate     # macOS/Linux
# .venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env to set OPENAI_API_KEY (or any OpenAI-compatible provider)
```

## Connect your MCP client

The exact step varies by client. Two examples:

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add:

```json
{
  "mcpServers": {
    "donna": {
      "url": "http://localhost:3102",
      "auth": "Bearer ${DONNA_AUTH_TOKEN}"
    }
  }
}
```

Restart Claude Desktop.

### Claude Code

```bash
claude mcp add --scope user donna http://localhost:3102
```

## Run the client

```bash
cd client
python3 main.py          # text REPL
python3 main.py --voice  # voice mode (requires microphone)
python3 main.py --pipe   # stdin to JSON
```

## Run tests

```bash
cd client
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
```

Tests mock all hardware and external APIs. No microphone or live API key required for the suite.

## Where to next

- [ROADMAP.md](../ROADMAP.md) — the five-waypoint journey vector
- [PROBAT.md](../PROBAT.md) — the audit chain DONNA keeps about itself
- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to send a PR

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `bin/notarise verify` fails | `DONNA_NOTARISE_KEY` not set, or wrong key | Set the public demo key for the public chain (see above) |
| MCP client cannot connect | Server not running, or wrong port | Confirm `npm start` succeeded; check `DONNA_PORT` |
| Voice mode stuck on "listening" | webrtcvad aggressiveness too low | Set `DONNA_VAD_AGGRESSIVENESS=3` in `.env` |
| Whisper API rate limits | Default to `api` backend, falls over on burst | Switch to `local` backend (`DONNA_STT_BACKEND=local`) |

For anything not listed: open an issue with the label `install` and the output of `bin/notarise verify --chain PROBAT.md` (it tells us your environment is at least chain-healthy).

*DONNA probat.*
