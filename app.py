"""
factory_stop_calculator.app
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Flask web server — serves the interactive HTML calculator and exposes a
REST API for programmatic access.

Endpoints:
    GET  /              → static/index.html (standalone calculator UI)
    GET  /api/health    → {"status": "ok"}
    POST /api/calculate → run the calculation; returns SummaryResult as JSON

Usage:
    pip install -r requirements.txt
    python app.py
    → http://localhost:5000
"""

from __future__ import annotations
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from calculator import StopParams, SkuInput, calculate_all

# ── App setup ────────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR))
CORS(app)

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the interactive HTML calculator."""
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/health")
def health():
    """Simple liveness check."""
    return jsonify({"status": "ok"})


@app.route("/api/calculate", methods=["POST"])
def calculate():
    """
    Calculate planned-stop impact for a list of SKUs.

    Request body (JSON):
        {
          "params": {
            "stop_days":              14,
            "ramp_down_days":         3,
            "ramp_up_days":           3,
            "prebuild_weeks":         4,
            "prod_days_per_week":     5,
            "line_capacity_per_day":  10000,
            "safety_stock_days":      7,
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

    Response (200):
        SummaryResult as JSON — see calculator.SummaryResult for field docs.

    Errors:
        400  missing / invalid body
        500  unexpected server error
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    # ── Parse params ─────────────────────────────────────────────
    params_data = body.get("params", {})
    try:
        params = StopParams(
            stop_days=              int(params_data.get("stop_days", 14)),
            ramp_down_days=         int(params_data.get("ramp_down_days", 3)),
            ramp_up_days=           int(params_data.get("ramp_up_days", 3)),
            prebuild_weeks=         int(params_data.get("prebuild_weeks", 4)),
            prod_days_per_week=     int(params_data.get("prod_days_per_week", 5)),
            line_capacity_per_day=  int(params_data.get("line_capacity_per_day", 10_000)),
            safety_stock_days=      int(params_data.get("safety_stock_days", 7)),
            downstream_buffer_days= int(params_data.get("downstream_buffer_days", 14)),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid params: {exc}"}), 400

    # ── Parse SKUs ───────────────────────────────────────────────
    skus_data = body.get("skus", [])
    if not isinstance(skus_data, list) or len(skus_data) == 0:
        return jsonify({"error": "'skus' must be a non-empty list"}), 400

    skus = []
    for i, s in enumerate(skus_data):
        try:
            skus.append(SkuInput(
                id=               int(s["id"]),
                name=             str(s["name"]),
                daily_demand=     float(s["daily_demand"]),
                current_stock=    float(s["current_stock"]),
                shelf_life_days=  int(s["shelf_life_days"]),
                demand_multiplier=float(s.get("demand_multiplier", 1.0)),
                alt_supply=       float(s.get("alt_supply", 0)),
                abc_class=        str(s.get("abc_class", "B")).upper(),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": f"SKU at index {i} is invalid: {exc}"}), 400

    # ── Calculate & return ───────────────────────────────────────
    result = calculate_all(skus, params)
    return jsonify(result.to_dict())


# ── Error handlers ───────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"  Factory Stop Calculator API → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
