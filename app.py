"""
FastAPI wrapper around pyairbnb
–––––––––––––––––––––––––––––––
/           →  health-check
/calendar   →  availability (+pricing if parsable) for ONE listing
/search     →  lightweight comps search in a radius
"""

import os, time
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb

API_TOKEN = os.getenv("API_TOKEN", "changeme")
_DEG_PER_MILE = 1 / 69.0            # 1 mi ≈ 0.01449°

app = FastAPI()


# ───────── helpers ─────────
def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


def clean_num(val: str | int | float, fallback: int) -> int:
    try:
        return int(float(val))
    except Exception:
        return fallback


def slim(hit: Dict[str, Any]) -> Dict[str, Any]:
    listing = hit.get("listing") or hit
    pricing = hit.get("pricingQuote") or hit.get("price", {})
    return {
        "id":      listing.get("id") or listing.get("listingId"),
        "title":   listing.get("name") or listing.get("title"),
        "price":   pricing.get("rate", {}).get("amount") or pricing.get("label"),
        "rating":  listing.get("avgRating") or hit.get("rating", {}).get("guestSatisfaction"),
        "reviews": listing.get("reviewsCount") or hit.get("rating", {}).get("reviewsCount"),
        "lat":     listing.get("lat") or listing.get("coordinates", {}).get("latitude"),
        "lon":     listing.get("lng") or listing.get("coordinates", {}).get("longitude"),
        "url":     listing.get("url"),
    }


# ───────── routes ─────────
@app.get("/")
def root() -> dict:
    return {"status": "ok", "ts": int(time.time())}


@app.get("/calendar")
def calendar(
    room: str,                               # numeric or numeric-ish
    check_in: str = Query(..., alias="check_in"),
    check_out: str = Query(..., alias="check_out"),
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")

        pricing = None
        if price_input and price_input.get("impression_id"):
            pricing = pyairbnb.price.get(
                price_input["api_key"], cookies,
                price_input["impression_id"], price_input["product_id"],
                check_in, check_out,
                2, "USD", "en", ""
            )

        return JSONResponse({"calendar": cal, "details": details, "pricing": pricing})

    except Exception as e:
        raise HTTPException(404, f"Listing {room} not found or not parsable ({e})")


@app.get("/search")
def search_listings(
    lat: float, lon: float,
    radius: float = Query(5.0),
    price_min: str = Query("0"), price_max: str = Query("10000"),
    check_in: Optional[str] = None, check_out: Optional[str] = None,
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")

    pmin, pmax = clean_num(price_min, 0), clean_num(price_max, 10000)
    if pmin >= pmax:
        raise HTTPException(400, "`price_min` must be lower than `price_max`")

    deg = miles_to_deg(radius)
    ne_lat, ne_lon, sw_lat, sw_lon = lat + deg, lon + deg, lat - deg, lon - deg

    try:
        hits: List[Dict[str, Any]] = pyairbnb.search_all(
            check_in, check_out,
            ne_lat, ne_lon, sw_lat, sw_lon,
            zoom_value=12,
            price_min=pmin, price_max=pmax,
            currency="USD", language="en", proxy_url=""
        )
    except Exception as e:
        raise HTTPException(502, f"pyairbnb search failed: {e}")

    comps = [slim(h) for h in hits]

    return {"centre": {"lat": lat, "lon": lon}, "radius_mi": radius,
            "count": len(comps), "listings": comps}
