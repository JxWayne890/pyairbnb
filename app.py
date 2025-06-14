"""
FastAPI wrapper around pyairbnb
—————————————
• /calendar   – availability + pricing for ONE listing
• /search     – lightweight comps search in a radius (Justin’s “RADAR”)
"""

import os
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb     # ⇠ the un-modified library from your repo

API_TOKEN = os.getenv("API_TOKEN", "changeme")

app = FastAPI()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEG_PER_MILE = 1 / 69.0          # ≈ 0.01449°  (lat/long offset for 1 mi)


def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


def clean_num(value: Optional[str | int | float], fallback: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


def slim(hit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract only the bits Justin actually needs.
    Works with both the *old* and *new* pyairbnb hit shapes.
    """
    listing = hit.get("listing") or hit
    pricing = hit.get("pricingQuote") or hit.get("price", {})

    return {
        "id":       listing.get("id") or listing.get("listingId"),
        "title":    listing.get("name") or listing.get("title"),
        "price":    pricing.get("rate", {}).get("amount") or pricing.get("label"),
        "rating":   listing.get("avgRating") or hit.get("rating", {}).get("guestSatisfaction"),
        "reviews":  listing.get("reviewsCount") or hit.get("rating", {}).get("reviewsCount"),
        "lat":      listing.get("lat") or listing.get("coordinates", {}).get("latitude"),
        "lon":      listing.get("lng") or listing.get("coordinates", {}).get("longitude"),
        "url":      listing.get("url"),
    }

# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.get("/")
def hello() -> dict:
    return {"status": "ok"}


@app.get("/calendar")
def calendar(
    room: str = Query(...),
    check_in: str = Query(..., alias="check_in"),
    check_out: str = Query(..., alias="check_out"),
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    try:
        details, price_inp, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        if not price_inp or not cookies:
            raise ValueError("Missing pricing input or cookies")

        pricing = pyairbnb.price.get(
            price_inp["api_key"], cookies, price_inp["impression_id"],
            price_inp["product_id"], check_in, check_out,
            2, "USD", "en", ""
        )

        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({
            "calendar": cal,
            "details": details,
            "pricing": pricing
        })

    except Exception as err:
        raise HTTPException(502, f"Error fetching data: {err}")


@app.get("/search")
def search_listings(
    lat: float  = Query(...),
    lon: float  = Query(...),
    radius: float = Query(5.0),
    price_min: Optional[str] = Query("0"),
    price_max: Optional[str] = Query("10000"),
    check_in:  Optional[str] = Query(None, alias="check_in"),
    check_out: Optional[str] = Query(None, alias="check_out"),
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    # --- sanitise & validate ------------------------------------------------
    pmin = clean_num(price_min, 0)
    pmax = clean_num(price_max, 10000)
    if pmin >= pmax:
        raise HTTPException(400, "`price_min` must be lower than `price_max`")

    # --- bounding box -------------------------------------------------------
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        hits: List[Dict[str, Any]] = pyairbnb.search_all(
            check_in, check_out,
            ne_lat, ne_lon, sw_lat, sw_lon,
            zoom_value=12,
            price_min=pmin, price_max=pmax,
            currency="USD", language="en", proxy_url=""
        )
    except Exception as err:
        raise HTTPException(502, f"pyairbnb search failed: {err}")

    comps = [slim(h) for h in hits]

    return {
        "centre":    {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":     len(comps),
        "listings":  comps,
    }

# ---------------------------------------------------------------------------
# ╭──────────────────────────────────────────────────────────────────────────╮
# │ Quick sanity checks once the Render build is green                      │
# ╰──────────────────────────────────────────────────────────────────────────╯
#
# 1️⃣  https://pyairbnb.onrender.com/calendar?room=7123549524411418888&check_in=2025-07-01&check_out=2025-07-03&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# 2️⃣  https://pyairbnb.onrender.com/search?lat=37.7749&lon=-122.4194&radius=5&price_min=0&price_max=2000&check_in=2025-08-10&check_out=2025-08-12&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# Expected: Both return listings with **non-null IDs**, titles, lat/lon
