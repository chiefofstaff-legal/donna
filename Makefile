# DONNA — top-level Makefile.
#
# One target per workflow. Pure stdlib; works with system make on macOS/Linux.

.PHONY: help demo verify test clean

help:
	@echo "DONNA · Decision-Oriented Network Notarisation for Attorneys"
	@echo ""
	@echo "Targets:"
	@echo "  make demo     -- run the 60-second end-to-end demo"
	@echo "  make verify   -- verify the demo audit chain (after make demo)"
	@echo "  make test     -- run the test suite (pytest)"
	@echo "  make clean    -- remove generated chain + caches"

demo:
	@DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08 python3 demo/demo.py

verify:
	@DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08 python3 bin/notarise verify --chain demo/chain.md

test:
	@python3 -m pytest tests/ -q

clean:
	@rm -f demo/chain.md
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
