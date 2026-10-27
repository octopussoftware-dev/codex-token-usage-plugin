# Cost Calculator

This workspace is a separate plugin from ChatGPT Stats / Codex Agent Status. Keep changes inside this project unless the user asks to work on the other plugin.

- Plugin: `cost-calculator`; MCP server: `cost_calculator`; marketplace: `cost-calculator-local`.
- Local preview: `python3 Tools/preview.py`, default port **61960**. Do not stop another plugin's server to free a port; use `--port` instead.
- Build with `./build.sh`, then check the package with `python3 Tests/mcp_test.py`.
- Scope: read-only token usage, parent totals and per-agent details. Never count cumulative or inherited usage twice. Label missing data explicitly. Count all recorded models without a pricing dependency; do not add currency estimates.
- Accounting fixtures: `python3 Tests/cost_test.py`; token accounting is documented in README.md.
