# Token Usage

An independent local Codex plugin showing tokens used by chats and their task subagents, plus the account’s remaining usage allowance. The package retains its `cost-calculator` identity; no currency estimates are calculated.

## Install

Requires an Apple silicon Mac running macOS 26 or later and a Codex desktop environment with local plugin support.

```sh
codex plugin marketplace add octopussoftware-dev/codex-token-usage-plugin
codex plugin add cost-calculator@cost-calculator-local
```

Then start a new chat and ask **Open Token Usage.** You can also install **Token Usage** from the **Token Usage** marketplace in the app's Plugins directory. The repository includes the compiled plugin, so installation does not require developer tools.

See [INSTALL.md](INSTALL.md) for ZIP installation, compatibility, and data access. Download the installation bundle and checksums from [Releases](https://github.com/octopussoftware-dev/codex-token-usage-plugin/releases).

## Dashboard

The main list groups parent chats by project, showing a chat count and token subtotal for each project. Turn off **Group by project** above the list to show one list of chats, with each chat’s project beneath its title. Projects are identified by the chat’s recorded working folder, keeping folders with the same name separate. Chats without a folder appear under Other chats.

The two-button selector above the list offers **Most recent** (latest activity first, the default) and **Token usage** (largest recorded total first), with the selected option highlighted. With grouping on, projects rank by the latest activity among their loaded chats or the sum of those chats’ tokens, including subagents. Chats within each project use the same sort order. With grouping off, the sort applies to individual parent chats. Token ties fall back to recency, then stable chat/project identity. Sorting covers the loaded matching chats; Load more expands the comparison and can change project positions. Incomplete totals rank by their recorded tokens and remain visibly marked as partial. Grouping and sorting preserve filters, totals and detail navigation, and are remembered across reloads when local storage is available. The compact list hides its scrollbar by default and reveals it when you hover over the list or focus a list control. Space for the scrollbar stays reserved to avoid a layout shift. A soft bottom fade with a **More below** button appears whenever additional rows are below the viewport. Clicking it or pressing Enter or Space scrolls down with some overlap and focuses the list for continued keyboard scrolling. The button captures clicks so they cannot open a chat underneath it, respects reduced-motion preferences, and disappears at the bottom or when all results fit.

Choose Day (last 24 hours, the default), Week (last 7 days), Month (last 30 days), or All time. Opening or reloading the dashboard starts with Day selected. These are rolling windows measured from each refresh, using individual usage-record timestamps. The chosen period applies to project subtotals, chat totals, and every agent in the detail view. Bounded views include chats used in either the selected or previous window, plus chats with incomplete usage. Subagent usage in either window can bring an older parent chat into the list.

An up/down percentage compares the selected window with the immediately preceding window of equal length: the previous 24 hours, 7 days, or 30 days. Both windows share one snapshot time and do not overlap. Change is `(current − previous) / previous × 100`. Project and overall changes use summed tokens for the same loaded chats, not an average of chat percentages. Chats with previous usage and zero current usage remain visible with a 100% decrease. The overall token total hides its comparison when the previous window has no recorded tokens. Chat and project rows also hide **New** when the previous total was zero. In the detail view, **New** means the previous total was zero; **No change** means both totals are equal. If either total is incomplete, the percentage is unavailable. All time has no comparison. Hover over a change to see the previous and current token counts.

Each chat total includes its own tokens plus every linked task subagent, recursively, including archived descendants. Open a row for individual agent tokens, model and reasoning effort, last recorded activity and progress text, and an expandable token breakdown with exact counts. Search matches parent chat titles and projects. Project subtotals and the overall total cover the currently loaded matching chats: initially 20 parent chats; Load more adds up to 200. They are not all-account project totals. All time covers the full recorded history of these loaded chats.

The dashboard refreshes every five seconds while visible. Activity and model/effort show the latest recorded state, which may be outside the selected period. Activity is not a live connection check. An old unfinished turn is marked Status unknown. Escape or All chats returns to the list with its period, search and scroll position intact.

## Account allowance

The overview places a small allowance readout to the right of the larger token total: **67% left**, with **Weekly allowance** beneath it. A short vertical divider and spacing separate it from the token count; the layout tightens on narrow screens. Hover over the readout for the reset countdown and exact time in your local timezone. These limits belong to the local Codex sign-in and are shared across chats. They do not change with the selected token period, search, grouping or pagination. Windows are labeled by their actual duration (for example, Weekly or 5-hour), not by whether the server calls them primary or secondary. Additional limit windows stack in the same area. Stale or unavailable readings expose further details on hover. Brief chat/project counts appear below the list controls, separate from the top metrics; their tooltip explains subagent inclusion. The comparison value stays beside the total, with its period and exact values in the tooltip.

The native reader calls the documented [`account/rateLimits/read`](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt) method through `codex app-server`, using Codex’s existing sign-in. Remaining allowance is `clamp(100 − usedPercent, 0, 100)`. Prefer `rateLimitsByLimitId` when present; fall back to the legacy single limit. Null or missing percentages/reset times stay unavailable. No remaining-token count is inferred, and credits or a missing limit are never treated as unlimited usage.

With Live enabled, account allowance refreshes once a minute while visible; manual Refresh requests a fresh reading. The server also caches readings for 60 seconds. Requests run separately from local token accounting, with a 15-second timeout. A failed refresh retains any previous reading as **Last known**; readings older than two minutes are also labeled. Once a reported reset time passes, the previous percentage is hidden until a new reading arrives. No reset, purchase, login, chat or turn is initiated.

Account allowance requires a compatible local Codex executable and an existing sign-in with access to account limits. The reader searches absolute PATH entries, known Codex app locations, and common CLI locations. Set `COST_CALCULATOR_CODEX_BIN` to an absolute executable path to override discovery; an invalid override fails explicitly. `CODEX_HOME` is inherited. Without a compatible executable, sign-in or connection, token accounting still works and allowance is marked unavailable.

## Token accounting

Values come directly from recorded token usage. There is no pricing table, currency conversion, pricing refresh, or model-price dependency. Compact totals are rounded for readability; tooltips and agent breakdowns show exact counts. A `+` marks an incomplete total, and `—` means usage is unavailable.

- Count response-local `token_usage_record.usage`, deduplicated by response ID and restricted to the owning thread. Ignore inherited/cumulative thread totals in forks.
- Fall back to legacy `last_token_usage` when a turn has no canonical response records; deduplicate repeated cumulative totals across turn boundaries.
- Deduplicate before filtering by time. Repeated updates to a response retain its original valid timestamp. Undated usage counts only in All time; bounded periods exclude it and mark the agent's usage as incomplete. Future timestamps are excluded from bounded periods. Catalog updates and file modification times only narrow which logs to scan; they do not determine token totals.
- Compute both windows from the same deduplicated responses and observation time. The previous window excludes its upper boundary, which belongs to the current window. Missing or undated records make the comparison unavailable. Apply search and pagination to the union of chats with usage in either window, then sum both totals over exactly those loaded chats.
- Total tokens are input plus output. Cache reads and writes are already part of input; reasoning is already part of output. Neither is added twice. Context processed again on later requests counts again.
- Preserve model changes in historical responses. Latest recorded model/effort is displayed per agent; mixed-model token counts are available in its breakdown.
- All recorded models count, including new or unknown model names.
- Missing logs produce explicit partial totals. Unlinked subagents are counted in coverage and excluded from parent totals. System approval-review and voice-helper sessions are excluded.

## Development

```sh
./build.sh
python3 Tests/mcp_test.py
python3 Tests/cost_test.py
python3 Tests/range_test.py
node Tests/comparison_test.js
python3 Tests/allowance_test.py
node Tests/allowance_ui_test.js
python3 Tools/preview.py
```

The preview binds only to `127.0.0.1`, defaults to **port 61960**, and exits safely if the port is occupied. Override with `--port`. Rebuild and restart the preview after source changes. Stop it with Control-C.

The native package targets Apple silicon macOS 26, matching the locally installed static zstd library. Development requires Xcode command-line tools, Python 3, Node.js for UI tests, and zstd (`COST_CALCULATOR_ZSTD_PREFIX` overrides `/opt/homebrew/opt/zstd`). The packaged plugin statically includes the zstd decoder and license; local token accounting has no Python, Node.js or Homebrew runtime dependency. Account allowance additionally uses the local Codex executable. Compressed logs are decoded in memory with a 512 MiB per-file bound. Larger or invalid logs produce a partial-usage warning.

Tests use a temporary Codex profile and isolated fixtures: nested and archived subagents, compressed logs, duplicate records, model changes, exact token categories, fork isolation, legacy counters, missing logs, unknown models, safe activity extraction, incremental appends, truncated files, and protocol validation. Time-window fixtures cover adjacent windows, each cutoff, previous-only chats and descendants, undated/future records, filtering before pagination, and matching list/detail totals. UI accounting tests cover increases, decreases, zero baselines, incomplete data and weighted project changes. Tests also check that responses contain no pricing or dollar fields. They never start or change real chats.

Allowance tests use a fake Codex executable and no real account/network access. They check multiple and legacy windows, percentage bounds, missing and invalid fields, cache/force refresh, stale data, process exit/timeout cleanup, concurrent local reads, sanitized output, and the read-only protocol. UI fixtures cover reset countdowns, unknown limits, zero remaining allowance and expired windows.

## Isolation and data

- Plugin: `cost-calculator`; marketplace: `cost-calculator-local`.
- MCP server: `cost_calculator`; UI: `ui://cost-calculator/calculator-v1.html`.
- Preview port: `61960`; this project is separate from ChatGPT Stats.

The plugin reads the local Codex catalog in read-only mode and session logs under `CODEX_HOME` (default `~/.codex`). It supports `.jsonl` and archived `.jsonl.zst` logs. It does not contact the ChatGPT Stats server, write to the Codex database, send messages, change settings, or start agents. It exposes concise assistant progress text and tool activity labels; analysis/reasoning text, tool arguments, credentials and full transcripts are not returned. Token accounting remains local. For account allowance, Codex contacts its own account service using its existing authentication; the plugin does not read credential files or return raw account responses, account identifiers, emails, credits or error details. Session titles and progress text are rendered as text, never executable markup or instructions.

MCP tools: `show_calculator`, `list_usage` (`query`, `limit`, `range`), `read_usage_detail` (`thread_id`, `range`), and `read_allowance` (`refresh`, optional boolean). The optional `range` is `all`, `day`, `week`, or `month` and defaults to `all` for direct tool calls; the UI explicitly requests `day` on opening. Token responses include `period`, `previousPeriod`, `total`, `previousTotal`, and per-chat/per-agent `previousUsage`. Previous fields are null for All time. Each period includes start/end timestamps and whether the upper bound is exclusive. Allowance responses include `status`, `scope`, `source`, `observedAt`, `message`, and normalized `windows`. The UI uses the same packaged tools in the native host and development preview.

## Packaging

Run `./build.sh` to generate:

- `build/token-usage-marketplace.zip`: the full installation bundle, including the marketplace catalog, plugin, and installation guide.
- `build/cost-calculator-plugin.zip`: the plugin alone, for an existing marketplace.
- `build/marketplace`: the unpacked local marketplace.
- `build/SHA256SUMS`: SHA-256 checksums for both ZIPs.

The root `.agents/plugins/marketplace.json` makes this repository a GitHub marketplace. Each build also refreshes `plugins/cost-calculator`, the ready-to-install package checked into the repository. `Plugin` and `Sources` contain the editable source; commit the refreshed package alongside source changes when publishing a release.

See [INSTALL.md](INSTALL.md) for compatibility and installation steps. Both archives omit macOS resource-fork and extended-attribute sidecar files. To verify downloaded archives, place them beside `SHA256SUMS` and run `shasum -a 256 -c SHA256SUMS` in that folder.

Previewing and building do not install the plugin. Register this project’s generated marketplace and install `cost-calculator@cost-calculator-local` separately when ready. For development, from this project directory:

```sh
codex plugin marketplace add "$PWD/build/marketplace"
```

Then install **Token Usage** from **Token Usage** in the desktop app's Plugins directory and start a new chat.
