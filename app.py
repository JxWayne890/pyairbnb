"""
FastAPI wrapper around pyairbnb
──────────────────────────────
• /calendar   ⇒ availability + stay-specific pricing for ONE listing
• /search     ⇒ “comps” – nearby listings inside a radius box
"""

from __future__ import annotations
import os
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

import pyairbnb


# ────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")     # set on Render
_DEG_PER_MILE = 1 / 69.0                           # ≈ 0 .0144927°


def miles_to_deg(mi: float) -> float:
    """Very small-distance conversion miles ⇢ lat/lon degrees."""
    return mi * _DEG_PER_MILE


app = FastAPI()


# ────────────────────────────────────────────────────────────
# Health check
# ────────────────────────────────────────────────────────────
@app.get("/")
def index() -> dict:
    return {"status": "ok"}


# ────────────────────────────────────────────────────────────
# /calendar  – unchanged from earlier working version
# ────────────────────────────────────────────────────────────
@app.get("/calendar")
def calendar(
    room: str = Query(...,             description="Airbnb room ID"),
    check_in: str = Query(...,         description="YYYY-MM-DD"),
    check_out: str = Query(...,        description="YYYY-MM-DD"),
    token: str = Query(...,            description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 1. listing details (gives us API keys & cookies)
        details, price_inp, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # 2. stay-specific pricing
        price = pyairbnb.price.get(
            price_inp["api_key"],
            cookies,
            price_inp["impression_id"],      # NB: library expects the typo
            price_inp["product_id"],
            check_in,
            check_out,
            2,                   # adults
            "USD",
            "en",
            "",
        )

        # 3. availability snapshot for the month range that covers check-in/out
        cal = pyairbnb.get_calendar(room_id=room, checkin=check_in, checkout=check_out, proxy_url="")

        return JSONResponse({"calendar": cal, "details": details, "pricing": price})

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ────────────────────────────────────────────────────────────
# /search  – “comps” in a radius
# ────────────────────────────────────────────────────────────
@app.get("/search")
def search_listings(
    lat: float = Query(...,  description="centre latitude"),
    lon: float = Query(...,  description="centre longitude"),
    radius: float = Query(5.0, description="radius (miles)"),
    price_min: int = Query(0,     description="min nightly USD"),
    price_max: int = Query(2000,  description="max nightly USD"),
    check_in: Optional[str] = Query(None, description="optional YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="optional YYYY-MM-DD"),
    token: str = Query(...,       description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding-box for pyairbnb.search_all()
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        results = pyairbnb.search_all(
            check_in=check_in,
            check_out=check_out,
            ne_lat=f"{ne_lat}",
            ne_long=f"{ne_lon}",
            sw_lat=f"{sw_lat}",
            sw_long=f"{sw_lon}",
            zoom_value="12",
            currency="USD",
            language="en",
            price_min=price_min,    # INT  ✅
            price_max=price_max,    # INT  ✅
            proxy_url="",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {err}")

    # shrink each listing to the essential bits Justin needs
    comps: list[dict] = []
    for r in results:
        comps.append(
            {
                "id": r.get("id") or r.get("listingId"),
                "title": r.get("title"),
                "price_label": r.get("price", {}).get("label"),
                "persons": r.get("personCapacity"),
                "rating": r.get("rating", {}).get("guestSatisfaction"),
                "reviews": r.get("rating", {}).get("reviewsCount"),
                "lat": r.get("coordinates", {}).get("latitude"),
                "lon": r.get("coordinates", {}).get("longitude"),
                "url": r.get("url"),
            }
        )

    return JSONResponse(
        {
            "centre": {"lat": lat, "lon": lon},
            "radius_mi": radius,
            "count": len(comps),
            "listings": comps,
        }
    )
