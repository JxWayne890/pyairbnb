"""
Tiny FastAPI wrapper around pyairbnb
===================================

• /               – health-check
• /calendar       – 1 listing   ➜  cal + details + price
• /search         – many comps  ➜  slim list inside radius
"""

from __future__ import annotations
import os
from datetime import date, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb

# ────────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")
_DEG_PER_MILE = 1 / 69.0           # ≈ 0 .0144927536°
app = FastAPI()
# ────────────────────────────────────────────────────────────────


@app.get("/")
def index() -> dict:                     # health-check
    return {"status": "ok"}


# ─────────────────────────────  1 LISTING  ──────────────────────
@app.get("/calendar")
def calendar(
    room:      str  = Query(...,              description="Airbnb room-id"),
    check_in:  str  = Query(...,              description="YYYY-MM-DD"),
    check_out: str  = Query(...,              description="YYYY-MM-DD"),
    token:     str  = Query(...,              description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 1 · details page (gets api_key, impression_id, …)
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # 2 · price for this stay
        price = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],      # NB: exactly like this in lib
            price_input["product_id"],
            check_in,
            check_out,
            2,                                 # adults
            "USD",
            "en",
            ""
        )

        # 3 · calendar (no check-in/out args in current pyairbnb)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {"calendar": calendar, "details": details, "pricing": price}
        )

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ─────────────────────────────  MANY COMPS  ─────────────────────
@app.get("/search")
def search_listings(
    lat:       float = Query(...,                        description="centre lat"),
    lon:       float = Query(...,                        description="centre lon"),
    radius:    float = Query(5.0,                        description="miles"),
    price_min: int   = Query(0,                         description="USD"),
    price_max: int   = Query(5000,                      description="USD"),
    check_in:  str   = Query(
        default=(date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
        description="YYYY-MM-DD (default ~30 d ahead)"
    ),
    check_out: str   = Query(
        default=(date.today() + timedelta(days=32)).strftime("%Y-%m-%d"),
        description="YYYY-MM-DD (default +2 d)"
    ),
    token:     str   = Query(...,                       description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    deg = radius * _DEG_PER_MILE
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        raw = pyairbnb.search_all(
            check_in, check_out,
            ne_lat, ne_lon, sw_lat, sw_lon,
            zoom_value=12,
            price_min=price_min,
            price_max=price_max,
            currency="USD",
            language="en",
            proxy_url="",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {err}")

    # keep it *light*: only the fields Justin needs for comps
    comps: list[dict] = []
    for l in raw:
        comps.append({
            "id":      l.get("id") or l.get("listingId"),
            "title":   l.get("title"),
            "price":   l.get("price", {}).get("label"),
            "rating":  l.get("rating", {}).get("guestSatisfaction"),
            "reviews": l.get("rating", {}).get("reviewsCount"),
            "lat":     l.get("coordinates", {}).get("latitude"),
            "lon":     l.get("coordinates", {}).get("longitude"),
            "url":     l.get("url"),
        })

    return JSONResponse({
        "centre": {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count": len(comps),
        "listings": comps,
    })
