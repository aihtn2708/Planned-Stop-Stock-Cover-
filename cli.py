"""
factory_shutdown_calculator.cli
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Command-line interface for batch calculation via CSV input.

Usage:
    python cli.py --help
    python cli.py --skus data/skus.csv
    python cli.py --skus data/skus.csv --shutdown-days 21 --prebuild-weeks 6
    python cli.py --skus data/skus.csv --output results.csv

CSV format (header row required):
    id,name,daily_demand,current_stock,shelf_life_days,demand_multiplier,alt_supply,abc_class
    1,Product A,500,3500,180,1.0,0,A
    2,Product B,200,1200,60,1.2,0,B
"""

from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

from calculator import ShutdownParams, SkuInput, calculate_all


SAMPLE_CSV = """id,name,daily_demand,current_stock,shelf_life_days,demand_multiplier,alt_supply,abc_class
1,Product A,500,3500,180,1.0,0,A
2,Product B,200,1200,60,1.2,0,B
3,Product C,1000,5000,365,1.0,2000,A
4,Product D,800,4000,90,1.0,0,A
5,Product E,50,800,365,1.0,0,C
"""

STATUS_ICONS = {
    "OK":         "✅",
    "COVERED":    "🟢",
    "TIGHT":      "⚠️ ",
    "INFEASIBLE": "🔴",
}


def load_skus_from_csv(path: Path) -> list[SkuInput]:
    skus = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            try:
                skus.append(SkuInput(
                    id=               int(row["id"]),
                    name=             row["name"].strip(),
                    daily_demand=     float(row["daily_demand"]),
                    current_stock=    float(row["current_stock"]),
                    shelf_life_days=  int(row["shelf_life_days"]),
                    demand_multiplier=float(row.get("demand_multiplier", 1.0)),
                    alt_supply=       float(row.get("alt_supply", 0)),
                    abc_class=        row.get("abc_class", "B").strip().upper(),
                ))
            except (KeyError, ValueError) as exc:
                print(f"  ⚠  Row {i} skipped — {exc}", file=sys.stderr)
    return skus


def write_results_csv(result, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "SKU ID", "SKU Name", "ABC", "Eff. Days",
            "Demand to Cover", "Safety Stock", "Pre-Build Needed",
            "Shelf Life Req. (d)", "Shelf Life Avail. (d)", "Margin (d)",
            "Status", "Action",
        ])
        for r in result.sku_results:
            writer.writerow([
                r.sku_id, r.sku_name, r.abc_class, r.effective_days,
                round(r.demand_to_cover), round(r.safety_stock_units),
                round(r.prebuild_needed),
                round(r.shelf_life_required), r.shelf_life_available,
                round(r.shelf_margin),
                r.status, r.action,
            ])


def print_summary(result) -> None:
    sep = "─" * 62
    print(f"\n{sep}")
    print("  FACTORY SHUTDOWN IMPACT — SUMMARY")
    print(sep)
    print(f"  Effective shutdown days : {result.effective_shutdown_days}")
    print(f"  Total pre-build units   : {result.total_prebuild_units:,.0f}")
    print(f"  Production days req.    : {result.production_days_required:.1f}")
    print(f"  Production days avail.  : {result.production_days_available:.1f}")
    cap_ok = "✅ OK" if result.capacity_ok else "🔴 GAP"
    print(f"  Capacity utilisation    : {result.capacity_utilisation_pct:.1f}%  {cap_ok}")
    print(f"  SKUs at risk            : {result.skus_at_risk} / {result.skus_total}")
    print(sep)
    print()

    for r in result.sku_results:
        icon = STATUS_ICONS.get(r.status, "  ")
        margin_str = (f"+{r.shelf_margin:.0f}d" if r.shelf_margin >= 0 else f"{r.shelf_margin:.0f}d")
        print(f"  {icon} [{r.abc_class}] {r.sku_name}")
        print(f"       Pre-build: {r.prebuild_needed:>9,.0f} units  |  "
              f"Shelf margin: {margin_str:>5}  |  Status: {r.status}")
        print(f"       {r.action}")
        print()
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FMCG Factory Shutdown Impact Calculator — CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # SKU input
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--skus", metavar="CSV", type=Path,
                   help="Path to SKU data CSV file.")
    g.add_argument("--sample", action="store_true",
                   help="Run with built-in sample data (5 SKUs).")
    g.add_argument("--generate-csv", metavar="PATH", type=Path,
                   help="Write a sample CSV template and exit.")

    # Shutdown params
    p = parser.add_argument_group("shutdown parameters")
    p.add_argument("--shutdown-days",         type=int, default=14)
    p.add_argument("--ramp-down-days",        type=int, default=3)
    p.add_argument("--ramp-up-days",          type=int, default=3)
    p.add_argument("--prebuild-weeks",        type=int, default=4)
    p.add_argument("--prod-days-per-week",    type=int, default=5)
    p.add_argument("--line-capacity-per-day", type=int, default=10000)
    p.add_argument("--safety-stock-days",     type=int, default=7)
    p.add_argument("--downstream-buffer",     type=int, default=14)

    # Output
    parser.add_argument("--output", metavar="CSV", type=Path, default=None,
                        help="Write results to this CSV file.")
    parser.add_argument("--json", action="store_true",
                        help="Print full results as JSON instead of table.")

    args = parser.parse_args()

    # Generate sample CSV and exit
    if args.generate_csv:
        args.generate_csv.write_text(SAMPLE_CSV, encoding="utf-8")
        print(f"Sample CSV written to {args.generate_csv}")
        return

    # Load SKUs
    if args.sample:
        import io
        reader = csv.DictReader(io.StringIO(SAMPLE_CSV))
        skus = [
            SkuInput(
                id=int(r["id"]), name=r["name"],
                daily_demand=float(r["daily_demand"]),
                current_stock=float(r["current_stock"]),
                shelf_life_days=int(r["shelf_life_days"]),
                demand_multiplier=float(r["demand_multiplier"]),
                alt_supply=float(r["alt_supply"]),
                abc_class=r["abc_class"],
            ) for r in reader
        ]
    else:
        if not args.skus.exists():
            print(f"Error: file not found — {args.skus}", file=sys.stderr)
            sys.exit(1)
        skus = load_skus_from_csv(args.skus)

    if not skus:
        print("Error: no valid SKUs loaded.", file=sys.stderr)
        sys.exit(1)

    params = ShutdownParams(
        shutdown_days=          args.shutdown_days,
        ramp_down_days=         args.ramp_down_days,
        ramp_up_days=           args.ramp_up_days,
        prebuild_weeks=         args.prebuild_weeks,
        prod_days_per_week=     args.prod_days_per_week,
        line_capacity_per_day=  args.line_capacity_per_day,
        safety_stock_days=      args.safety_stock_days,
        downstream_buffer_days= args.downstream_buffer,
    )

    result = calculate_all(skus, params)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print_summary(result)

    if args.output:
        write_results_csv(result, args.output)
        print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
