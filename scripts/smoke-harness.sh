#!/usr/bin/env bash
# scripts/smoke-harness.sh — end-to-end clone-to-running smoke harness for DONNA.
#
# Clones a fresh copy of the repo, runs documented setup, exercises all 6 scenarios
# with MOCK_PROVIDER=1 (no live API budget consumed), verifies every scenario emits
# a valid IDR chain entry.
#
# Two chain formats co-exist in this repo:
#   happi/1.1    — bin/notarise format, used by PROBAT.md and Scenario 5
#   donna/idr/1  — lib/docuseal_webhook.py format, used by Scenarios 1-4, 6
#
# The harness writes webhook-format IDRs to SMOKE.md (separate from PROBAT.md)
# so bin/notarise verify on PROBAT.md is never polluted by incompatible records.
# SMOKE.md integrity is verified by counting ```idr blocks (format-agnostic).
#
# Exit 0: all 6 scenarios passed.
# Exit 1: at least one scenario failed (failing name printed to stderr).
#
# Usage:
#   bash scripts/smoke-harness.sh
#   DONNA_REPO_URL=<url> bash scripts/smoke-harness.sh
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
WORK_DIR="/tmp/donna-smoke-$$"
CLONE_DIR="$WORK_DIR/donna"
LOG="$WORK_DIR/log.txt"
DONNA_NOTARISE_KEY="${DONNA_NOTARISE_KEY:-donna-public-demo-key-2026-05-08}"
MOCK_PROVIDER=1
export DONNA_NOTARISE_KEY MOCK_PROVIDER

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DONNA_REPO_URL="${DONNA_REPO_URL:-$REPO_ROOT}"

PASS=0; FAIL=0; FAILED_SCENARIOS=(); LAST_FAIL=""

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%H:%M:%S')] $*" | tee -a "$LOG"; }
fail() { echo "FAIL: $1" | tee -a "$LOG" >&2; FAILED_SCENARIOS+=("$1"); LAST_FAIL="$1"; FAIL=$((FAIL+1)); }
pass() { echo "PASS: $1" | tee -a "$LOG"; LAST_FAIL=""; PASS=$((PASS+1)); }

run_scenario() {
    local name="$1"; shift
    log "--- Scenario: $name ---"
    if "$@" >> "$LOG" 2>&1; then pass "$name"; else fail "$name"; fi
}

count_idr_entries() {
    grep -c '^\`\`\`idr' "$1" 2>/dev/null || echo 0
}

verify_idr_grew() {
    local chain="$1" before="$2" name="$3"
    local after; after=$(count_idr_entries "$chain")
    if [ "$after" -gt "$before" ]; then
        log "  IDR chain grew: $before → $after entries"; return 0
    fi
    log "  IDR chain did NOT grow (still $after) — Goodhart fail"; return 1
}

# ── Step 1: Fresh clone ───────────────────────────────────────────────────────
mkdir -p "$WORK_DIR"
log "Work dir: $WORK_DIR"
log "Log file: $LOG"
log "Cloning from: $DONNA_REPO_URL"
git clone --quiet "$DONNA_REPO_URL" "$CLONE_DIR" >> "$LOG" 2>&1
log "Clone complete."
cd "$CLONE_DIR"

# ── Step 2: Setup ─────────────────────────────────────────────────────────────
log "Setting up virtualenv..."
python3 -m venv .venv >> "$LOG" 2>&1
# shellcheck source=/dev/null
source .venv/bin/activate
if [ -f requirements.txt ]; then
    pip install --quiet -r requirements.txt >> "$LOG" 2>&1
    log "pip install complete (requirements.txt)."
elif [ -f client/requirements.txt ]; then
    pip install --quiet -r client/requirements.txt >> "$LOG" 2>&1
    log "pip install complete (client/requirements.txt)."
else
    log "No requirements.txt — skipping pip install."
fi

# ── Step 3: Verify bootstrap chain (happi/1.1 format) ────────────────────────
log "Verifying PROBAT.md bootstrap chain..."
if ! python3 bin/notarise verify --chain PROBAT.md >> "$LOG" 2>&1; then
    log "FATAL: bootstrap chain verification failed. Aborting."
    echo "FAIL: bootstrap-chain-verify" >&2; exit 1
fi
log "Bootstrap chain OK."

# Separate chain files:
#   PROBAT.md — happi/1.1, verified by bin/notarise (S5 only adds here via notarise sign)
#   SMOKE.md  — donna/idr/1, written by lib/docuseal_webhook.append_to_chain (S1,S2,S3,S4,S6)
NOTARISE_CHAIN="PROBAT.md"
SMOKE_CHAIN="SMOKE.md"
TIME_CHAIN="time-entries/$(date -u '+%Y-%m-%d').jsonl"

# ── Scenario 1: Voice notes → action ──────────────────────────────────────────
before=$(count_idr_entries "$SMOKE_CHAIN")
run_scenario "S1-voice-notes" bash -c "
    python3 examples/voice/record_intent.py --out /tmp/donna-smoke-$$.wav &&
    DONNA_CHAIN_PATH=$SMOKE_CHAIN python3 examples/voice/route_intent.py \
        --audio /tmp/donna-smoke-$$.wav --emit-idr
"
if [ "$LAST_FAIL" != "S1-voice-notes" ]; then
    verify_idr_grew "$SMOKE_CHAIN" "$before" "S1-voice-notes" || fail "S1-idr-verify"
fi

# ── Scenario 2: Time entry from voice ─────────────────────────────────────────
mkdir -p time-entries
run_scenario "S2-time-entry" bash -c "
    python3 examples/time-entry/voice_to_entry.py \
        --matter-list examples/time-entry/sample-matters.json --emit-idr
"
if [ "$LAST_FAIL" != "S2-time-entry" ]; then
    after_time=$(count_idr_entries "$TIME_CHAIN")
    if [ "$after_time" -gt 0 ]; then
        log "  Time-entry chain: $after_time entries"
    else
        fail "S2-idr-verify"
    fi
fi

# ── Scenario 3: Document ingestion ────────────────────────────────────────────
before=$(count_idr_entries "$SMOKE_CHAIN")
run_scenario "S3-doc-ingest" bash -c "
    DONNA_CHAIN_PATH=$SMOKE_CHAIN python3 examples/doc-ingest/ingest.py \
        --file examples/doc-ingest/sample-contract.pdf --emit-idr &&
    DONNA_CHAIN_PATH=$SMOKE_CHAIN python3 examples/doc-ingest/query.py \
        --question 'what is the termination clause?' --emit-idr
"
if [ "$LAST_FAIL" != "S3-doc-ingest" ]; then
    verify_idr_grew "$SMOKE_CHAIN" "$before" "S3-doc-ingest" || fail "S3-idr-verify"
fi

# ── Scenario 4: Matter summaries ──────────────────────────────────────────────
before=$(count_idr_entries "$SMOKE_CHAIN")
run_scenario "S4-matter-summary" bash -c "
    DONNA_CHAIN_PATH=$SMOKE_CHAIN python3 examples/matter-summary/summarise.py \
        --matter examples/matter-summary/sample-matter/ --emit-idr
"
if [ "$LAST_FAIL" != "S4-matter-summary" ]; then
    verify_idr_grew "$SMOKE_CHAIN" "$before" "S4-matter-summary" || fail "S4-idr-verify"
fi

# ── Scenario 5: IDR audit chain (happi/1.1 — bin/notarise native) ────────────
# Use append_to_chain-compatible emission then verify with bin/notarise.
# NOTE: notarise `sign` prints JSON to stdout only; we use lib/docuseal_webhook
# for consistency but write to NOTARISE_CHAIN only after format alignment.
# Instead: emit a notarise-native record via bin/notarise sign + parse + append.
before_notarise=$(count_idr_entries "$NOTARISE_CHAIN")
run_scenario "S5-idr-chain" bash -c "
    python3 bin/notarise sign \
        --intent 'Smoke harness: S5 manual IDR entry' \
        --signer donna-smoke-harness \
        --confidence 1.0 \
        --previous-hash \$(python3 -c \"
import sys, json, hashlib
text = open('$NOTARISE_CHAIN').read()
blocks = []
in_b = False; buf = []
for line in text.splitlines():
    if line.strip().startswith('\\\`\\\`\\\`idr'): in_b=True; buf=[]
    elif in_b and line.strip().startswith('\\\`\\\`\\\`'): in_b=False; blocks.append(''.join(buf))
    elif in_b: buf.append(line+'\n')
if not blocks: print('0'*64)
else:
    last = json.loads(blocks[-1])
    last.pop('signature', None)
    canon = json.dumps(last, sort_keys=True, separators=(',',':')).encode()
    print(hashlib.sha256(canon).hexdigest())
\") >> /tmp/donna-smoke-s5-idr-$$.json 2>/dev/null &&
    python3 -c \"
import json, sys
data = json.load(open('/tmp/donna-smoke-s5-idr-$$.json'))
block = '\\\`\\\`\\\`idr\n' + json.dumps(data, indent=2, sort_keys=True) + '\n\\\`\\\`\\\`\n'
open('$NOTARISE_CHAIN', 'a').write('\n' + block)
print('IDR appended to $NOTARISE_CHAIN:', data['signature'][:16] + '...')
\" &&
    python3 bin/notarise verify --chain $NOTARISE_CHAIN
"
if [ "$LAST_FAIL" != "S5-idr-chain" ]; then
    verify_idr_grew "$NOTARISE_CHAIN" "$before_notarise" "S5-idr-chain" || fail "S5-idr-verify"
fi

# ── Scenario 6: Sign with receipt (DocuSeal mock) ────────────────────────────
before=$(count_idr_entries "$SMOKE_CHAIN")
run_scenario "S6-docuseal-sign" bash -c "
    DONNA_CHAIN_PATH=$SMOKE_CHAIN python3 -c \"
import sys, os, time
sys.path.insert(0, '.')
from lib.docuseal_webhook import append_to_chain, event_to_idr
from pathlib import Path
event = {
    'event_type': 'submission.created',
    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'data': {
        'submission_id': 'smoke-sign-99999',
        'submitter': {'email': 'lawyer@firm.example', 'name': 'Senior Counsel'},
        'submission': {'id': 99999, 'template_id': 88888},
    },
}
idr = event_to_idr(event)
chain_path = Path(os.environ.get('DONNA_CHAIN_PATH', 'SMOKE.md'))
record_hash = append_to_chain(idr, chain_path)
print('IDR signature:', idr['signature'])
print('Submission mock: 99999 | Template mock: 88888')
print('Chain head:', str(chain_path), '(hash', record_hash[:8] + '...)')
\"
"
if [ "$LAST_FAIL" != "S6-docuseal-sign" ]; then
    verify_idr_grew "$SMOKE_CHAIN" "$before" "S6-docuseal-sign" || fail "S6-idr-verify"
fi

# ── Final chain integrity (happi/1.1 chain only) ──────────────────────────────
log "--- Final PROBAT.md integrity check ---"
if python3 bin/notarise verify --chain "$NOTARISE_CHAIN" >> "$LOG" 2>&1; then
    log "PROBAT.md integrity: OK"
else
    log "PROBAT.md integrity: FAILED"
    fail "final-chain-integrity"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log ""
log "============================="
log "  DONNA smoke harness done"
log "  Passed: $PASS  Failed: $FAIL"
log "  Log:    $LOG"
log "============================="

if [ "$FAIL" -gt 0 ]; then
    echo "FAILED scenarios: ${FAILED_SCENARIOS[*]}" >&2; exit 1
fi
exit 0
