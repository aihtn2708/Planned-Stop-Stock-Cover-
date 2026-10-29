"""
factory_stop_calculator.calculator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Core calculation logic for FMCG planned factory stop impact analysis.

This module is pure Python with no external dependencies and can be used
standalone, via the Flask API (app.py), or via the CLI (cli.py).
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Literal


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class StopParams:
    """Parameters that describe the planned factory stop and planning constraints."""

    stop_days: int = 14
    """Hard-stop calendar days with zero production output."""

    ramp_down_days: int = 3
    """Days before the stop with reduced output (WIP clearance, changeovers)."""

    ramp_up_days: int = 3
    """Days after restart with reduced yield (line trials, first-pass waste)."""

    prebuild_weeks: int = 4
    """Weeks available to build stock *before* the planned stop begins."""

    prod_days_per_week: int = 5
    """Production days available per week in the pre-build window."""

    line_capacity_per_day: int = 10_000
    """Units per day of *incremental* capacity above normal demand production."""

    safety_stock_days: int = 7
    """Days of demand cover to maintain / restore post-restart."""

    downstream_buffer_days: int = 14
    """Transit time from factory gate to consumer (DC + retail + consumer)."""

    @property
    def effective_stop_days(self) -> float:
        """Total days of lost / reduced output including ramp-down and ramp-up."""
        return self.ramp_down_days + self.stop_days + self.ramp_up_days

    @property
    def available_production_days(self) -> float:
        """Production days available for pre-build in the pre-build window."""
        return self.prebuild_weeks * self.prod_days_per_week

    @property
    def shelf_life_required_base(self) -> float:
        """Minimum shelf life (days) for goods produced at the start of the pre-build window."""
        return (self.prebuild_weeks * 7) + self.effective_stop_days + self.downstream_buffer_days


StatusType = Literal["OK", "COVERED", "TIGHT", "INFEASIBLE"]


@dataclass
class SkuInput:
    """Input data for a single SKU."""

    id: int
    """Unique identifier for this SKU."""

    name: str
    """Human-readable product name."""

    daily_demand: float
    """Average units sold per calendar day."""

    current_stock: float
    """Units currently on hand at the factory / DC."""

    shelf_life_days: int
    """Remaining usable shelf life of goods produced today (days)."""

    demand_multiplier: float = 1.0
    """Seasonal / promotional uplift factor (1.0 = no change)."""

    alt_supply: float = 0.0
    """Units available from co-packer or sister plant during the stop."""

    abc_class: str = "B"
    """ABC classification (A = high volume, C = low volume)."""


@dataclass
class SkuResult:
    """Calculated output for a single SKU."""

    sku_id: int
    sku_name: str
    abc_class: str

    effective_days: float
    """Total days of demand to cover (ramp-down + stop + ramp-up)."""

    adjusted_daily_demand: float
    """Daily demand after applying the multiplier."""

    demand_to_cover: float
    """Total units of demand during the effective stop period."""

    safety_stock_units: float
    """Safety stock units to hold after restart."""

    prebuild_needed: float
    """Net units that must be pre-built (after netting off existing stock and alt supply)."""

    shelf_life_required: float
    """Minimum shelf life (days) needed if production starts at week 0 of pre-build."""

    shelf_life_available: int
    """Actual shelf life of this SKU (days)."""

    shelf_margin: float
    """Shelf life available minus shelf life required (positive = headroom)."""

    shelf_life_ok: bool
    """True if the SKU can be pre-built without expiry risk."""

    status: StatusType
    """
    OK         – pre-build feasible, sufficient shelf life.
    COVERED    – no pre-build needed; current stock is enough.
    TIGHT      – shelf life feasible but margin < 14 days; monitor closely.
    INFEASIBLE – shelf life too short to pre-build from week 0.
    """

    action: str
    """One-line recommended action for planners."""


@dataclass
class SummaryResult:
    """Aggregated summary across all SKUs for a given set of stop parameters."""

    effective_stop_days: float
    total_prebuild_units: float
    production_days_required: float
    production_days_available: float
    capacity_utilisation_pct: float
    skus_at_risk: int
    skus_infeasible: int
    skus_total: int
    sku_results: List[SkuResult] = field(default_factory=list)

    @property
    def capacity_ok(self) -> bool:
        return self.production_days_required <= self.production_days_available

    def to_dict(self) -> dict:
        return asdict(self)


# ── Calculation functions ────────────────────────────────────────────────────

def calculate_sku(sku: SkuInput, params: StopParams) -> SkuResult:
    """
    Calculate the pre-build requirement and feasibility for one SKU.

    Args:
        sku:    SKU input data (demand, stock, shelf life, etc.)
        params: Planned stop parameters

    Returns:
        SkuResult with all derived figures and a status classification.
    """
    eff = params.effective_stop_days
    adj = sku.daily_demand * sku.demand_multiplier
    dmd = adj * eff
    ss  = adj * params.safety_stock_days
    pb  = max(0.0, dmd + ss - sku.current_stock - sku.alt_supply)

    shelf_req = params.shelf_life_required_base
    shelf_ok  = sku.shelf_life_days >= shelf_req
    margin    = sku.shelf_life_days - shelf_req

    # ── Status & action ──────────────────────────────────────────
    if pb == 0:
        status = "COVERED"
        action = "No pre-build needed. Monitor stock levels weekly during the run-up."
    elif not shelf_ok:
        status = "INFEASIBLE"
        action = (
            f"Shelf life too short by {abs(margin):.0f}d. "
            "Options: (1) source from co-packer, "
            "(2) shorten pre-build window / start closer to the stop, "
            "(3) accept planned stockout with commercial sign-off, "
            "(4) explore shelf-life extension."
        )
    elif margin < 14:
        status = "TIGHT"
        action = (
            f"Pre-build {pb:,.0f} units. "
            f"Shelf margin only +{margin:.0f}d — delay production start or enforce strict FIFO. "
            "Review downstream buffer assumption."
        )
    else:
        status = "OK"
        action = (
            f"Pre-build {pb:,.0f} units spread across the "
            f"{params.prebuild_weeks}-week pre-build window. Enforce FIFO rotation."
        )

    return SkuResult(
        sku_id=sku.id,
        sku_name=sku.name,
        abc_class=sku.abc_class,
        effective_days=eff,
        adjusted_daily_demand=adj,
        demand_to_cover=round(dmd, 2),
        safety_stock_units=round(ss, 2),
        prebuild_needed=round(pb, 2),
        shelf_life_required=round(shelf_req, 1),
        shelf_life_available=sku.shelf_life_days,
        shelf_margin=round(margin, 1),
        shelf_life_ok=shelf_ok,
        status=status,
        action=action,
    )


def calculate_all(skus: List[SkuInput], params: StopParams) -> SummaryResult:
    """
    Calculate pre-build requirements for all SKUs and return a full summary.

    Args:
        skus:   List of SKU inputs.
        params: Planned stop parameters.

    Returns:
        SummaryResult with per-SKU results and aggregated KPIs.

    Example::

        from calculator import StopParams, SkuInput, calculate_all

        params = StopParams(stop_days=14, prebuild_weeks=4)
        skus = [
            SkuInput(id=1, name="Product A", daily_demand=500,
                     current_stock=3500, shelf_life_days=180),
        ]
        result = calculate_all(skus, params)
        print(result.total_prebuild_units)
    """
    results = [calculate_sku(s, params) for s in skus]

    total_pb  = sum(r.prebuild_needed for r in results)
    cap       = params.line_capacity_per_day
    prod_req  = total_pb / cap if cap > 0 else 0.0
    prod_avail = params.available_production_days
    cap_pct   = (prod_req / prod_avail * 100) if prod_avail > 0 else 0.0
    at_risk   = sum(1 for r in results if r.status in ("INFEASIBLE", "TIGHT"))
    infeasible = sum(1 for r in results if r.status == "INFEASIBLE")

    return SummaryResult(
        effective_stop_days=params.effective_stop_days,
        total_prebuild_units=round(total_pb, 2),
        production_days_required=round(prod_req, 2),
        production_days_available=prod_avail,
        capacity_utilisation_pct=round(cap_pct, 1),
        skus_at_risk=at_risk,
        skus_infeasible=infeasible,
        skus_total=len(skus),
        sku_results=results,
    )
