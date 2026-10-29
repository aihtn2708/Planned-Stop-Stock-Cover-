"""
Tests for calculator.py — core FMCG planned stop impact logic.

Run:
    pytest tests/ -v
    pytest tests/ -v --cov=calculator --cov-report=term-missing
"""

import pytest
from calculator import (
    StopParams,
    SkuInput,
    calculate_sku,
    calculate_all,
    SummaryResult,
    SkuResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def default_params():
    return StopParams(
        stop_days=14,
        ramp_down_days=3,
        ramp_up_days=3,
        prebuild_weeks=4,
        prod_days_per_week=5,
        line_capacity_per_day=10_000,
        safety_stock_days=7,
        downstream_buffer_days=14,
    )


@pytest.fixture
def ok_sku():
    """A SKU with enough shelf life and sufficient stock situation to pre-build."""
    return SkuInput(id=1, name="OK Product", daily_demand=500,
                    current_stock=0, shelf_life_days=180,
                    demand_multiplier=1.0, alt_supply=0, abc_class="A")


@pytest.fixture
def covered_sku():
    """A SKU whose current stock already covers everything — no pre-build needed."""
    return SkuInput(id=2, name="Covered Product", daily_demand=100,
                    current_stock=99_999, shelf_life_days=365,
                    demand_multiplier=1.0, alt_supply=0, abc_class="C")


@pytest.fixture
def infeasible_sku():
    """A short shelf-life SKU that cannot be pre-built from week 0."""
    return SkuInput(id=3, name="Short Shelf Product", daily_demand=200,
                    current_stock=0, shelf_life_days=30,
                    demand_multiplier=1.0, alt_supply=0, abc_class="B")


@pytest.fixture
def tight_sku():
    """A SKU where shelf life is just barely sufficient (margin < 14 days)."""
    # shelf_life_required = 4*7 + 20 + 14 = 62 days
    # We set shelf_life_days = 65 → margin = +3 days → TIGHT
    return SkuInput(id=4, name="Tight Margin Product", daily_demand=300,
                    current_stock=0, shelf_life_days=65,
                    demand_multiplier=1.0, alt_supply=0, abc_class="B")


# ── StopParams properties ─────────────────────────────────────────────────────

class TestStopParams:
    def test_effective_days(self, default_params):
        assert default_params.effective_stop_days == 3 + 14 + 3

    def test_available_production_days(self, default_params):
        assert default_params.available_production_days == 4 * 5

    def test_shelf_life_required_base(self, default_params):
        # 4*7 + 20 + 14
        assert default_params.shelf_life_required_base == 28 + 20 + 14

    def test_zero_ramp(self):
        p = StopParams(stop_days=10, ramp_down_days=0, ramp_up_days=0)
        assert p.effective_stop_days == 10


# ── calculate_sku: status classification ─────────────────────────────────────

class TestCalculateSkuStatus:

    def test_ok_status(self, ok_sku, default_params):
        r = calculate_sku(ok_sku, default_params)
        assert r.status == "OK"
        assert r.prebuild_needed > 0
        assert r.shelf_life_ok is True
        assert r.shelf_margin >= 14

    def test_covered_status(self, covered_sku, default_params):
        r = calculate_sku(covered_sku, default_params)
        assert r.status == "COVERED"
        assert r.prebuild_needed == 0.0

    def test_infeasible_status(self, infeasible_sku, default_params):
        r = calculate_sku(infeasible_sku, default_params)
        assert r.status == "INFEASIBLE"
        assert r.shelf_life_ok is False
        assert r.shelf_margin < 0

    def test_tight_status(self, tight_sku, default_params):
        r = calculate_sku(tight_sku, default_params)
        assert r.status == "TIGHT"
        assert r.shelf_life_ok is True
        assert 0 <= r.shelf_margin < 14


# ── calculate_sku: numeric correctness ───────────────────────────────────────

class TestCalculateSkuNumerics:

    def test_effective_days_passed_through(self, ok_sku, default_params):
        r = calculate_sku(ok_sku, default_params)
        assert r.effective_days == default_params.effective_stop_days

    def test_demand_to_cover(self, ok_sku, default_params):
        r = calculate_sku(ok_sku, default_params)
        expected = ok_sku.daily_demand * default_params.effective_stop_days
        assert r.demand_to_cover == pytest.approx(expected, rel=1e-6)

    def test_demand_multiplier_applied(self, default_params):
        sku = SkuInput(id=9, name="Promo SKU", daily_demand=100,
                       current_stock=0, shelf_life_days=365,
                       demand_multiplier=1.5, alt_supply=0, abc_class="A")
        r = calculate_sku(sku, default_params)
        assert r.adjusted_daily_demand == 150.0
        assert r.demand_to_cover == pytest.approx(150 * default_params.effective_stop_days)

    def test_alt_supply_reduces_prebuild(self, ok_sku, default_params):
        sku_no_alt = ok_sku
        sku_with_alt = SkuInput(**{**ok_sku.__dict__, "alt_supply": 1000})
        r_no_alt   = calculate_sku(sku_no_alt,   default_params)
        r_with_alt = calculate_sku(sku_with_alt, default_params)
        assert r_with_alt.prebuild_needed == pytest.approx(
            max(0, r_no_alt.prebuild_needed - 1000), rel=1e-6
        )

    def test_current_stock_reduces_prebuild(self, default_params):
        base = SkuInput(id=5, name="X", daily_demand=500, current_stock=0,
                        shelf_life_days=365, abc_class="A")
        with_stock = SkuInput(id=5, name="X", daily_demand=500, current_stock=5000,
                              shelf_life_days=365, abc_class="A")
        r_base  = calculate_sku(base, default_params)
        r_stock = calculate_sku(with_stock, default_params)
        assert r_stock.prebuild_needed == pytest.approx(
            max(0, r_base.prebuild_needed - 5000), rel=1e-6
        )

    def test_prebuild_never_negative(self, covered_sku, default_params):
        r = calculate_sku(covered_sku, default_params)
        assert r.prebuild_needed >= 0.0

    def test_shelf_life_required_correct(self, ok_sku, default_params):
        r = calculate_sku(ok_sku, default_params)
        expected = default_params.shelf_life_required_base
        assert r.shelf_life_required == pytest.approx(expected)

    def test_shelf_margin_correct(self, ok_sku, default_params):
        r = calculate_sku(ok_sku, default_params)
        assert r.shelf_margin == pytest.approx(
            ok_sku.shelf_life_days - default_params.shelf_life_required_base, rel=1e-6
        )


# ── calculate_all ─────────────────────────────────────────────────────────────

class TestCalculateAll:

    def _three_skus(self):
        return [
            SkuInput(id=1, name="A", daily_demand=500,  current_stock=0,     shelf_life_days=180, abc_class="A"),
            SkuInput(id=2, name="B", daily_demand=200,  current_stock=99999, shelf_life_days=365, abc_class="C"),
            SkuInput(id=3, name="C", daily_demand=1000, current_stock=0,     shelf_life_days=30,  abc_class="A"),
        ]

    def test_returns_summary_result(self, default_params):
        result = calculate_all(self._three_skus(), default_params)
        assert isinstance(result, SummaryResult)

    def test_total_prebuild_is_sum(self, default_params):
        skus = self._three_skus()
        result = calculate_all(skus, default_params)
        individual = sum(calculate_sku(s, default_params).prebuild_needed for s in skus)
        assert result.total_prebuild_units == pytest.approx(individual, rel=1e-6)

    def test_skus_total_count(self, default_params):
        skus = self._three_skus()
        result = calculate_all(skus, default_params)
        assert result.skus_total == 3

    def test_skus_at_risk_counts_tight_and_infeasible(self, default_params):
        skus = self._three_skus()
        result = calculate_all(skus, default_params)
        at_risk = sum(1 for r in result.sku_results if r.status in ("INFEASIBLE", "TIGHT"))
        assert result.skus_at_risk == at_risk

    def test_capacity_utilisation(self, default_params):
        skus = [SkuInput(id=1, name="X", daily_demand=500, current_stock=0,
                         shelf_life_days=365, abc_class="A")]
        result = calculate_all(skus, default_params)
        # Derived from raw (unrounded) totals; stored value is rounded to 1dp
        assert 0 < result.capacity_utilisation_pct < 100
        # Internally consistent: utilisation ↔ days required / available
        implied = result.production_days_required / result.production_days_available * 100
        assert result.capacity_utilisation_pct == pytest.approx(implied, abs=0.1)

    def test_capacity_ok_flag(self, default_params):
        skus = [SkuInput(id=1, name="Tiny", daily_demand=1, current_stock=0,
                         shelf_life_days=365, abc_class="C")]
        result = calculate_all(skus, default_params)
        assert result.capacity_ok is True

    def test_to_dict_serialisable(self, default_params):
        import json
        result = calculate_all(self._three_skus(), default_params)
        d = result.to_dict()
        dumped = json.dumps(d)   # must not raise
        assert "sku_results" in d
        assert len(d["sku_results"]) == 3

    def test_empty_sku_list_returns_zeros(self, default_params):
        result = calculate_all([], default_params)
        assert result.total_prebuild_units == 0.0
        assert result.skus_total == 0
        assert result.sku_results == []


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_zero_line_capacity(self):
        params = StopParams(line_capacity_per_day=0)
        skus = [SkuInput(id=1, name="X", daily_demand=100, current_stock=0,
                         shelf_life_days=365, abc_class="A")]
        result = calculate_all(skus, params)
        assert result.production_days_required == 0.0   # no division by zero

    def test_very_long_shelf_life(self, default_params):
        sku = SkuInput(id=1, name="Canned", daily_demand=100, current_stock=0,
                       shelf_life_days=3650, abc_class="A")
        r = calculate_sku(sku, default_params)
        assert r.status == "OK"
        assert r.shelf_margin > 3000

    def test_zero_ramp_days(self):
        params = StopParams(stop_days=14, ramp_down_days=0, ramp_up_days=0)
        sku = SkuInput(id=1, name="Y", daily_demand=200, current_stock=0,
                       shelf_life_days=365, abc_class="B")
        r = calculate_sku(sku, params)
        assert r.effective_days == 14

    def test_multiplier_above_one_increases_demand(self, default_params):
        base  = SkuInput(id=1, name="Z", daily_demand=100, current_stock=0,
                         shelf_life_days=365, demand_multiplier=1.0, alt_supply=0, abc_class="A")
        promo = SkuInput(id=1, name="Z", daily_demand=100, current_stock=0,
                         shelf_life_days=365, demand_multiplier=2.0, alt_supply=0, abc_class="A")
        r_base  = calculate_sku(base,  default_params)
        r_promo = calculate_sku(promo, default_params)
        assert r_promo.prebuild_needed > r_base.prebuild_needed
