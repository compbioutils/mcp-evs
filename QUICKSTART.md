# Quickstart: ask NCIt questions from your AI client

This gets you from a fresh clone to asking "what is the NCIt code for adenocarcinoma?" in a
chat client, in about five minutes. The server only exposes tools. Your client's model reads
the question, picks a tool, and writes the answer, citing the NCIt code and release.

## 1. Install

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/) (`brew install uv` or `pip install uv`).

```bash
git clone https://github.com/compbioutils/mcp-evs.git && cd mcp-evs
uv venv && uv pip install -e '.[dev]'
cp .env.example .env        # defaults work as is: EVS-only profile, no credentials needed
```

## 2. Check it works without a client

```bash
uv run --no-sync python scripts/call_tool.py --mode live evs_lookup_concept identifier=adenocarcinoma
```

You should see `"code": "C2852"` and `"release": "26.10d"` (or whichever NCIt release is current).

## 3. Connect a client

The server runs over **stdio**: the client starts it as a subprocess, so there's nothing to
start yourself, and it prints no URL.

### VS Code (Copilot) and Claude Code

The repo root has a [`.mcp.json`](.mcp.json) that both read. Open the folder, trust the
`evsCadsr` server when prompted, and in Copilot Chat switch to **Agent** mode and make sure the
`evsCadsr` tools are enabled in the tools picker. In Claude Code, run `claude` in the repo and
approve the project server.

### Claude Desktop

Claude Desktop needs absolute paths. Add this to
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows), then restart it:

```json
{
  "mcpServers": {
    "evsCadsr": {
      "command": "/absolute/path/to/mcp-evs/.venv/bin/evs-cadsr-mcp",
      "args": ["serve", "--transport", "stdio"],
      "env": { "ECM_PROFILE": "evs-only" }
    }
  }
}
```

### Any client, over HTTP

```bash
uv run --no-sync evs-cadsr-mcp serve --transport http --port 8000
curl -s http://127.0.0.1:8000/healthz
```

Point the client at `http://127.0.0.1:8000/mcp` (for example `{"type": "http", "url": "http://127.0.0.1:8000/mcp"}`
in `.mcp.json`). The server binds to `127.0.0.1` and refuses any other address without JWT auth;
see [SECURITY.md](SECURITY.md).

## 4. Ask questions

Try these. Each should come back with an NCIt code and the release it came from.

- "What is the NCIt code for adenocarcinoma?" → **C2852**
- "What is NSCLC, and what is it a kind of?" → **C2926**, under Lung Carcinoma
- "What are the allowed SDTM values for Sex?" → codelist **C66731** (Female, Intersex, Male, Unknown)
- "Which drugs target EGFR L858R?" → osimertinib, lazertinib and 15 more
- "Which of C3224, C28327 and C9324 are retired, and what replaced them?"

More worked examples are in [docs/evs mcp use cases.md](docs/evs%20mcp%20use%20cases.md) and
[docs/tools/](docs/tools/).

## 5. caDSR tools (optional)

The `cadsr_*` and `map_*` tools need `ECM_PROFILE=unified`. Some also need caDSR credentials
(`ECM_CADSR_USERNAME` and `ECM_CADSR_PASSWORD` in `.env`, never in tracked files). Use the caDSR
stage environment for testing. Worked examples of mapping between NCIt and caDSR are in
[docs/tools/map-tools.md](docs/tools/map-tools.md).

## Troubleshooting

- **No tools in the client:** run step 2 first. If that works, check that the client's working
  directory is the repo root (`uv run` finds the project from there), or use the absolute-path
  form shown for Claude Desktop.
- **`release_not_available`:** EVS serves only the last few monthly NCIt releases. Drop
  `ECM_RELEASE_PIN` or pick a release listed by `uv run --no-sync evs-cadsr-mcp releases`.
- **Logs:** they go to stderr; your client shows them in its MCP server log view.
