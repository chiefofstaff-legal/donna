import { createHmac, createHash, createPrivateKey, createPublicKey, sign as cryptoSign, verify as cryptoVerify, timingSafeEqual } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const PROTOCOL_VERSION = "happi/1.1";
export const GENESIS_HASH = "0".repeat(64);
export const ENV_SIGN_KEY = "DONNA_NOTARISE_KEY";
export const ENV_ED25519_KEY = "DONNA_NOTARISE_ED25519_PRIVKEY";
export const SCHEME_HMAC = "hmac-sha256";
export const SCHEME_ED25519 = "ed25519";

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
  scheme?: string;  // "hmac-sha256" (default) | "ed25519"
  idr_ref?: IdrRef; // canonical happi-lib v1.1 content hash; absent when happi-lib unreachable
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

export function canonicalPayload(payload: IdrPayload | IDR): string {
  // Excludes `scheme` and `signature` — byte-identical to Python's canonical_payload().
  // Accepts either IdrPayload (no sig fields) or a full IDR (strips them). Backward-compatible.
  const { signature: _sig, scheme: _scheme, idr_ref: _ref, ...rest } = payload as IDR;
  return stableStringify(rest);
}

export function signIdr(payload: IdrPayload, key: string): string {
  return createHmac("sha256", key).update(canonicalPayload(payload), "utf8").digest("hex");
}

// ASN.1 PKCS#8 header for a raw 32-byte Ed25519 seed.
const PKCS8_HEADER = Buffer.from("302e020100300506032b657004220420", "hex");
// ASN.1 SubjectPublicKeyInfo header for a raw 32-byte Ed25519 public key.
const SPKI_HEADER = Buffer.from("302a300506032b6570032100", "hex");

export function ed25519Sign(payloadStr: string, seedHex: string): string {
  const seed = Buffer.from(seedHex.trim(), "hex");
  const priv = createPrivateKey({ key: Buffer.concat([PKCS8_HEADER, seed]), format: "der", type: "pkcs8" });
  return cryptoSign(null, Buffer.from(payloadStr, "utf8"), priv).toString("hex");
}

export function ed25519PubkeyHex(seedHex: string): string {
  const seed = Buffer.from(seedHex.trim(), "hex");
  const priv = createPrivateKey({ key: Buffer.concat([PKCS8_HEADER, seed]), format: "der", type: "pkcs8" });
  const pub = createPublicKey(priv);
  return pub.export({ type: "spki", format: "der" }).slice(-32).toString("hex");
}

export function ed25519Verify(payloadStr: string, sigHex: string, pubkeyHex: string): boolean {
  const pub = createPublicKey({ key: Buffer.concat([SPKI_HEADER, Buffer.from(pubkeyHex.trim(), "hex")]), format: "der", type: "spki" });
  return cryptoVerify(null, Buffer.from(payloadStr, "utf8"), pub, Buffer.from(sigHex, "hex"));
}

export function makeDecisionId(): string {
  return `idr_${Date.now()}_${Math.floor(Math.random() * 1000).toString().padStart(3, "0")}`;
}

export type VerifyResult = { valid: true } | { valid: false; reason: string };

/** verifyRecord — mirrors web/lib/idr.js verifyRecord(record, key?, pubkeyHex?). */
export function verifyRecord(record: IDR, key?: string, pubkeyHex?: string): VerifyResult {
  if (!record || typeof record !== "object") return { valid: false, reason: "record not object" };
  if (typeof record.signature !== "string" || !record.signature) {
    return { valid: false, reason: "signature missing" };
  }
  const scheme = record.scheme ?? SCHEME_HMAC;
  const payload = canonicalPayload(record);

  if (scheme === SCHEME_ED25519) {
    const pub = pubkeyHex ?? process.env["DONNA_NOTARISE_ED25519_PUBKEY"];
    if (!pub) return { valid: false, reason: "DONNA_NOTARISE_ED25519_PUBKEY not set; cannot verify ed25519 signature" };
    try {
      if (!ed25519Verify(payload, record.signature, pub)) return { valid: false, reason: "ed25519 signature invalid" };
    } catch (e: unknown) {
      return { valid: false, reason: `ed25519 verify error: ${(e as Error).message}` };
    }
  } else {
    const k = key ?? process.env[ENV_SIGN_KEY];
    if (!k) return { valid: false, reason: "missing key" };
    const expected = createHmac("sha256", k).update(payload, "utf8").digest("hex");
    const a = Buffer.from(expected, "hex");
    const b = Buffer.from(record.signature, "hex");
    if (a.length !== b.length || !timingSafeEqual(a, b)) {
      return { valid: false, reason: `signature mismatch (expected ${expected.slice(0, 8)}..., got ${record.signature.slice(0, 8)}...)` };
    }
  }
  if (record.protocol !== PROTOCOL_VERSION) {
    return { valid: false, reason: `unexpected protocol ${JSON.stringify(record.protocol)}` };
  }
  if (!(record.confidence >= 0.0 && record.confidence <= 1.0)) {
    return { valid: false, reason: `confidence ${record.confidence} out of [0.0, 1.0]` };
  }
  return { valid: true };
}

export interface SignOpts {
  intent: string;
  signer: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
  scheme?: string;
  key?: string;               // HMAC secret (hmac-sha256)
  ed25519SeedHex?: string;    // 32-byte seed hex (ed25519)
  previousHash?: string;
  decisionId?: string;
  timestamp?: string;
}

/** sign() — mirrors web/lib/idr.js public API. Returns { record, hash }. */
export function sign(opts: SignOpts): { record: IDR; hash: string } {
  const scheme = opts.scheme ?? SCHEME_HMAC;
  if (!opts.intent) throw Object.assign(new Error("intent required"), { code: "missing_intent" });
  if (!opts.signer) throw Object.assign(new Error("signer required"), { code: "missing_signer" });
  const confidence = opts.confidence ?? 1.0;
  if (confidence < 0 || confidence > 1) throw new Error("confidence out of [0,1]");

  const payload: IdrPayload = {
    confidence,
    decision_id: opts.decisionId ?? makeDecisionId(),
    intent: opts.intent,
    metadata: opts.metadata ?? {},
    previous_hash: opts.previousHash ?? GENESIS_HASH,
    protocol: PROTOCOL_VERSION,
    signer: opts.signer,
    timestamp: opts.timestamp ?? new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
  };

  let signature: string;
  if (scheme === SCHEME_ED25519) {
    const seedHex = opts.ed25519SeedHex ?? process.env[ENV_ED25519_KEY];
    if (!seedHex) throw Object.assign(new Error(`${ENV_ED25519_KEY} not set`), { code: "missing_key" });
    signature = ed25519Sign(canonicalPayload(payload), seedHex);
  } else {
    const key = opts.key ?? process.env[ENV_SIGN_KEY];
    if (!key) throw Object.assign(new Error(`${ENV_SIGN_KEY} not set`), { code: "missing_key" });
    signature = signIdr(payload, key);
  }

  const record: IDR = { ...payload, signature, scheme };
  return { record, hash: createHash("sha256").update(canonicalPayload(payload), "utf8").digest("hex") };
}

export function makeIdr(
  opts: Pick<IdrPayload, "intent" | "signer" | "confidence" | "metadata"> & {
    previous_hash?: string;
    scheme?: string;
  }
): IDR {
  const scheme = opts.scheme ?? SCHEME_HMAC;
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

  let signature = "";
  if (scheme === SCHEME_ED25519) {
    const seedHex = process.env[ENV_ED25519_KEY] ?? "";
    if (seedHex) signature = ed25519Sign(canonicalPayload(payload), seedHex);
  } else {
    const key = process.env[ENV_SIGN_KEY] ?? "";
    if (key) signature = signIdr(payload, key);
  }

  const idr_ref = computeIdrRef(canonicalPayload(payload), "");
  return { ...payload, signature, scheme, idr_ref };
}
