import { describe, it, expect } from "vitest";
import { makeIdr, computeIdrRef, canonicalPayload, IdrPayload } from "../src/idr.js";

// Wave-F harmonization tests: makeIdr now attaches a canonical happi-lib v1.1
// idr_ref (sha256 of canonical_payload + empty events). These tests verify
// determinism, chain-verifiability, and graceful happi.md fallback.

const SAMPLE_PAYLOAD: IdrPayload = {
  confidence: 0.9,
  decision_id: "idr_fixed_001",
  intent: "test:parity",
  metadata: { tool: "test" },
  previous_hash: "0".repeat(64),
  protocol: "happi/1.1",
  signer: "donna-bot",
  timestamp: "2026-01-01T00:00:00Z",
};

describe("idr happi-lib v1.1 parity", () => {
  it("computeIdrRef produces deterministic sha256 over 100 calls with identical input", () => {
    const envelope = canonicalPayload(SAMPLE_PAYLOAD);
    const first = computeIdrRef(envelope, "").sha256;
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    for (let i = 0; i < 100; i++) {
      expect(computeIdrRef(envelope, "").sha256).toBe(first);
    }
  }, 15000);

  it("computeIdrRef produces different sha256 for different envelopes", () => {
    const a = computeIdrRef(canonicalPayload(SAMPLE_PAYLOAD), "").sha256;
    const b = computeIdrRef(canonicalPayload({ ...SAMPLE_PAYLOAD, intent: "different" }), "").sha256;
    expect(a).not.toBe(b);
  });

  it("makeIdr returns idr_ref with 64-char hex sha256", () => {
    const idr = makeIdr({
      intent: "wave-f:test",
      signer: "donna-bot",
      confidence: 0.5,
      metadata: { tool: "test" },
    });
    expect(idr.idr_ref).toBeDefined();
    expect(idr.idr_ref!.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(idr.idr_ref!.cid).toBeNull();
    expect(Array.isArray(idr.idr_ref!.model_versions)).toBe(true);
    expect(idr.idr_ref!.block_anchor).toBeNull();
  });

  it("makeIdr idr_ref.sha256 chain-verifies against the recorded payload", () => {
    // Re-emit cmd:idr.emit on the canonical payload of a recorded IDR;
    // the resulting sha256 must match the originally attached idr_ref.sha256.
    const idr = makeIdr({
      intent: "chain-verify",
      signer: "donna-bot",
      confidence: 0.7,
      metadata: { tool: "test" },
    });
    // Reconstruct the IdrPayload-only view (strip signature + idr_ref).
    const { signature: _sig, idr_ref: _ref, ...payloadOnly } = idr;
    const reverified = computeIdrRef(canonicalPayload(payloadOnly), "");
    expect(reverified.sha256).toBe(idr.idr_ref!.sha256);
  });

  it("computeIdrRef returns valid IdrRef when HAPPI_MD_PATH points at a missing file (local fallback)", () => {
    const saved = process.env["HAPPI_MD_PATH"];
    process.env["HAPPI_MD_PATH"] = "/tmp/definitely-not-a-real-happi-md-path-2026.md";
    try {
      const ref = computeIdrRef("{}", "");
      // Local fallback path always populates a valid 64-char hex sha256.
      expect(ref.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(ref.cid).toBeNull();
    } finally {
      if (saved !== undefined) process.env["HAPPI_MD_PATH"] = saved;
      else delete process.env["HAPPI_MD_PATH"];
    }
  });

  it("local sha256 matches direct node:crypto computation (parity ground-truth)", async () => {
    // Force the local path by pointing happi.md at a missing file.
    const saved = process.env["HAPPI_MD_PATH"];
    process.env["HAPPI_MD_PATH"] = "/tmp/missing-happi-md.md";
    try {
      const { createHash } = await import("node:crypto");
      const envelope = '{"hello":"world"}';
      const events = "";
      const expected = createHash("sha256").update(envelope + events, "utf8").digest("hex");
      expect(computeIdrRef(envelope, events).sha256).toBe(expected);
    } finally {
      if (saved !== undefined) process.env["HAPPI_MD_PATH"] = saved;
      else delete process.env["HAPPI_MD_PATH"];
    }
  });
});
