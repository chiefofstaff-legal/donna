import { describe, it, expect, beforeAll, afterAll } from "vitest";
import express from "express";
import { Server } from "http";
import { createServer, buildAuthMiddleware } from "../src/server.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const TEST_PORT = 13102;
const GUARD_PORT = 13103;

async function startApp(port: number, withAuth: boolean): Promise<Server> {
  const app = express();
  app.use(express.json());
  const mcpServer = createServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  app.get("/health", (_req, res) => res.json({ status: "ok" }));
  const token = withAuth ? "test-secret" : "";
  app.all("/mcp", buildAuthMiddleware(token), async (req, res) => {
    await transport.handleRequest(req, res, req.body);
  });
  await mcpServer.connect(transport);
  return new Promise<Server>((resolve) => {
    const s = app.listen(port, () => resolve(s));
  });
}

function closeServer(s: Server): Promise<void> {
  return new Promise((resolve, reject) => s.close((e) => (e ? reject(e) : resolve())));
}

describe("donna-legal MCP server", () => {
  let httpServer: Server;
  let guardServer: Server;

  beforeAll(async () => {
    httpServer = await startApp(TEST_PORT, false);
    guardServer = await startApp(GUARD_PORT, true);
  });

  afterAll(async () => {
    await Promise.all([closeServer(httpServer), closeServer(guardServer)]);
  });

  it("health endpoint responds 200", async () => {
    const res = await fetch(`http://localhost:${TEST_PORT}/health`);
    expect(res.status).toBe(200);
    const body = await res.json() as { status: string };
    expect(body.status).toBe("ok");
  });

  it("donna_analyse tool is registered", () => {
    const server = createServer();
    const tools = (server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools;
    expect(tools).toHaveProperty("donna_analyse");
  });

  it("donna_draft tool is registered", () => {
    const server = createServer();
    const tools = (server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools;
    expect(tools).toHaveProperty("donna_draft");
  });

  it("donna_review tool is registered", () => {
    const server = createServer();
    const tools = (server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools;
    expect(tools).toHaveProperty("donna_review");
  });

  it("donna_export tool is registered", () => {
    const server = createServer();
    const tools = (server as unknown as { _registeredTools: Record<string, unknown> })._registeredTools;
    expect(tools).toHaveProperty("donna_export");
  });

  it("unauthorised request returns 403 when auth is enabled", async () => {
    const res = await fetch(`http://localhost:${GUARD_PORT}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", method: "tools/list", id: 1 }),
    });
    expect(res.status).toBe(403);
  });

  it("donna_analyse returns demo result without API key", async () => {
    const savedKey = process.env["ANTHROPIC_API_KEY"];
    delete process.env["ANTHROPIC_API_KEY"];
    try {
      const { analyse } = await import("../src/tools/analyse.js");
      const result = await analyse({ doc_text: "This agreement is between Party A and Party B.", jurisdiction: "UK" });
      expect(result.status).toBe("demo");
      expect(result.jurisdiction).toBe("UK");
      expect(Array.isArray(result.findings)).toBe(true);
      expect(result.idr).toBeDefined();
      expect(typeof result.idr.signature).toBe("string");
    } finally {
      if (savedKey !== undefined) process.env["ANTHROPIC_API_KEY"] = savedKey;
    }
  });

  it("donna_draft returns demo result without API key", async () => {
    const savedKey = process.env["ANTHROPIC_API_KEY"];
    delete process.env["ANTHROPIC_API_KEY"];
    try {
      const { draft } = await import("../src/tools/draft.js");
      const result = await draft({ template: "nda", fields: { party_a: "Acme Ltd", party_b: "Beta Corp" } });
      expect(result.status).toBe("demo");
      expect(result.template).toBe("nda");
      expect(result.draft_text.length).toBeGreaterThan(0);
      expect(result.idr).toBeDefined();
    } finally {
      if (savedKey !== undefined) process.env["ANTHROPIC_API_KEY"] = savedKey;
    }
  });

  it("donna_review returns demo result without API key", async () => {
    const savedKey = process.env["ANTHROPIC_API_KEY"];
    delete process.env["ANTHROPIC_API_KEY"];
    try {
      const { review } = await import("../src/tools/review.js");
      const result = await review({ doc_text: "This agreement governs the relationship.", redline_target: "liability" });
      expect(result.status).toBe("demo");
      expect(Array.isArray(result.redlines)).toBe(true);
      expect(result.idr).toBeDefined();
    } finally {
      if (savedKey !== undefined) process.env["ANTHROPIC_API_KEY"] = savedKey;
    }
  });

  it("donna_export formats content and signs IDR", async () => {
    const { exportDoc } = await import("../src/tools/export.js");
    const result = exportDoc({ content: "# Test Document\n\nContent here.", format: "md" });
    expect(result.status).toBe("ok");
    expect(result.format).toBe("md");
    expect(result.word_count).toBeGreaterThan(0);
    expect(result.idr).toBeDefined();
    expect(result.note).toContain("markdown");
  });

  it("IDR signing produces 64-char hex signature when key is set", async () => {
    const origKey = process.env["DONNA_NOTARISE_KEY"];
    process.env["DONNA_NOTARISE_KEY"] = "test-key-vitest-2026";
    try {
      const { exportDoc } = await import("../src/tools/export.js");
      const result = exportDoc({ content: "test", format: "txt" });
      expect(result.idr.signature).toMatch(/^[0-9a-f]{64}$/);
    } finally {
      if (origKey !== undefined) process.env["DONNA_NOTARISE_KEY"] = origKey;
      else delete process.env["DONNA_NOTARISE_KEY"];
    }
  });

  it("IDR has correct protocol version", async () => {
    const { exportDoc } = await import("../src/tools/export.js");
    const result = exportDoc({ content: "test", format: "txt" });
    expect(result.idr.protocol).toBe("happi/1.1");
  });
});
