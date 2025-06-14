"""
FastAPI wrapper around pyairbnb
–––––––––––––––––––––––––––––––
/           →  health-check
/calendar   →  availability (+pricing if parsable) for ONE listing
/search     →  lightweight comps search in a radius
"""

import os, time, uuid
from typing import Optional, List, Dict, Any

import httpx                       # ← NEW
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb                    # unchanged

API_TOKEN = os.getenv("API_TOKEN", "changeme")
_DEG_PER_MILE = 1 / 69.0           # 1 mi ≈ 0.01449°

# ────────────────────────────────────────────────────────────────────────────
# GraphQL fallback for new-style 20-digit listing ids
# ────────────────────────────────────────────────────────────────────────────
_GQL_ENDPOINT = "https://www.airbnb.com/api/v3/PdpAvailabilityCalendar"
_GQL_HASH     = "5a7a0e2b917a1d0403b5cfb4ba8d32c2d2b4f4099c61e7a3fb77f4e2a477f907"
_STD_HEADERS  = {
    "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_2) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/json",
}


def nightly_quote(room_id: str, check_in: str, check_out: str,
                  guests: int = 2) -> dict:
    """Hit Airbnb’s public GraphQL endpoint to obtain price bundle."""
    now_ms = int(time.time() * 1000)

    variables = {
        "request": {
            "count": 1,
            "listingId": str(room_id),
            "month": int(check_in[5:7]),
            "year": int(check_in[:4]),
            "checkIn": check_in,
            "checkOut": check_out,
            "adults": guests,
            "version": "1.9.4",
            "operationName": "PdpAvailabilityCalendar",
            "_intents": ["pricing_dates", "calendar_day"],
            "__refId": str(uuid.uuid4()),
            "_timestamp": now_ms,
        }
    }

    payload = {
        "operationName": "PdpAvailabilityCalendar",
        "variables":     variables,
        "extensions": {
            "persistedQuery": {"version": 1, "sha256Hash": _GQL_HASH}
        },
    }

    with httpx.Client(timeout=20, headers=_STD_HEADERS) as cli:
        r = cli.post(_GQL_ENDPOINT, json=payload)
        r.raise_for_status()
        return r.json()


# ────────────────────────────────────────────────────────────────────────────
# FastAPI
# ────────────────────────────────────────────────────────────────────────────
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
        "rating":  listing.get("avgRating") or
                   hit.get("rating", {}).get("guestSatisfaction"),
        "reviews": listing.get("reviewsCount") or
                   hit.get("rating", {}).get("reviewsCount"),
        "lat":     listing.get("lat") or
                   listing.get("coordinates", {}).get("latitude"),
        "lon":     listing.get("lng") or
                   listing.get("coordinates", {}).get("longitude"),
        "url":     listing.get("url"),
    }


# ───────── routes ─────────
@app.get("/")
def root() -> dict:
    return {"status": "ok", "ts": int(time.time())}


@app.get("/calendar")
def calendar(
    room: str,
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

        # ── try classic scraper first ───────────────────────────────────────
        pricing = None
        if price_input and price_input.get("impression_id"):
            try:
                pricing = pyairbnb.price.get(
                    price_input["api_key"], cookies,
                    price_input["impression_id"], price_input["product_id"],
                    check_in, check_out,
                    2, "USD", "en", ""
                )
            except Exception:
                pricing = None

        # ── fallback to GraphQL for 20-digit ids ───────────────────────────
        if pricing is None:
            try:
                gq = nightly_quote(room, check_in, check_out, guests=2)
                pricing = gq["data"]["presentation"]["stayProductDetailPage"]
            except Exception:
                pricing = None

        return JSONResponse({"calendar": cal,
                             "details": details,
                             "pricing": pricing})

    except Exception as e:
        raise HTTPException(
            404, f"Listing {room} not found or not parsable ({e})"
        )


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

    return {
        "centre":    {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count":     len(comps),
        "listings":  comps,
    }
