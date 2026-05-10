# donna-legal MCP server

Streamable-HTTP MCP server exposing four legal-tech tools. Listens on port 3102 by default.

## Install and run

```bash
cd mcp-servers/donna
npm install
npm run build
npm start
```

## Tools

| Tool | Description |
|------|-------------|
| `donna_analyse` | Analyse a document for clauses, risks, obligations |
| `donna_draft` | Draft from a named template + field map |
| `donna_review` | Redline a document by category |
| `donna_export` | Export content to pdf, docx, md, or txt |

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `DONNA_PORT` | `3102` | HTTP listen port |
| `DONNA_AUTH_TOKEN` | _(empty)_ | Bearer token; omit to disable auth |

## Test

```bash
npm test
```

## MCP endpoint

```
POST http://localhost:3102/mcp
```

Add to your MCP client config:

```json
{
  "mcpServers": {
    "donna-legal": {
      "type": "streamable-http",
      "url": "http://localhost:3102/mcp"
    }
  }
}
```
