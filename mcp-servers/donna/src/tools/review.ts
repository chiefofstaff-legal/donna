import { z } from "zod";
import Anthropic from "@anthropic-ai/sdk";
import { makeIdr, IDR } from "../idr.js";

export const ReviewInputSchema = z.object({
  doc_text: z.string().min(1).describe("Full text of the document to review"),
  redline_target: z.string().min(1).describe("Focus area: 'liability', 'ip', 'payment', 'termination', 'all'"),
});

export type ReviewInput = z.infer<typeof ReviewInputSchema>;

interface Redline {
  location: string;
  issue: string;
  suggestion: string;
}

export interface ReviewResult {
  status: "ok" | "demo";
  redline_target: string;
  redlines: Redline[];
  summary: string;
  idr: IDR;
}

const DEMO_REDLINES: Redline[] = [
  { location: "Clause 4.2", issue: "Unlimited indemnity scope", suggestion: "Cap indemnity at contract value" },
  { location: "Clause 7.1", issue: "60-day payment term is non-standard", suggestion: "Negotiate to net-30" },
];

export async function review(input: ReviewInput): Promise<ReviewResult> {
  const apiKey = process.env["ANTHROPIC_API_KEY"] ?? "";
  const idr = makeIdr({
    intent: `review:${input.redline_target}:${input.doc_text.slice(0, 60)}`,
    signer: "donna-bot",
    confidence: apiKey ? 0.88 : 0.0,
    metadata: { tool: "donna_review", redline_target: input.redline_target, mode: apiKey ? "live" : "demo" },
  });

  if (!apiKey) {
    return {
      status: "demo",
      redline_target: input.redline_target,
      redlines: DEMO_REDLINES,
      summary: "Demo mode — set ANTHROPIC_API_KEY for real redlining.",
      idr,
    };
  }

  const client = new Anthropic({ apiKey });
  const response = await client.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 1024,
    system: "You are DONNA, a legal AI assistant. Return only valid JSON. No preamble.",
    messages: [{
      role: "user",
      content: `Review this document for ${input.redline_target} issues. Return JSON with:
- "redlines": array of {"location": string, "issue": string, "suggestion": string}
- "summary": one paragraph summary

Document:
${input.doc_text.slice(0, 8000)}`,
    }],
  });

  const text = response.content[0]?.type === "text" ? response.content[0].text : "{}";
  let parsed: { redlines?: unknown[]; summary?: string } = {};
  try { parsed = JSON.parse(text); } catch { parsed = { redlines: [], summary: text.slice(0, 500) }; }

  return {
    status: "ok",
    redline_target: input.redline_target,
    redlines: Array.isArray(parsed.redlines) ? (parsed.redlines as Redline[]) : [],
    summary: typeof parsed.summary === "string" ? parsed.summary : "",
    idr,
  };
}
