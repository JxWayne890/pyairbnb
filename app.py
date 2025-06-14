"""
FastAPI wrapper around pyairbnb
—————————————
/calendar   – availability + pricing for ONE listing
/search     – lightweight comps search in a radius (Justin’s “RADAR”)
"""

from __future__ import annotations

import os, json, time
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

API_TOKEN = os.getenv("API_TOKEN", "changeme")
app = FastAPI()

# ╭─ helpers ─────────────────────────────────────────────────────────────╮
_DEG_PER_MILE = 1 / 69.0            # ≈ 0.01449° lat/lon per mile


def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


def clean_int(val: str | int | float | None, default: int) -> int:
    try:
        return int(float(val))
    except Exception:
        return default


def _slim(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the handful of fields the workflow needs."""
    listing = hit.get("listing") or hit                       # new / old
    pricing = hit.get("pricingQuote") or hit.get("price", {})
    return {
        "id":       listing.get("id") or listing.get("listingId"),
        "title":    listing.get("name") or listing.get("title"),
        "price":    pricing.get("rate", {}).get("amount")
                    or pricing.get("label"),
        "rating":   listing.get("avgRating")
                    or hit.get("rating", {}).get("guestSatisfaction"),
        "reviews":  listing.get("reviewsCount")
                    or hit.get("rating", {}).get("reviewsCount"),
        "lat":      listing.get("lat")
                    or listing.get("coordinates", {}).get("latitude"),
        "lon":      listing.get("lng")
                    or listing.get("coordinates", {}).get("longitude"),
        "url":      listing.get("url"),
    }


def _details_with_fallback(room_id: str) -> tuple[dict, dict, dict]:
    """
    Robust wrapper around pyairbnb.details.get():
    * first try the normal parser
    * if that returns (None, None, None) → fallback to a super-light page probe
    """
    deets, price_input, cookies = pyairbnb.details.get(
        f"https://www.airbnb.com/rooms/{room_id}", lang="en", proxy_url=""
    )
    if deets:
        return deets, price_input, cookies                       #  ← happy path

    # ── fallback – try to hit the public ics feed just to confirm the
    #    listing exists (this works even for many hotel / collection pages)
    cal_url = f"https://www.airbnb.com/calendar/ical/{room_id}.ics?s=1"
    try:
        ics_text = pyairbnb._http.simple_get(cal_url)
        if "BEGIN:VCALENDAR" in ics_text:
            # Fake-but-consistent placeholders so downstream logic keeps working
            dummy_price_input = {
                "api_key": "dummy", "impression_id": "0",
                "product_id": room_id,
            }
            return {}, dummy_price_input, {}
    except Exception:
        pass

    raise HTTPException(
        status_code=404,
        detail=f"Listing {room_id} not found or not parsable by pyairbnb",
    )

# ╰───────────────────────────────────────────────────────────────────────╯


@app.get("/")
def root() -> dict:
    return {"status": "ok", "ts": int(time.time())}


@app.get("/calendar")
def calendar(
    room: str       = Query(..., description="Airbnb numeric room id"),
    check_in: str   = Query(..., description="YYYY-MM-DD"),
    check_out: str  = Query(..., description="YYYY-MM-DD"),
    token: str      = Query(...),
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    # ── 1. robust listing details & pricing ──────────────────────────────
    details, price_input, cookies = _details_with_fallback(room)

    # pricing may still fail for hotels; handle gracefully
    pricing: dict | None = None
    if price_input.get("api_key") != "dummy":
        try:
            pricing = pyairbnb.price.get(
                price_input["api_key"], cookies,
                price_input["impression_id"], price_input["product_id"],
                check_in, check_out, 2, "USD", "en", "",
            )
        except Exception:
            pricing = None

    # ── 2. calendar (try html/json API first; fall back to ics) ──────────
    calendar_data: dict | str | None = None
    errs: list[str] = []

    # a. pyairbnb JSON calendar
    try:
        calendar_data = pyairbnb.get_calendar(room_id=room, proxy_url="")
    except Exception as e:
        errs.append(f"json-calendar: {e!s}")

    # b. fallback: raw .ics feed (always available, even if not very rich)
    if calendar_data is None:
        try:
            ics_url = f"https://www.airbnb.com/calendar/ical/{room}.ics?s=1"
            calendar_data = {"ics": ics_url}
        except Exception as e:
            errs.append(f"ics-calendar: {e!s}")

    if calendar_data is None:                # both strategies failed
        raise HTTPException(502, "; ".join(errs))

    return JSONResponse({
        "room_id":   room,
        "details":   details or None,
        "pricing":   pricing,
        "calendar":  calendar_data,
    })


@app.get("/search")
def search_listings(
    lat: float  = Query(...),
    lon: float  = Query(...),
    radius: float = Query(5.0),
    price_min: str = Query("0"),
    price_max: str = Query("10000"),
    check_in:  Optional[str] = Query(None),
    check_out: Optional[str] = Query(None),
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    pmin = clean_int(price_min, 0)
    pmax = clean_int(price_max, 10000)
    if pmin >= pmax:
        raise HTTPException(400, "`price_min` must be < `price_max`")

    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        raw_hits = pyairbnb.search_all(
            check_in, check_out,
            ne_lat, ne_lon, sw_lat, sw_lon,
            zoom_value=12,
            price_min=pmin, price_max=pmax,
            currency="USD", language="en", proxy_url=""
        )
    except Exception as err:
        raise HTTPException(502, f"search failed: {err}")

    return {
        "centre":    {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":     len(raw_hits),
        "listings":  [_slim(hit) for hit in raw_hits],
    }

# ╭───── quick smoke-tests (after each Render build) ─────────────────────╮
# • replace ROOM with a live id copied from airbnb.com/rooms/…            #
# • both should run without 500s                                          #
#                                                                         #
#  curl -s https://pyairbnb.onrender.com/calendar\?room=27955738\          #
#         "&check_in=2025-08-10&check_out=2025-08-12"\                    #
#         "&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52 | jq                   #
#                                                                         #
#  curl -s https://pyairbnb.onrender.com/search\?lat=37.7749\             #
#         "&lon=-122.4194&radius=5&price_min=0&price_max=2000"\           #
#         "&check_in=2025-08-10&check_out=2025-08-12"\                    #
#         "&token=f1a6f9f0a2b14f2fb0d02d7ec23e3e52 | jq                   #
# ╰───────────────────────────────────────────────────────────────────────╯
