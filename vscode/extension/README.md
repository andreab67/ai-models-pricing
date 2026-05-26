# model-pricing-statusbar

Tiny VS Code extension. Polls `models.andrea-house.com/api/models/top?n=1`
every N seconds and displays the cheapest qualified coding model + its
$/Mtok in the status bar. Optionally applies the Kilo Pass discount.

## Build

```bash
npm install
npm run compile
npm run package     # → model-pricing-statusbar-0.1.0.vsix
code --install-extension model-pricing-statusbar-0.1.0.vsix
```

## Settings

| Setting                              | Default                                  |
|--------------------------------------|------------------------------------------|
| `modelPricing.apiBaseUrl`            | `https://models.andrea-house.com/api`    |
| `modelPricing.refreshSeconds`        | `300`                                    |
| `modelPricing.includeKiloDiscount`   | `true`                                   |
| `modelPricing.kiloTier`              | `pro`                                    |
| `modelPricing.kiloStreakMonths`      | `8`                                      |

Click the status bar item to open the dashboard.
