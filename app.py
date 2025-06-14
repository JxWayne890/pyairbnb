"""
FastAPI wrapper around **pyairbnb**               (© 2025-06)

Routes
------
/               → simple health-check
/calendar       → availability + pricing for ONE room
/search         → radius search (“comps”) around a lat/lon point
"""

from __future__ import annotations

import math
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")           # ← set in Render!
DEFAULT_CURRENCY = "USD"
DEFAULT_LANG = "en"

app = FastAPI(title="pyairbnb mini-API")


# ────────────────────────────────────────────────────────────────
# Helpers – radius maths
# ────────────────────────────────────────────────────────────────
def miles_to_lat_deg(mi: float) -> float:
    """Miles → degrees of latitude (≈ 69 miles per ° everywhere)."""
    return mi / 69.0


def miles_to_lon_deg(mi: float, latitude: float) -> float:
    """Miles → degrees of longitude at a given latitude."""
    return mi / (69.0 * math.cos(math.radians(latitude)))


# ────────────────────────────────────────────────────────────────
# Health-check
# ────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> dict:
    return {"status": "ok"}


# ────────────────────────────────────────────────────────────────
# /calendar  – availability + pricing for one listing
# ────────────────────────────────────────────────────────────────
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (numbers only)"),
    check_in: str = Query(...,  description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(...,      description="Must match API_TOKEN"),
):
    # --- auth ----------------------------------------------------------------
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # --- listing-level info ---------------------------------------------
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}",
            DEFAULT_LANG,
            proxy_url="",
        )

        # --- stay-specific pricing ------------------------------------------
        price = pyairbnb.price.get(
            price_input["api_key"],          # 1
            cookies,                         # 2
            price_input["impression_id"],    # 3  (library param is *impresion_id*)
            price_input["product_id"],       # 4
            check_in,                        # 5
            check_out,                       # 6
            2,                               # adults
            DEFAULT_CURRENCY,
            DEFAULT_LANG,
            proxy_url="",
        )

        # --- availability calendar (current month snapshot) -----------------
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({
            "calendar": calendar,
            "details":  details,
            "pricing":  price,
        })

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ────────────────────────────────────────────────────────────────
# /search – Justin’s “comps” radius search
# ────────────────────────────────────────────────────────────────
@app.get("/search")
def search_listings(
    lat: float = Query(...,  description="Centre latitude"),
    lon: float = Query(...,  description="Centre longitude"),
    radius: float = Query(5, description="Radius in **miles** (default 5)"),
    price_min: int = Query(0,      description="Min nightly price"),
    price_max: int = Query(5000,   description="Max nightly price"),
    check_in: Optional[str]  = Query(None, description="Optional YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="Optional YYYY-MM-DD"),
    token: str = Query(...,        description="Must match API_TOKEN"),
):
    # --- auth ----------------------------------------------------------------
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # --- bounding box --------------------------------------------------------
    lat_deg = miles_to_lat_deg(radius)
    lon_deg = miles_to_lon_deg(radius, lat)

    ne_lat = lat + lat_deg
    sw_lat = lat - lat_deg
    ne_lon = lon + lon_deg
    sw_lon = lon - lon_deg

    try:
        results = pyairbnb.search_all(
            check_in,
            check_out,
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            price_min,
            price_max,
            12,                 # zoom_value
            DEFAULT_CURRENCY,
            DEFAULT_LANG,
            proxy_url="",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb.search_all failed: {err}")

    # --- slim the payload ----------------------------------------------------
    comps: list[dict] = []
    for listing in results:
        comps.append({
            "id":      listing.get("id") or listing.get("listingId"),
            "title":   listing.get("title"),
            "price":   listing.get("price", {}).get("label"),
            "guests":  listing.get("personCapacity"),
            "rating":  listing.get("rating", {}).get("guestSatisfaction"),
            "reviews": listing.get("rating", {}).get("reviewsCount"),
            "lat":     listing.get("coordinates", {}).get("latitude"),
            "lon":     listing.get("coordinates", {}).get("longitude"),
            "url":     listing.get("url"),
        })

    return JSONResponse({
        "centre":    {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":     len(comps),
        "listings":  comps,
    })
