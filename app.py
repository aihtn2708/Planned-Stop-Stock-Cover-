"""
factory_shutdown_calculator.app
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Flask web application that serves the HTML calculator and exposes a REST API.

Usage:
    pip install -r requirements.txt
    python app.py            # development server on http://localhost:5000
    flask run --port 5000    # alternative

API:
    POST /api/calculate      – calculate pre-build requirements for a set of SKUs
    GET  /api/health         – health check
"""

from __future__ import annotations
import os
from dataclasses import asdict

from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

from calculator import ShutdownParams, SkuInput, calculate_all

# ── App setup ────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)  # allow the static HTML to call /api/* during local development


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the single-page HTML calculator."""
    return send_from_directory("static", "index.html")


@app.route("/api/health")
def health():
    """Simple health-check endpoint."""
    return jsonify({"status": "ok", "service": "factory-shutdown-calculator"})


@app.route("/api/calculate", methods=["POST"])
def calculate():
    """
    Calculate shutdown pre-build requirements.

    Request body (JSON):
    {
        "params": {
            "shutdown_days":          14,
            "ramp_down_days":          3,
            "ramp_up_days":            3,
            "prebuild_weeks":          4,
            "prod_days_per_week":      5,
            "line_capacity_per_day": 10000,
            "safety_stock_days":       7,
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

    Response body (JSON):
        SummaryResult serialised to dict.
    """
    body = request.get_json(silent=True)
    if not body:
        abort(400, description="Request body must be JSON.")

    # ── Parse params (all optional — defaults used if omitted) ──────────────
    raw_params = body.get("params", {})
    try:
        params = ShutdownParams(
            shutdown_days=          int(raw_params.get("shutdown_days",          14)),
            ramp_down_days=         int(raw_params.get("ramp_down_days",          3)),
            ramp_up_days=           int(raw_params.get("ramp_up_days",            3)),
            prebuild_weeks=         int(raw_params.get("prebuild_weeks",           4)),
            prod_days_per_week=     int(raw_params.get("prod_days_per_week",       5)),
            line_capacity_per_day=  int(raw_params.get("line_capacity_per_day", 10000)),
            safety_stock_days=      int(raw_params.get("safety_stock_days",        7)),
            downstream_buffer_days= int(raw_params.get("downstream_buffer_days",  14)),
        )
    except (TypeError, ValueError) as exc:
        abort(400, description=f"Invalid params: {exc}")

    # ── Parse SKUs ──────────────────────────────────────────────────────────
    raw_skus = body.get("skus", [])
    if not raw_skus:
        abort(400, description="'skus' list is required and must not be empty.")

    try:
        skus = [
            SkuInput(
                id=               int(s["id"]),
                name=             str(s["name"]),
                daily_demand=     float(s["daily_demand"]),
                current_stock=    float(s["current_stock"]),
                shelf_life_days=  int(s["shelf_life_days"]),
                demand_multiplier=float(s.get("demand_multiplier", 1.0)),
                alt_supply=       float(s.get("alt_supply", 0)),
                abc_class=        str(s.get("abc_class", "B")).upper(),
            )
            for s in raw_skus
        ]
    except (KeyError, TypeError, ValueError) as exc:
        abort(400, description=f"Invalid SKU data: {exc}")

    result = calculate_all(skus, params)
    return jsonify(result.to_dict())


@app.errorhandler(400)
def bad_request(err):
    return jsonify({"error": str(err.description)}), 400


@app.errorhandler(404)
def not_found(_err):
    return jsonify({"error": "Not found"}), 404


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") != "production"
    print(f"  → Open http://localhost:{port} in your browser")
    app.run(host="0.0.0.0", port=port, debug=debug)
