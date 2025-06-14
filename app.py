"""
FastAPI wrapper around pyairbnb
───────────────────────────────
Routes
  • /           – health-check
  • /calendar   – details + pricing + calendar for ONE listing
  • /search     – “comps” search (lat/lon + radius → slim list)
"""

from __future__ import annotations
import os
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import pyairbnb

app = FastAPI()

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
API_TOKEN   = os.getenv("API_TOKEN",   "changeme")
DEBUG_PYAIR = bool(int(os.getenv("DEBUG_PYAIRBNB", "0")))   # set to 1 for verbose

_DEG_PER_MILE = 1 / 69.0            # very good ~approx for lat/long conversion
miles_to_deg  = lambda mi: mi * _DEG_PER_MILE


# ─────────────────────────────────────────────────────────────────────────────
# Health-check
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
def root() -> dict:
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/calendar")
def calendar(
    room:      str = Query(...),
    check_in:  str = Query(...,  alias="check_in"),
    check_out: str = Query(...,  alias="check_out"),
    token:     str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        pricing = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],
            price_input["product_id"],
            check_in,
            check_out,
            2,                # adults
            "USD",
            "en",
            "",
        )

        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({"calendar": cal, "details": details, "pricing": pricing})

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error fetching data: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH  – comps within radius
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/search")
def search_listings(
    lat:        float = Query(...),
    lon:        float = Query(...),
    radius:     float = Query(5.0,  description="miles"),
    check_in:   Optional[str] = Query(None),
    check_out:  Optional[str] = Query(None),
    price_min:  Optional[int] = Query(0),
    price_max:  Optional[int] = Query(50000),
    token:      str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding box
    d = miles_to_deg(radius)
    ne_lat, ne_lon = lat + d, lon + d
    sw_lat, sw_lon = lat - d, lon - d

    try:
        results = pyairbnb.search_all(
            check_in,
            check_out,
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            12,              # zoom
            "USD",
            "en",
            "",
            price_min,
            price_max,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {e}")

    # ── OPTIONAL DEBUG ──────────────────────────────────────────────────────
    if DEBUG_PYAIR and results:
        print("╭─ pyairbnb raw listing ───────────────────────────────")
        print(results[0])
        print("╰──────────────────────────────────────────────────────")

    # map to slim structure – keys verified against real pyairbnb output
    slim: list[dict] = []
    for listing in results:
        # NOTE: Many keys may be missing → .get() with fallback
        slim.append({
            "id":        listing.get("listingId")                       or listing.get("id"),
            "title":     listing.get("title"),
            "price":     listing.get("pricingQuote", {}).get("rate", {}).get("amountFormatted")
                          or listing.get("price", {}).get("label"),
            "rating":    listing.get("starRating")                      or listing.get("rating", {}).get("guestSatisfaction"),
            "reviews":   listing.get("reviewsCount")                    or listing.get("rating", {}).get("reviewsCount"),
            "lat":       listing.get("lat")                             or listing.get("coordinates", {}).get("latitude"),
            "lon":       listing.get("lng")                             or listing.get("coordinates", {}).get("longitude"),
            "url":       listing.get("url"),
        })

    return JSONResponse({
        "centre": {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count": len(slim),
        "listings": slim,
    })
