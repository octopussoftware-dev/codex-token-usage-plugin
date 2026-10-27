# Install Token Usage

Token Usage shows recorded tokens for local chats and subagents, grouped by project, with day/week/month comparisons and the account's remaining allowance.

## Requirements

- Apple silicon Mac (M1 or newer), running macOS 26 or later.
- A desktop Codex environment that supports local plugins.
- Local Codex history to display. Account allowance also requires an available Codex executable and a working Codex sign-in.

The binary includes its compression library. Users do not need Xcode, Python, Node.js, or Homebrew to run it. This build is ad-hoc signed; it is not Developer ID signed or notarized.

## Install from GitHub

Register the marketplace and install the plugin:

```sh
codex plugin marketplace add octopussoftware-dev/codex-token-usage-plugin
codex plugin add cost-calculator@cost-calculator-local
```

Alternatively, after registering the marketplace, open the desktop app's Plugins directory and install **Token Usage** from **Token Usage**. Restart the app if the marketplace does not appear. Start a new chat and ask **Open Token Usage.**

The repository includes the compiled plugin. No build step is needed.

## Install the marketplace ZIP

Download `token-usage-marketplace.zip` from [GitHub Releases](https://github.com/octopussoftware-dev/codex-token-usage-plugin/releases).

1. Extract `token-usage-marketplace.zip`. It contains a `marketplace` folder, including a hidden `.agents` folder. Keep the entire folder together in a lasting location.
2. In Terminal, register that folder using its actual path:

   ```sh
   codex plugin marketplace add "/absolute/path/to/marketplace"
   ```

3. Open the desktop app's Plugins directory, select **Token Usage**, and install **Token Usage**. Restart the desktop app if the marketplace does not appear. Alternatively, with a CLI that supports plugin installation:

   ```sh
   codex plugin add cost-calculator@cost-calculator-local
   ```

4. Start a new chat and ask: **Open Token Usage.**

The separate `cost-calculator-plugin.zip` contains only the plugin folder, for inclusion in an existing marketplace. Use the full marketplace ZIP for the steps above. The ZIP files do not install anything by themselves.

## Data access

The plugin reads local Codex history and token records. It uses Codex's account interface for allowance information. It does not change chats, models, reasoning effort, settings, or account limits. No API key or pricing table is required. Read `README.md` in the plugin folder for accounting and coverage details.

Installation follows the [official OpenAI packaging documentation](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli) and [CLI plugin commands](https://learn.chatgpt.com/docs/cli/reference#codex-plugin).
