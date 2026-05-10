import express, { Request, Response } from "express";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { analyse, AnalyseInputSchema } from "./tools/analyse.js";
import { draft, DraftInputSchema } from "./tools/draft.js";
import { review, ReviewInputSchema } from "./tools/review.js";
import { exportDoc, ExportInputSchema } from "./tools/export.js";
import { sign, SignInputSchema } from "./tools/sign.js";

const PORT = parseInt(process.env["DONNA_PORT"] ?? "3102", 10);
const authToken = process.env["DONNA_AUTH_TOKEN"] ?? "";

export function createServer(): McpServer {
  const server = new McpServer({
    name: "donna-legal",
    version: "0.1.0",
  });

  server.tool(
    "donna_analyse",
    "Analyse a legal document and identify key clauses, risks, and obligations",
    AnalyseInputSchema.shape,
    async (args) => {
      const result = analyse(AnalyseInputSchema.parse(args));
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  );

  server.tool(
    "donna_draft",
    "Draft a legal document from a named template and field map",
    DraftInputSchema.shape,
    async (args) => {
      const result = draft(DraftInputSchema.parse(args));
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  );

  server.tool(
    "donna_review",
    "Review a legal document and produce redline suggestions for a specified category",
    ReviewInputSchema.shape,
    async (args) => {
      const result = review(ReviewInputSchema.parse(args));
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  );

  server.tool(
    "donna_export",
    "Export document content to the specified format (pdf, docx, md, txt)",
    ExportInputSchema.shape,
    async (args) => {
      const result = exportDoc(ExportInputSchema.parse(args));
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  );

  server.tool(
    "donna_sign",
    "Dispatch a document for e-signature via DocuSeal. Supports PDF, DOCX, HTML, MD, PNG, JPG, TXT, DOC, RTF, ODT. Returns signing URLs per signer and an IDR audit record.",
    SignInputSchema.shape,
    async (args) => {
      const result = await sign(SignInputSchema.parse(args));
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    }
  );

  return server;
}

export function buildAuthMiddleware(token: string) {
  return (req: Request, res: Response, next: () => void): void => {
    if (!token) { next(); return; }
    const header = req.headers["authorization"] ?? "";
    if (header === `Bearer ${token}`) { next(); return; }
    res.status(403).json({ error: "Forbidden" });
  };
}

async function main(): Promise<void> {
  const app = express();
  app.use(express.json());

  const mcpServer = createServer();
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });

  app.get("/health", (_req, res) => {
    res.json({ status: "ok", server: "donna-legal", port: PORT });
  });

  app.all("/mcp", buildAuthMiddleware(authToken), async (req, res) => {
    await transport.handleRequest(req, res, req.body);
  });

  await mcpServer.connect(transport);

  app.listen(PORT, () => {
    console.log(`donna-legal MCP server listening on :${PORT}`);
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
