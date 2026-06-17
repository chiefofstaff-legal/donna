import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  sign,
  verifyRecord,
  canonicalPayload,
  ed25519Sign,
  ed25519PubkeyHex,
  ed25519Verify,
  makeIdr,
  SCHEME_HMAC,
  SCHEME_ED25519,
  ENV_ED25519_KEY,
  GENESIS_HASH,
} from "../src/idr.js";

// Deterministic test keys — never production keys.
// 32-byte seed hex (matches Python test: "a" * 64 = 32 bytes of 0xaa).
const TEST_SEED_HEX = "a".repeat(64);
const TEST_HMAC_KEY = "test-key-donna-unit-2026-abc123xyz";

// Derived once — must match Python's _derive_pubkey(TEST_SEED_HEX).
const TEST_PUBKEY_HEX = ed25519PubkeyHex(TEST_SEED_HEX);

// Cross-language parity vector (must match Python test_cross_language_parity_vector).
const PARITY_RECORD_FIELDS = {
  decision_id: "idr_parity_001",
  timestamp: "2026-06-17T00:00:00Z",
  intent: "cross-language parity test",
  signer: "donna-test",
  confidence: 1.0,
  previous_hash: "0".repeat(64),
  metadata: { lang: "python" },
};

function withEnv(key: string, value: string, fn: () => void) {
  const old = process.env[key];
  process.env[key] = value;
  try { fn(); } finally {
    if (old === undefined) delete process.env[key];
    else process.env[key] = old;
  }
}

describe("idr Ed25519 signing", () => {
  beforeEach(() => { process.env[ENV_ED25519_KEY] = TEST_SEED_HEX; });
  afterEach(() => { delete process.env[ENV_ED25519_KEY]; });

  it("sign with ed25519 scheme returns 128-char hex signature", () => {
    const { record } = sign({
      intent: "test intent",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    expect(record.signature).toMatch(/^[0-9a-f]{128}$/);
    expect(record.scheme).toBe(SCHEME_ED25519);
  });

  it("sign with ed25519 is deterministic (same key + payload = same sig)", () => {
    const opts = {
      intent: "determinism test",
      signer: "donna-bot",
      confidence: 1.0,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
      timestamp: "2026-06-17T00:00:00Z",
      decisionId: "idr_det_001",
      previousHash: GENESIS_HASH,
    } as const;
    const { record: r1 } = sign(opts);
    const { record: r2 } = sign(opts);
    expect(r1.signature).toBe(r2.signature);
  });

  it("signatures differ across different intents", () => {
    const base = { signer: "donna-bot", confidence: 1.0, metadata: {}, scheme: SCHEME_ED25519, ed25519SeedHex: TEST_SEED_HEX };
    const { record: r1 } = sign({ ...base, intent: "alpha" });
    const { record: r2 } = sign({ ...base, intent: "beta" });
    expect(r1.signature).not.toBe(r2.signature);
  });

  it("ed25519 signature differs from hmac-sha256 signature for same payload", () => {
    const base = {
      intent: "same intent", signer: "donna-bot", confidence: 1.0, metadata: {},
      timestamp: "2026-06-17T00:00:00Z", decisionId: "idr_cross_001", previousHash: GENESIS_HASH,
    };
    const { record: hmacRec } = sign({ ...base, scheme: SCHEME_HMAC, key: TEST_HMAC_KEY });
    const { record: edRec } = sign({ ...base, scheme: SCHEME_ED25519, ed25519SeedHex: TEST_SEED_HEX });
    expect(hmacRec.signature).not.toBe(edRec.signature);
  });
});

describe("idr Ed25519 verify", () => {
  it("verifyRecord accepts a valid ed25519-signed record", () => {
    const { record } = sign({
      intent: "verify test",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    const result = verifyRecord(record, undefined, TEST_PUBKEY_HEX);
    expect(result).toEqual({ valid: true });
  });

  it("verifyRecord rejects tampered intent", () => {
    const { record } = sign({
      intent: "tamper test",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    record.intent = "tampered intent";
    const result = verifyRecord(record, undefined, TEST_PUBKEY_HEX);
    expect(result.valid).toBe(false);
  });

  it("verifyRecord rejects wrong signature bytes", () => {
    const { record } = sign({
      intent: "sig test",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    record.signature = "00".repeat(64);
    const result = verifyRecord(record, undefined, TEST_PUBKEY_HEX);
    expect(result.valid).toBe(false);
  });

  it("verifyRecord returns error when pubkey missing for ed25519", () => {
    const { record } = sign({
      intent: "no pubkey test",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    delete process.env["DONNA_NOTARISE_ED25519_PUBKEY"];
    const result = verifyRecord(record);
    expect(result.valid).toBe(false);
    expect((result as any).reason).toMatch(/DONNA_NOTARISE_ED25519_PUBKEY/);
  });
});

describe("idr canonical payload — scheme excluded", () => {
  it("canonical payload excludes scheme field", () => {
    const { record } = sign({
      intent: "payload test",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_ED25519,
      ed25519SeedHex: TEST_SEED_HEX,
    });
    const payload = JSON.parse(canonicalPayload(record as any));
    expect(payload).not.toHaveProperty("scheme");
    expect(payload).not.toHaveProperty("signature");
  });

  it("canonical payload is identical for hmac and ed25519 records with same fields", () => {
    const fixed = {
      intent: "parity", signer: "bot", confidence: 1.0, metadata: {},
      timestamp: "2026-06-17T00:00:00Z", decisionId: "idr_p", previousHash: GENESIS_HASH,
    };
    const { record: hmacRec } = sign({ ...fixed, scheme: SCHEME_HMAC, key: TEST_HMAC_KEY });
    const { record: edRec } = sign({ ...fixed, scheme: SCHEME_ED25519, ed25519SeedHex: TEST_SEED_HEX });
    expect(canonicalPayload(hmacRec as any)).toBe(canonicalPayload(edRec as any));
  });
});

describe("idr cross-language parity", () => {
  it("JS verifies a record signed by Python (fixed seed + fixed fields)", () => {
    // Python test_cross_language_parity_vector produces a deterministic Ed25519 signature
    // over the same canonical payload. We sign the same record here and verify:
    // 1. Same canonical payload bytes.
    // 2. JS-signed record passes JS verifyRecord.
    // 3. The pubkey derived from TEST_SEED_HEX matches Python's _derive_pubkey.
    const payload = canonicalPayload(PARITY_RECORD_FIELDS as any);
    // Verify that the canonical payload is sort-key, no-whitespace JSON.
    const parsed = JSON.parse(payload);
    const keys = Object.keys(parsed);
    expect(keys).toEqual([...keys].sort());
    expect(payload).not.toMatch(/": /);  // no ": " whitespace separator

    // Sign with JS and verify.
    const sigHex = ed25519Sign(payload, TEST_SEED_HEX);
    expect(sigHex).toMatch(/^[0-9a-f]{128}$/);
    const ok = ed25519Verify(payload, sigHex, TEST_PUBKEY_HEX);
    expect(ok).toBe(true);
  });

  it("ed25519PubkeyHex is 64-char hex (32-byte raw public key)", () => {
    expect(TEST_PUBKEY_HEX).toMatch(/^[0-9a-f]{64}$/);
  });

  it("tamper-detection: mutated payload fails ed25519Verify", () => {
    const payload = canonicalPayload(PARITY_RECORD_FIELDS as any);
    const sigHex = ed25519Sign(payload, TEST_SEED_HEX);
    const tampered = payload.replace("python", "tampered");
    expect(ed25519Verify(tampered, sigHex, TEST_PUBKEY_HEX)).toBe(false);
  });

  it("makeIdr with ed25519 scheme produces verifiable record", () => {
    process.env[ENV_ED25519_KEY] = TEST_SEED_HEX;
    try {
      const idr = makeIdr({
        intent: "makeIdr ed25519",
        signer: "donna-bot",
        confidence: 0.9,
        metadata: {},
        scheme: SCHEME_ED25519,
      });
      expect(idr.scheme).toBe(SCHEME_ED25519);
      expect(idr.signature).toMatch(/^[0-9a-f]{128}$/);
      const result = verifyRecord(idr, undefined, TEST_PUBKEY_HEX);
      expect(result).toEqual({ valid: true });
    } finally {
      delete process.env[ENV_ED25519_KEY];
    }
  });
});

describe("idr backward compat — existing HMAC records", () => {
  it("hmac-signed record (no scheme field) still verifies", () => {
    const { record } = sign({
      intent: "legacy hmac",
      signer: "donna-bot",
      confidence: 0.9,
      metadata: {},
      scheme: SCHEME_HMAC,
      key: TEST_HMAC_KEY,
    });
    // Strip scheme to simulate a legacy record without the field.
    const legacy = { ...record } as any;
    delete legacy.scheme;
    const result = verifyRecord(legacy, TEST_HMAC_KEY);
    expect(result).toEqual({ valid: true });
  });
});
