"""
Minimal FastAPI wrapper around pyairbnb
======================================

* /            – health-check
* /calendar    – 1 listing: availability + details + pricing
* /search      – “RADAR” comps search (lat/lon + radius + price band)

Author: you 😊
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ───────────────────────────  CONFIG  ────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")          # set on Render
DEFAULT_CURRENCY = "USD"
DEFAULT_LANG = "en"

# 1 mile ≈ 0 .0144927536 degrees  ( 1° ≈ 69 mi )
DEG_PER_MILE = 1 / 69.0


def miles_to_deg(mi: float) -> float:
    return mi * DEG_PER_MILE


app = FastAPI()


# ──────────────────────────  HEALTH  ─────────────────────────────
@app.get("/")
def index() -> dict[str, str]:
    return {"status": "ok"}


# ─────────────────────  SINGLE-LISTING CALENDAR  ─────────────────
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID"),
    check_in: date = Query(..., description="YYYY-MM-DD"),
    check_out: date = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Your API token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 1. basic details
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}",
            DEFAULT_LANG,
            "",
        )

        # 2. stay-specific pricing
        pricing = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],
            price_input["product_id"],
            str(check_in),
            str(check_out),
            2,  # adults
            DEFAULT_CURRENCY,
            DEFAULT_LANG,
            "",
        )

        # 3. current-month availability snapshot
        availability = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {
                "calendar": availability,
                "details": details,
                "pricing": pricing,
            }
        )

    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error fetching data: {exc}")


# ───────────────────────────  COMPS  ─────────────────────────────
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, description="Radius in miles"),
    price_min: int = Query(0, ge=0),
    price_max: int = Query(5000, ge=0),
    check_in: Optional[date] = Query(None),
    check_out: Optional[date] = Query(None),
    token: str = Query(...),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding-box → pyairbnb expects NE & SW corners
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        # NB: search_all positional order matters!
        results = pyairbnb.search_all(
            str(check_in) if check_in else None,
            str(check_out) if check_out else None,
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            1,              # page
            price_min,
            price_max,
            12,             # zoom_value
            DEFAULT_CURRENCY,
            DEFAULT_LANG,
            "",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {exc}")

    # keep payload light – just the essentials for comps
    slim: list[dict] = []
    for item in results:
        slim.append(
            {
                "id": item.get("id") or item.get("listingId"),
                "title": item.get("title"),
                "price": item.get("price", {}).get("label"),
                "rating": item.get("rating", {}).get("guestSatisfaction"),
                "reviews": item.get("rating", {}).get("reviewsCount"),
                "lat": item.get("coordinates", {}).get("latitude"),
                "lon": item.get("coordinates", {}).get("longitude"),
                "url": item.get("url"),
            }
        )

    return JSONResponse(
        {
            "centre": {"lat": lat, "lon": lon},
            "radius_mi": radius,
            "count": len(slim),
            "listings": slim,
        }
    )
