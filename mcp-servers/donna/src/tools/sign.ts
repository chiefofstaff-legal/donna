import { z } from "zod";
import { spawnSync } from "node:child_process";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { makeIdr, IDR } from "../idr.js";

export const SignInputSchema = z.object({
  file_path: z.string().min(1).describe(
    "Absolute path to the document to sign (PDF, DOCX, HTML, MD, PNG, JPG, TXT, DOC, RTF, ODT)"
  ),
  signers: z
    .array(
      z.object({
        email: z.string().email().describe("Signer email address"),
        name: z.string().min(1).describe("Signer display name"),
        role: z.string().optional().describe("Signer role, e.g. 'Client' or 'Counsel'"),
      })
    )
    .min(1)
    .describe("Ordered list of signers — order is preserved in the DocuSeal submission"),
  emit_idr: z.boolean().optional().default(true).describe(
    "Emit a DONNA IDR audit record for this signing dispatch (default true)"
  ),
  completed_redirect_url: z.string().url().optional().describe(
    "URL signers are redirected to after completing signing"
  ),
});

export type SignInput = z.infer<typeof SignInputSchema>;

export interface SignerUrl {
  email: string;
  name: string;
  signing_url: string;
}

export interface SignResult {
  status: "ok";
  submission_id: number;
  signing_urls: SignerUrl[];
  idr_signature: string;
  template_id: number;
  idr: IDR;
}

// Resolve repo root: mcp-servers/donna/src/tools/sign.ts → ../../../../..
function repoRoot(): string {
  const thisFile = fileURLToPath(import.meta.url);
  return resolve(join(thisFile, "..", "..", "..", "..", ".."));
}

export async function sign(input: SignInput): Promise<SignResult> {
  const idr = makeIdr({
    intent: `signing_dispatched:${input.file_path}`,
    signer: "donna-bot",
    confidence: 0.95,
    metadata: {
      tool: "donna_sign",
      file_path: input.file_path,
      signer_count: input.signers.length,
      emit_idr: input.emit_idr,
    },
  });

  const root = repoRoot();
  const pyArgs = JSON.stringify({
    file_path: input.file_path,
    signers: input.signers,
    emit_idr: input.emit_idr ?? true,
    redirect_url: input.completed_redirect_url ?? null,
  });

  // Invoke Python handler via subprocess (syscall doctrine: shim hides path manipulation)
  const inlineScript = [
    `import sys, json`,
    `sys.path.insert(0, '${root}')`,
    `sys.path.insert(0, '${root}/donna-skill')`,
    `from handlers.sign import handle`,
    `print(json.dumps(handle(json.loads(sys.stdin.read()))))`,
  ].join("; ");

  const proc = spawnSync("python3", ["-c", inlineScript], {
    input: pyArgs,
    encoding: "utf8",
    timeout: 60_000,
    cwd: root,
  });

  if (proc.status !== 0) {
    const errMsg = _extractError(proc.stderr?.trim() ?? "");
    throw new Error(`donna_sign failed: ${errMsg}`);
  }

  const out = JSON.parse(proc.stdout) as {
    submission_id: number;
    signing_urls: SignerUrl[];
    idr_signature: string;
    template_id: number;
  };

  return {
    status: "ok",
    submission_id: out.submission_id,
    signing_urls: out.signing_urls,
    idr_signature: out.idr_signature,
    template_id: out.template_id,
    idr,
  };
}

function _extractError(raw: string): string {
  // Token must never appear in error output — parse plain-language message from Python
  try {
    const parsed = JSON.parse(raw) as { error?: string };
    if (parsed.error) return parsed.error;
  } catch { /* use raw */ }
  return raw || "unknown error";
}
