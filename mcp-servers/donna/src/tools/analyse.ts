import { z } from "zod";
import Anthropic from "@anthropic-ai/sdk";
import { makeIdr, IDR } from "../idr.js";

export const AnalyseInputSchema = z.object({
  doc_text: z.string().min(1).describe("Full text of the legal document to analyse"),
  jurisdiction: z.string().min(1).describe("Jurisdiction code, e.g. 'ZA', 'UK', 'US-CA'"),
});

export type AnalyseInput = z.infer<typeof AnalyseInputSchema>;

interface AnalysisFinding {
  clause: string;
  risk: string;
  severity: "low" | "medium" | "high";
}

export interface AnalyseResult {
  status: "ok" | "demo";
  jurisdiction: string;
  doc_length: number;
  findings: AnalysisFinding[];
  summary: string;
  idr: IDR;
}

const DEMO_FINDINGS: AnalysisFinding[] = [
  { clause: "Limitation of Liability", risk: "Uncapped liability exposure", severity: "high" },
  { clause: "Termination", risk: "Unilateral termination without notice", severity: "medium" },
  { clause: "Governing Law", risk: "Unfavourable jurisdiction selected", severity: "low" },
];

export async function analyse(input: AnalyseInput): Promise<AnalyseResult> {
  const apiKey = process.env["ANTHROPIC_API_KEY"] ?? "";
  const idr = makeIdr({
    intent: `analyse:${input.jurisdiction}:${input.doc_text.slice(0, 60)}`,
    signer: "donna-bot",
    confidence: apiKey ? 0.9 : 0.0,
    metadata: { tool: "donna_analyse", jurisdiction: input.jurisdiction, mode: apiKey ? "live" : "demo" },
  });

  if (!apiKey) {
    return {
      status: "demo",
      jurisdiction: input.jurisdiction,
      doc_length: input.doc_text.length,
      findings: DEMO_FINDINGS,
      summary: "Demo mode — set ANTHROPIC_API_KEY for real analysis. This document contains standard commercial clauses with moderate risk exposure.",
      idr,
    };
  }

  const client = new Anthropic({ apiKey });
  const response = await client.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 1024,
    system: "You are DONNA, a legal AI assistant. Respond only with valid JSON. No preamble.",
    messages: [{
      role: "user",
      content: `Analyse this ${input.jurisdiction} legal document. Return JSON with exactly these keys:
- "findings": array of {"clause": string, "risk": string, "severity": "low"|"medium"|"high"}
- "summary": one paragraph plain-English summary

Document (first 8000 chars):
${input.doc_text.slice(0, 8000)}`,
    }],
  });

  const text = response.content[0]?.type === "text" ? response.content[0].text : "{}";
  let parsed: { findings?: unknown[]; summary?: string } = {};
  try { parsed = JSON.parse(text); } catch { parsed = { findings: [], summary: text.slice(0, 500) }; }

  return {
    status: "ok",
    jurisdiction: input.jurisdiction,
    doc_length: input.doc_text.length,
    findings: Array.isArray(parsed.findings) ? (parsed.findings as AnalysisFinding[]) : [],
    summary: typeof parsed.summary === "string" ? parsed.summary : "",
    idr,
  };
}
