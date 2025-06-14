"""
FastAPI service for Airbnb data (pyairbnb)
––––––––––––––––––––––––––––––––––––––––––––––––––
Routes
  /                → {"status":"ok"}
  /calendar        → details / calendar / pricing for one room_id
  /search          → lightweight comps list inside radius
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ────────────────────────────────────────────────────────────────
# Config & helpers
# ────────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")

_DEG_PER_MILE = 1 / 69.0        # ≈1° lat  ~ 69 statute miles
def miles_to_deg(mi: float) -> float:
    """Rough conversion miles → decimal degrees."""
    return mi * _DEG_PER_MILE


# ────────────────────────────────────────────────────────────────
# FastAPI
# ────────────────────────────────────────────────────────────────
app = FastAPI(title="pyairbnb micro-API")


@app.get("/")
def index() -> dict[str, str]:
    """Simple health-check."""
    return {"status": "ok"}


# ────────────────────────────
#  /calendar  (unchanged logic)
# ────────────────────────────
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (numbers only)"),
    check_in: str = Query(...,  description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(...,     description="Auth token")
):
    # 1. Auth
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 2. Listing-level details
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # 3. Pricing for that stay
        price_data = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],   # ← note spelling inside lib
            price_input["product_id"],
            check_in,
            check_out,
            2,                              # adults
            "USD",
            "en",
            ""
        )

        # 4. Availability calendar (current snapshot)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({
            "calendar": calendar,
            "details":  details,
            "pricing":  price_data
        })

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ────────────────────────────
#  /search   (comps)
# ────────────────────────────
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, description="Radius in miles (default 5)"),
    check_in: Optional[str] = Query(None, description="YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="YYYY-MM-DD"),
    price_min: int = Query(0,    description="Min nightly price (USD)"),
    price_max: int = Query(2000, description="Max nightly price (USD)"),
    token: str = Query(...,      description="Auth token")
):
    # 1. Auth
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Build bounding box
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        results = pyairbnb.search_all(
            check_in          = check_in,
            check_out         = check_out,
            ne_lat            = f"{ne_lat}",
            ne_long           = f"{ne_lon}",
            sw_lat            = f"{sw_lat}",
            sw_long           = f"{sw_lon}",
            zoom_value        = "12",               # ← must be str
            currency          = "USD",
            language          = "en",
            price_min         = f"{price_min}",
            price_max         = f"{price_max}",
            proxy_url         = ""
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {e}")

    # 3. Slim response: only the fields Justin cares about
    comps: list[dict] = []
    for listing in results:
        comps.append({
            "id":        listing.get("id") or listing.get("listingId"),
            "title":     listing.get("title"),
            "price":     listing.get("price", {}).get("label"),
            "guests":    listing.get("personCapacity"),
            "rating":    listing.get("rating", {}).get("guestSatisfaction"),
            "reviews":   listing.get("rating", {}).get("reviewsCount"),
            "lat":       listing.get("coordinates", {}).get("latitude"),
            "lon":       listing.get("coordinates", {}).get("longitude"),
            "url":       listing.get("url"),
        })

    return JSONResponse({
        "centre":  {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":   len(comps),
        "listings": comps,
    })
