import { createHmac, createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const PROTOCOL_VERSION = "happi/1.1";
export const GENESIS_HASH = "0".repeat(64);
export const ENV_SIGN_KEY = "DONNA_NOTARISE_KEY";

// Happi-lib v1.1 canonical idr_ref shape (per happi.md:120-127).
export interface IdrRef {
  sha256: string;                  // content hash of envelope + event stream
  cid: string | null;              // IPFS CID if pinned
  model_versions: string[];        // model identifiers consulted
  block_anchor: string | null;     // on-chain block reference if anchored
}

export interface IdrPayload {
  confidence: number;
  decision_id: string;
  intent: string;
  metadata: Record<string, unknown>;
  previous_hash: string;
  protocol: string;
  signer: string;
  timestamp: string;
}

export interface IDR extends IdrPayload {
  signature: string;
  idr_ref?: IdrRef;  // canonical happi-lib v1.1 content hash; absent when happi-lib unreachable
}

// Resolve happi.md location. Override via HAPPI_MD_PATH env for tests / packaging.
function happiMdPath(): string {
  return process.env["HAPPI_MD_PATH"] ?? join(homedir(), ".hal", "happi.md");
}

// Local stdlib parity implementation of cmd:idr.emit (happi.md:135-137).
// Used as fallback when bash/happi.md is unavailable, so the canonical
// sha256 is always reproducible.
function localIdrEmit(envelopeJson: string, ndjsonEvents: string): IdrRef {
  const buf = Buffer.concat([
    Buffer.from(envelopeJson, "utf8"),
    Buffer.from(ndjsonEvents, "utf8"),
  ]);
  return {
    sha256: createHash("sha256").update(buf).digest("hex"),
    cid: null,
    model_versions: [],
    block_anchor: null,
  };
}

// Dispatch cmd:idr.emit through happi.md and parse the emitted idr event.
// Returns null if the dispatch path is unreachable; caller falls back to local.
function happiIdrEmit(envelopeJson: string, ndjsonEvents: string): IdrRef | null {
  const path = happiMdPath();
  if (!existsSync(path)) return null;
  const reqEnvelope = {
    v: "happi/1.1",
    id: `donna-idr-${Date.now()}`,
    cmd: "idr.emit",
    args: [envelopeJson, ndjsonEvents],
    flags: {},
  };
  const proc = spawnSync("bash", [path, "run"], {
    input: JSON.stringify(reqEnvelope),
    timeout: 10_000,
    encoding: "utf8",
  });
  if (proc.status !== 0 || !proc.stdout) return null;
  for (const line of proc.stdout.split("\n").reverse()) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line) as { type?: string; idr_ref?: IdrRef };
      if (event.type === "idr" && event.idr_ref) return event.idr_ref;
    } catch { /* skip non-JSON */ }
  }
  return null;
}

// Public: compute canonical idr_ref for a (envelope, events) pair.
// Prefers happi-lib dispatch (sha256 byte-equivalent), falls back to local.
export function computeIdrRef(envelopeJson: string, ndjsonEvents: string): IdrRef {
  return happiIdrEmit(envelopeJson, ndjsonEvents) ?? localIdrEmit(envelopeJson, ndjsonEvents);
}

function stableStringify(val: unknown): string {
  if (val === null || typeof val !== "object") return JSON.stringify(val);
  if (Array.isArray(val)) return "[" + val.map(stableStringify).join(",") + "]";
  const obj = val as Record<string, unknown>;
  return (
    "{" +
    Object.keys(obj)
      .sort()
      .map((k) => JSON.stringify(k) + ":" + stableStringify(obj[k]))
      .join(",") +
    "}"
  );
}

export function canonicalPayload(payload: IdrPayload): string {
  return stableStringify(payload);
}

export function signIdr(payload: IdrPayload, key: string): string {
  return createHmac("sha256", key).update(canonicalPayload(payload), "utf8").digest("hex");
}

export function makeDecisionId(): string {
  return `idr_${Date.now()}_${Math.floor(Math.random() * 1000).toString().padStart(3, "0")}`;
}

export function makeIdr(
  opts: Pick<IdrPayload, "intent" | "signer" | "confidence" | "metadata"> & {
    previous_hash?: string;
  }
): IDR {
  const key = process.env[ENV_SIGN_KEY] ?? "";
  const payload: IdrPayload = {
    confidence: opts.confidence,
    decision_id: makeDecisionId(),
    intent: opts.intent,
    metadata: opts.metadata,
    previous_hash: opts.previous_hash ?? GENESIS_HASH,
    protocol: PROTOCOL_VERSION,
    signer: opts.signer,
    timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
  };
  const signature = key ? signIdr(payload, key) : "";
  // Attach canonical happi-lib v1.1 idr_ref (sha256 of canonical payload + empty events).
  // Hashing the envelope-equivalent JSON with empty events makes the IDR self-contained
  // and locally verifiable; new callers can re-emit cmd:idr.emit on the recorded payload
  // to confirm the chain. Existing callers that don't read idr_ref see no change.
  const idr_ref = computeIdrRef(canonicalPayload(payload), "");
  return { ...payload, signature, idr_ref };
}
