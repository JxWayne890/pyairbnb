"""
Minimal FastAPI wrapper around **pyairbnb**  
* /               → health-check (“status: ok”)  
* /calendar       → availability + pricing for ONE listing  
* /search         → “comps” search (radius in miles, date/price filters)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ---------------------------------------------------------------------------
# ── CONFIG ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
API_TOKEN = os.getenv("API_TOKEN", "changeme")

# 1 mile ≈ 1 / 69°  (good enough for city-scale searches)
_DEG_PER_MILE = 1 / 69.0


def miles_to_deg(mi: float) -> float:
    """Convert miles to decimal degrees."""
    return mi * _DEG_PER_MILE


# ---------------------------------------------------------------------------
# ── FASTAPI INSTANCE ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
app = FastAPI(title="pyairbnb micro-API", version="1.0")


# ---------------------------------------------------------------------------
# ── HELPER: very small auth check ──────────────────────────────────────────
# ---------------------------------------------------------------------------
def check_token(tok: str) -> None:
    if tok != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# ── ROOT / HEALTH - CHECK ─────────────────────────────────────────────────
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# ── SINGLE-LISTING CALENDAR / PRICING ─────────────────────────────────────
# ---------------------------------------------------------------------------
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (digits only)"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    """
    Return   ▸ `details`   (static)  
             ▸ `pricing`   (for given stay)  
             ▸ `calendar`  (current-month availability)
    """
    check_token(token)

    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # NB: internal typo in the library → “impresion_id”
        price = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],
            price_input["product_id"],
            check_in,
            check_out,
            2,          # adults
            "USD",
            "en",
            "",
        )

        calendar = pyairbnb.get_calendar(
            room_id=room, checkin=check_in, checkout=check_out, proxy_url=""
        )

        return JSONResponse({"calendar": calendar, "details": details, "pricing": price})

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ---------------------------------------------------------------------------
# ── RADIUS SEARCH (“COMPS”) ───────────────────────────────────────────────
# ---------------------------------------------------------------------------
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, gt=0, le=30, description="Radius in miles"),
    price_min: float = Query(0, ge=0, description="Min nightly price (USD)"),
    price_max: float = Query(2000, gt=0, description="Max nightly price (USD)"),
    check_in: Optional[str] = Query(None, description="Check-in YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="Check-out YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    """
    Thin wrapper around **pyairbnb.search_all**.  
    Returns a *slim* list of nearby listings good enough for RADAR comps.
    """
    check_token(token)

    # --- date sanity (optional) -------------------------------------------------
    if (check_in is None) ^ (check_out is None):
        raise HTTPException(
            400, detail="Both check_in and check_out must be supplied (or neither)."
        )
    if check_in:
        try:
            d_in = datetime.fromisoformat(check_in)
            d_out = datetime.fromisoformat(check_out)        # type: ignore[arg-type]
            if d_out <= d_in:
                raise ValueError
        except ValueError:
            raise HTTPException(400, detail="Invalid dates")

    # --- bounding box ----------------------------------------------------------
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    # --- pyairbnb call ---------------------------------------------------------
    try:
        results: List[Dict[str, Any]] = pyairbnb.search_all(
            check_in,           # may be None
            check_out,          # may be None
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            price_min,
            price_max,
            12,                 # zoom (constant works fine)
            "USD",
            "en",
            "",
        )
    except Exception as err:
        raise HTTPException(502, detail=f"pyairbnb search failed: {err}")

    # --- project into slim schema ---------------------------------------------
    comps: list[dict[str, Any]] = []
    for r in results:
        lst   = r.get("listing", {})
        quote = r.get("pricingQuote", {}) or {}
        price_amt = (
            quote.get("structuredStayDisplayPrice", {})
            .get("primaryLine", {})
            .get("price", {})
            .get("amount")
        )

        comps.append(
            {
                "id":       lst.get("id"),
                "title":    lst.get("name"),
                "price":    price_amt,
                "persons":  lst.get("personCapacity"),
                "rating":   lst.get("avgRating"),
                "reviews":  lst.get("reviewsCount"),
                "lat":      lst.get("lat"),
                "lon":      lst.get("lng"),
                "url":      r.get("url"),
            }
        )

    return JSONResponse(
        {
            "centre": {"lat": lat, "lon": lon},
            "radius_mi": radius,
            "count": len(comps),
            "listings": comps,
        }
    )
