import { z } from "zod";
import { makeIdr, IDR } from "../idr.js";

export const ExportInputSchema = z.object({
  content: z.string().min(1).describe("Document content to export"),
  format: z.enum(["pdf", "docx", "md", "txt"]).describe("Output format"),
});

export type ExportInput = z.infer<typeof ExportInputSchema>;

export interface ExportResult {
  status: "ok";
  format: string;
  content: string;
  word_count: number;
  note: string;
  idr: IDR;
}

const FORMAT_NOTES: Record<string, string> = {
  md: "Ready to render. Compatible with all major markdown processors.",
  txt: "Plain text, universally compatible.",
  pdf: "PDF generation requires server-side rendering (wkhtmltopdf / weasyprint). Content provided as markdown source.",
  docx: "DOCX generation requires python-docx or LibreOffice. Content provided as markdown source.",
};

export function exportDoc(input: ExportInput): ExportResult {
  const idr = makeIdr({
    intent: `export:${input.format}:${input.content.slice(0, 60)}`,
    signer: "donna-bot",
    confidence: 1.0,
    metadata: { tool: "donna_export", format: input.format, word_count: input.content.split(/\s+/).length },
  });

  return {
    status: "ok",
    format: input.format,
    content: input.content,
    word_count: input.content.split(/\s+/).length,
    note: FORMAT_NOTES[input.format] ?? "Exported.",
    idr,
  };
}
