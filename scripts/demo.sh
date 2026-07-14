#!/usr/bin/env bash
# Conduit demo — three beats, each proving one pillar. Drives the real server
# and CLI; safe to run for a Loom. Run from the repo root:  bash scripts/demo.sh
#
#   Beat 1  Security is real   — a path traversal and a secret file are refused live
#   Beat 2  Discovery is real  — the assistant discovers tools and answers a question
#   Beat 3  Model-agnostic     — the same CLI, swapped to a fully-local model
#
# Providers: Beat 2 uses $LLM_PROVIDER (default gemini; needs GOOGLE_API_KEY in
# .env). Beat 3 forces ollama (needs `ollama serve` + $OLLAMA_MODEL pulled).

set -uo pipefail
cd "$(dirname "$0")/.."

PROVIDER="${LLM_PROVIDER:-gemini}"
OLLAMA_MODEL="${OLLAMA_MODEL:-mistral}"

echo
echo "════════════════════════════════════════════════════════════════"
echo "  BEAT 1 — Security is real (refused live, no LLM involved)"
echo "════════════════════════════════════════════════════════════════"
uv run python - <<'PY' 2>/dev/null
import asyncio
from conduit.host.client import MCPCodebaseClient, conduit_server_params

async def main():
    async with MCPCodebaseClient(conduit_server_params("./sample-repo")) as c:
        for path in ["../../etc/passwd", ".env", "service.key", "src/auth.py"]:
            r = await c.call_tool("read_file", {"path": path})
            if r.isError:
                msg = r.content[0].text.split(":", 2)[-1].strip()
                print(f"  read_file {path!r:20} ->  REFUSED — {msg[:72]}")
            else:
                print(f"  read_file {path!r:20} ->  ok ({r.structuredContent['total_lines']} lines)")

asyncio.run(main())
PY

echo
echo "════════════════════════════════════════════════════════════════"
echo "  BEAT 2 — Discovery is real (assistant drives discovered tools)  [$PROVIDER]"
echo "════════════════════════════════════════════════════════════════"
uv run conduit --provider "$PROVIDER" \
  "Which file defines the authenticate function, and what does it return on failure? Cite the file and line." 2>/dev/null

echo
echo "════════════════════════════════════════════════════════════════"
echo "  BEAT 3 — Model-agnostic (same CLI, fully local via Ollama)"
echo "════════════════════════════════════════════════════════════════"
OLLAMA_MODEL="$OLLAMA_MODEL" uv run conduit --provider ollama \
  "List the functions and classes defined in src/payments.py" 2>/dev/null

echo
echo "Done. The server refused a traversal + secrets, the assistant discovered"
echo "and drove the tools, and the same CLI answered via a local model."
