import { z } from "zod";
import Anthropic from "@anthropic-ai/sdk";
import { makeIdr, IDR } from "../idr.js";

export const DraftInputSchema = z.object({
  template: z.string().min(1).describe("Template name, e.g. 'nda', 'service-agreement', 'employment-contract'"),
  fields: z.record(z.string()).describe("Key-value map of template fields to populate"),
});

export type DraftInput = z.infer<typeof DraftInputSchema>;

export interface DraftResult {
  status: "ok" | "demo";
  template: string;
  word_count: number;
  draft_text: string;
  idr: IDR;
}

export async function draft(input: DraftInput): Promise<DraftResult> {
  const apiKey = process.env["ANTHROPIC_API_KEY"] ?? "";
  const fieldsSummary = Object.entries(input.fields).map(([k, v]) => `${k}: ${v}`).join(", ");
  const idr = makeIdr({
    intent: `draft:${input.template}:${fieldsSummary.slice(0, 60)}`,
    signer: "donna-bot",
    confidence: apiKey ? 0.85 : 0.0,
    metadata: { tool: "donna_draft", template: input.template, mode: apiKey ? "live" : "demo" },
  });

  if (!apiKey) {
    const demoText = `[DEMO] ${input.template.toUpperCase()} — Set ANTHROPIC_API_KEY for a real draft.\n\nThis agreement is entered into between ${input.fields["party_a"] ?? "Party A"} and ${input.fields["party_b"] ?? "Party B"}.`;
    return { status: "demo", template: input.template, word_count: demoText.split(/\s+/).length, draft_text: demoText, idr };
  }

  const client = new Anthropic({ apiKey });
  const response = await client.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 2048,
    system: "You are DONNA, a legal AI assistant. Draft professional legal documents. Use plain English where possible.",
    messages: [{
      role: "user",
      content: `Draft a ${input.template} document using these fields:\n${Object.entries(input.fields).map(([k, v]) => `- ${k}: ${v}`).join("\n")}\n\nReturn the complete document text only.`,
    }],
  });

  const text = response.content[0]?.type === "text" ? response.content[0].text : "";
  return { status: "ok", template: input.template, word_count: text.split(/\s+/).length, draft_text: text, idr };
}
