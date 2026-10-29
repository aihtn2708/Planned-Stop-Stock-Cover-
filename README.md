# FMCG Factory Shutdown Impact Calculator

> **Plan your pre-build strategy before a factory shutdown — in seconds.**

A Python-powered tool (Flask API + CLI) with a self-contained interactive HTML calculator for FMCG supply-chain planners. Given a set of shutdown parameters and per-SKU data, it instantly computes:

- **Pre-build quantities** for each SKU
- **Shelf-life feasibility** (INFEASIBLE / TIGHT / OK / COVERED)
- **Capacity utilisation** across the pre-build window
- **Recommended actions** for each product

---

## Quick Start

### 1 — Interactive Web Calculator (no server needed)

Open `static/index.html` directly in any browser — no server, no install:

```bash
open static/index.html          # macOS
xdg-open static/index.html      # Linux
start static/index.html         # Windows
```

Edit parameters and SKU data live; results update instantly. Use the **"Start API Mode"** button to connect the UI to a running Flask server.

---

### 2 — Python CLI

**Requires Python 3.10+** (no extra dependencies for the core logic).

```bash
# Run with built-in sample data
python cli.py --sample

# Run with your own SKU CSV
python cli.py --skus data/skus_sample.csv

# Save results to CSV
python cli.py --skus data/skus_sample.csv --output results.csv

# Override any shutdown parameter
python cli.py --sample --shutdown-days 21 --prebuild-weeks 6

# Full JSON output (pipe to jq, etc.)
python cli.py --sample --json | jq '.sku_results[].status'

# Generate a blank CSV template to fill in
python cli.py --generate-csv my_skus.csv
```

---

### 3 — Flask Web API

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
# → http://localhost:5000
```

The server serves the HTML calculator at `/` and exposes a REST endpoint at `/api/calculate`.

---

## CSV Format

Your SKU file must be UTF-8 CSV with this header row:

```
id,name,daily_demand,current_stock,shelf_life_days,demand_multiplier,alt_supply,abc_class
```

| Column | Type | Required | Description |
|---|---|---|---|
| `id` | int | ✅ | Unique SKU identifier |
| `name` | str | ✅ | Product name |
| `daily_demand` | float | ✅ | Average units sold per calendar day |
| `current_stock` | float | ✅ | Units currently at factory / DC |
| `shelf_life_days` | int | ✅ | Days of remaining usable shelf life |
| `demand_multiplier` | float | ☐ | Seasonal/promo uplift (default `1.0`) |
| `alt_supply` | float | ☐ | Units from co-packer/sister plant (default `0`) |
| `abc_class` | str | ☐ | `A`, `B`, or `C` (default `B`) |

See `data/skus_sample.csv` for a worked example.

---

## Shutdown Parameters

| Parameter | CLI flag | Default | Description |
|---|---|---|---|
| `shutdown_days` | `--shutdown-days` | 14 | Hard-stop calendar days (zero output) |
| `ramp_down_days` | `--ramp-down-days` | 3 | Days before shutdown at reduced output |
| `ramp_up_days` | `--ramp-up-days` | 3 | Days after restart before full yield |
| `prebuild_weeks` | `--prebuild-weeks` | 4 | Weeks available to build stock ahead |
| `prod_days_per_week` | `--prod-days-per-week` | 5 | Production days per week in the pre-build window |
| `line_capacity_per_day` | `--line-capacity-per-day` | 10000 | *Incremental* units/day above normal demand production |
| `safety_stock_days` | `--safety-stock-days` | 7 | Days of demand cover to hold after restart |
| `downstream_buffer_days` | `--downstream-buffer` | 14 | Transit days factory gate → consumer (DC + retail) |

> **Effective Shutdown Days** = `ramp_down_days` + `shutdown_days` + `ramp_up_days`

---

## Status Classifications

| Status | Meaning | Action |
|---|---|---|
| 🟢 **COVERED** | Current stock sufficient — no pre-build needed | Monitor weekly in run-up |
| ✅ **OK** | Pre-build feasible; shelf life has comfortable headroom | Spread production across the window; enforce FIFO |
| ⚠️ **TIGHT** | Shelf life feasible but margin < 14 days | Delay production start; strict FIFO mandatory |
| 🔴 **INFEASIBLE** | Shelf life too short to pre-build from week 0 | Source from co-packer, or accept planned stockout with sign-off |

---

## Key Formulas

```
Effective Shutdown Days = ramp_down + shutdown_days + ramp_up

Demand to Cover = daily_demand × demand_multiplier × effective_days

Pre-Build Needed = max(0,  demand_to_cover
                          + safety_stock_days × adjusted_demand
                          − current_stock
                          − alt_supply)

Shelf Life Required = prebuild_weeks × 7
                    + effective_shutdown_days
                    + downstream_buffer_days

Production Days Required = total_prebuild_units / line_capacity_per_day

Capacity Utilisation % = prod_days_required / prod_days_available × 100
```

---

## REST API Reference

**Base URL:** `http://localhost:5000`

### `GET /api/health`

```json
{ "status": "ok" }
```

---

### `POST /api/calculate`

Calculate pre-build requirements for a list of SKUs.

**Request body:**

```json
{
  "params": {
    "shutdown_days": 14,
    "ramp_down_days": 3,
    "ramp_up_days": 3,
    "prebuild_weeks": 4,
    "prod_days_per_week": 5,
    "line_capacity_per_day": 10000,
    "safety_stock_days": 7,
    "downstream_buffer_days": 14
  },
  "skus": [
    {
      "id": 1,
      "name": "Product A",
      "daily_demand": 500,
      "current_stock": 3500,
      "shelf_life_days": 180,
      "demand_multiplier": 1.0,
      "alt_supply": 0,
      "abc_class": "A"
    }
  ]
}
```

**Response (200):**

```json
{
  "effective_shutdown_days": 20,
  "total_prebuild_units": 10000.0,
  "production_days_required": 1.0,
  "production_days_available": 20,
  "capacity_utilisation_pct": 5.0,
  "skus_at_risk": 0,
  "skus_infeasible": 0,
  "skus_total": 1,
  "sku_results": [
    {
      "sku_id": 1,
      "sku_name": "Product A",
      "abc_class": "A",
      "effective_days": 20,
      "adjusted_daily_demand": 500.0,
      "demand_to_cover": 10000.0,
      "safety_stock_units": 3500.0,
      "prebuild_needed": 10000.0,
      "shelf_life_required": 62.0,
      "shelf_life_available": 180,
      "shelf_margin": 118.0,
      "shelf_life_ok": true,
      "status": "OK",
      "action": "Pre-build 10,000 units spread across the 4-week pre-build window. Enforce FIFO rotation."
    }
  ]
}
```

---

## Project Structure

```
factory-shutdown-calculator/
├── calculator.py         # Core logic — pure Python, no external deps
├── app.py                # Flask web server + REST API
├── cli.py                # Command-line interface
├── requirements.txt      # Flask + flask-cors
├── requirements-dev.txt  # + pytest + pytest-cov
├── .gitignore
│
├── static/
│   └── index.html        # Standalone interactive HTML calculator
│
├── data/
│   └── skus_sample.csv   # 8-SKU sample dataset
│
└── tests/
    ├── __init__.py
    └── test_calculator.py  # 28 pytest tests
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=calculator --cov-report=term-missing
```

Expected output: **28 passed**.

---

## Use Cases

| Scenario | How to use |
|---|---|
| Quick planning check | Open `static/index.html`; adjust sliders; read KPIs |
| Batch analysis (many SKUs) | `python cli.py --skus your_data.csv --output results.csv` |
| Integrate into existing tools | `POST /api/calculate` from your planning system |
| Sensitivity testing | Change `--shutdown-days`, `--prebuild-weeks`, etc. on the CLI |
| Import as a library | `from calculator import calculate_all, ShutdownParams, SkuInput` |

---

## License

MIT — free to use, modify, and distribute.
