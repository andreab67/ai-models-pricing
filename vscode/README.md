# VSCode setup for Kilo Code + OpenRouter

## Recommended extensions

Drop this into your workspace's `.vscode/extensions.json` and accept the
prompt — VS Code will offer to install the missing ones.

```json
{
  "recommendations": [
    "kilocode.kilo-code",
    "rooveterinaryinc.roo-cline",
    "anthropic.claude-code",
    "github.copilot-chat",
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff",
    "esbenp.prettier-vscode",
    "dbaeumer.vscode-eslint",
    "bradlc.vscode-tailwindcss",
    "yzhang.markdown-all-in-one",
    "ms-azuretools.vscode-docker",
    "ms-kubernetes-tools.vscode-kubernetes-tools",
    "redhat.vscode-yaml",
    "tamasfe.even-better-toml",
    "eamodio.gitlens"
  ]
}
```

Kilo Code is the workflow driver. The other extensions cut friction for the
specific stacks in this repo.

## Workspace settings (suggested)

`.vscode/settings.example.json` is in this folder — copy to `.vscode/settings.json`
and adjust. Key bits:

- `kilo-code.openrouter.modelId` defaults to the cheapest passing model from
  this dashboard's top-10 (`/api/models/top?n=1`).
- `kilo-code.openrouter.byok` is `true` — point Kilo at your OpenRouter key
  directly so you only pay the 5% BYOK fee instead of 5.5% credit purchase.
  Or use a Kilo Pass token if you've subscribed.
- `editor.formatOnSave` + Ruff formatter for Python, Prettier for TS/TSX.

## Companion extension: `model-pricing-statusbar`

A small VS Code extension lives in `vscode/extension/`. It polls this
project's API (`/models/top?n=1`) and shows the current cheapest qualified
coding model + its $/Mtok in the status bar so you don't have to open the
dashboard.

### Install (dev install / sideload)

```bash
cd vscode/extension
npm install
npm run package     # produces model-pricing-statusbar-0.1.0.vsix

# install in your VS Code
code --install-extension model-pricing-statusbar-0.1.0.vsix
```

### Configure

`File → Preferences → Settings → Extensions → Model Pricing Status Bar`:

- `modelPricing.apiBaseUrl` — default `https://models.andrea-house.com/api`
- `modelPricing.refreshSeconds` — default `300`
- `modelPricing.includeKiloDiscount` — boolean, default `true`
- `modelPricing.kiloTier` / `modelPricing.kiloStreakMonths` — Kilo Pass assumptions

Click the status bar item to open the full dashboard.
