"""
FastAPI wrapper around *pyairbnb*
–––––––––––––––––––––––––––––––––
/calendar   – availability + pricing for ONE listing  (uses room-id)
/search     – lightweight comps search in a radius   (Justin’s “RADAR”)
"""

import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb     # un-modified library from your repo root

# ──────────────────────────── config ────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")
app       = FastAPI()

_DEG_PER_MILE = 1 / 69.0                                  # lat/long offset for 1 mi


# ──────────────────────────── helpers ───────────────────────────
def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


def to_int(value: str | int | float | None, fallback: int = 0) -> int:
    """Cast a query-arg safely to int (for price_min/max)."""
    try:
        return int(float(value))   # handles '', None, '123.45'
    except Exception:
        return fallback


def coerce_room_id(listing: Dict[str, Any]) -> Optional[int]:
    """
    PyAirbnb’s *details.get()* only understands the classic numeric **room-id**
    (as in https://airbnb.com/rooms/27955738).

    › Newer search endpoints sometimes return:
        • listing["id"]           →  1006452882983257600  (64-bit “Merlin” id)
        • listing["listingId"]    →  27955738             (classic id)
        • listing["legacyId"]     →  27955738             (rare)
    """
    bogus   = {"-1", "", None}
    cand_id = (
        listing.get("listingId")
        or listing.get("legacyId")
        or listing.get("id")
    )

    if cand_id in bogus:
        return None

    # 64-bit Merlin ­→ strip trailing 6 digits heuristic
    # e.g. 1006452882983257600  →  1006452883  (usually the real room-id)
    if isinstance(cand_id, (str, int)) and len(str(cand_id)) > 12:
        cand_id = int(str(cand_id)[:10])

    try:
        return int(cand_id)
    except Exception:
        return None


def slim(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Cut everything down to the bits your n8n flow actually needs."""
    listing  = hit.get("listing") or hit                     # new vs old shape
    pricing  = hit.get("pricingQuote") or hit.get("price", {})

    return {
        "id":      coerce_room_id(listing),
        "title":   listing.get("name") or listing.get("title"),
        "price":   pricing.get("rate", {}).get("amount") or pricing.get("label"),
        "rating":  listing.get("avgRating") or hit.get("rating", {}).get("guestSatisfaction"),
        "reviews": listing.get("reviewsCount") or hit.get("rating", {}).get("reviewsCount"),
        "lat":     listing.get("lat") or listing.get("coordinates", {}).get("latitude"),
        "lon":     listing.get("lng") or listing.get("coordinates", {}).get("longitude"),
        "url":     listing.get("url"),
    }


# ───────────────────────────── routes ───────────────────────────
@app.get("/")
def ping() -> dict:
    """Tiny health-check so Render shows “up” quickly in the dashboard."""
    return {"status": "ok", "ts": int(time.time())}


@app.get("/calendar")
def calendar(
    room:      int  = Query(..., description="Classic Airbnb room-id, e.g. 27955738"),
    check_in:  str  = Query(..., alias="check_in", description="YYYY-MM-DD"),
    check_out: str  = Query(..., alias="check_out", description="YYYY-MM-DD"),
    token:     str  = Query(..., description="Same token you set in Render’s env-vars")
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    # STEP 1 – grab listing details so we have all the secret tokens Airbnb needs
    try:
        details, price_inp, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )
        if details is None:
            raise ValueError("listing vanished")
    except Exception as err:
        raise HTTPException(404, f"Listing {room} not found or not parsable ({err})")

    # STEP 2 – nightly rate for the requested stay
    try:
        pricing = pyairbnb.price.get(
            price_inp["api_key"],
            cookies,
            price_inp["impresion_id"],          # ←  *MISSPELLING* kept on purpose
            price_inp["product_id"],
            check_in,
            check_out,
            2, "USD", "en", ""
        )
    except Exception as err:
        raise HTTPException(502, f"Airbnb pricing API failed: {err}")

    # STEP 3 – first-month availability snapshot
    try:
        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")
    except Exception as err:
        raise HTTPException(502, f"Airbnb calendar API failed: {err}")

    return JSONResponse({"calendar": cal, "details": details, "pricing": pricing})


@app.get("/search")
def search_listings(
    lat:        float        = Query(...),
    lon:        float        = Query(...),
    radius:     float        = Query(5.0),
    price_min:  str | int    = Query("0"),
    price_max:  str | int    = Query("10000"),
    check_in:   Optional[str]= Query(None, alias="check_in"),
    check_out:  Optional[str]= Query(None, alias="check_out"),
    token:      str          = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    pmin, pmax = to_int(price_min), to_int(price_max, 10000)
    if pmin >= pmax:
        raise HTTPException(400, "`price_min` must be lower than `price_max`")

    # bounding-box for Airbnb’s search endpoint
    deg          = miles_to_deg(radius)
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

    return JSONResponse({
        "centre":    {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":     len(comps),
        "listings":  comps,
    })


# ────────────────────── sanity-check URLs ───────────────────────
# After Render finishes building, paste these into a new tab:
#
# 1️⃣  /search  (5-mi comps around North Hills – Raleigh)
#     https://pyairbnb.onrender.com/search?lat=35.8377914&lon=-78.6423709&radius=5&price_min=0&price_max=2000&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# 2️⃣  /calendar of the *first* id returned by #1 (replace ROOM_ID)
#     https://pyairbnb.onrender.com/calendar?room=27955738&check_in=2025-08-10&check_out=2025-08-12&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52
#
# Both should now work end-to-end without “NoneType” or 502s.
