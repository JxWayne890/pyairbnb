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

import pyairbnb            # ← un-modified library from your repo

API_TOKEN = os.getenv("API_TOKEN", "changeme")
_DEG_PER_MILE = 1 / 69.0                     # ≈ 0.01449°  (lat/long offset for 1 mi)

app = FastAPI()


# ───────────────────────── helpers ──────────────────────────────────────────
def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


def clean_num(value: Optional[str | int | float], fallback: int) -> int:
    """Force-cast any query arg to int or return fallback."""
    try:
        return int(float(value))
    except Exception:
        return fallback


def slim(hit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract only the fields we actually need.
    Handles *old*, *mid-era*, and *2024-V2* shapes returned by Airbnb.
    """
    # three possible “wrappers”:
    listing = hit.get("listing") or hit                       # mid/V2 or old
    deep    = listing.get("listing") if isinstance(listing.get("listing"), dict) else {}

    pricing = hit.get("pricingQuote") or hit.get("price", {})
    rating  = listing.get("avgRating") or hit.get("rating", {})

    return {
        # id
        "id": (
            listing.get("id") or
            listing.get("listingId") or
            deep.get("id") or
            hit.get("id")
        ),

        # title / headline
        "title": (
            listing.get("name") or
            listing.get("title") or
            deep.get("name")
        ),

        # nightly price (string or number; keep raw for now)
        "price": (
            pricing.get("rate", {}).get("amount") or
            pricing.get("label")
        ),

        "rating":  rating.get("guestSatisfaction"),
        "reviews": rating.get("reviewsCount"),

        # coordinates
        "lat": (
            listing.get("lat") or
            (listing.get("coordinates") or {}).get("latitude") or
            deep.get("lat")
        ),
        "lon": (
            listing.get("lng") or
            (listing.get("coordinates") or {}).get("longitude") or
            deep.get("lng")
        ),

        "url": listing.get("url") or deep.get("url"),
    }


# ───────────────────────── routes ───────────────────────────────────────────
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

        pricing = pyairbnb.price.get(
            price_inp["api_key"], cookies, price_inp["impression_id"],
            price_inp["product_id"], check_in, check_out,
            2, "USD", "en", ""
        )

        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {"calendar": cal, "details": details, "pricing": pricing}
        )

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

    # validate & cast prices
    pmin = clean_num(price_min, 0)
    pmax = clean_num(price_max, 10000)
    if pmin >= pmax:
        raise HTTPException(400, "`price_min` must be lower than `price_max`")

    # bounding box from centre/radius
    deg   = miles_to_deg(radius)
    ne_la = lat + deg
    ne_lo = lon + deg
    sw_la = lat - deg
    sw_lo = lon - deg

    try:
        hits: List[Dict[str, Any]] = pyairbnb.search_all(
            check_in, check_out,
            ne_la, ne_lo, sw_la, sw_lo,
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


# ───────────────────────── sanity-check URLs ───────────────────────────────
#
# 1️⃣ single listing (replace ROOM_ID with a real id)
#    https://pyairbnb.onrender.com/calendar?room=7123549524411418888&check_in=2025-07-01&check_out=2025-07-03&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# 2️⃣ 5-mile comps around San Francisco (≤ $2000):
#    https://pyairbnb.onrender.com/search?lat=37.7749&lon=-122.4194&radius=5&price_min=0&price_max=2000&check_in=2025-08-10&check_out=2025-08-12&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# Both should now show real *ids* / *lat* / *lon*.
