"""
FastAPI service exposing two Airbnb endpoints

* /calendar  – listing-level availability, details and stay-specific pricing
* /search    – lightweight “comps” search inside a radius (miles)

Render-ready: set API_TOKEN in the Render dashboard or let it default to
“changeme” for local tests.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI()
API_TOKEN = os.getenv("API_TOKEN", "changeme")

# conversion helper (1 mile ≈ 0.01449°)
_DEG_PER_MILE = 1 / 69.0
miles_to_deg = lambda mi: mi * _DEG_PER_MILE  # noqa: E731


# ───────────────────── health-check ──────────────────────────────────────────
@app.get("/")
def index() -> dict[str, str]:
    return {"status": "ok"}


# ───────────────────── single-listing calendar/pricing ───────────────────────
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (numbers only)"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 1️⃣ listing-level details ------------------------------------------
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # 2️⃣ stay-specific pricing ------------------------------------------
        price = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            impresion_id=price_input["impression_id"],  # ← library spelling
            product_id=price_input["product_id"],
            checkin=check_in,
            checkout=check_out,
            adults=2,
            currency="USD",
            language="en",
            proxy_url="",
        )

        # 3️⃣ availability calendar (month snapshot) -------------------------
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {"calendar": calendar, "details": details, "pricing": price}
        )

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ───────────────────── comps search inside radius ────────────────────────────
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, description="Radius in miles (default 5)"),
    check_in: Optional[str] = Query(
        None, description="Optional check-in YYYY-MM-DD"
    ),
    check_out: Optional[str] = Query(
        None, description="Optional check-out YYYY-MM-DD"
    ),
    token: str = Query(..., description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding box from centre & radius
    deg = miles_to_deg(radius)
    ne_lat, ne_lng = lat + deg, lon + deg
    sw_lat, sw_lng = lat - deg, lon - deg

    try:
        results = pyairbnb.search_all(
            check_in=check_in,
            check_out=check_out,
            ne_lat=ne_lat,
            ne_lng=ne_lng,          # ← correct kwarg
            sw_lat=sw_lat,
            sw_lng=sw_lng,          # ← correct kwarg
            zoom_value=12,
            currency="USD",
            language="en",
            proxy_url="",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {err}")

    # slim payload for comps
    comps: list[dict] = []
    for listing in results:
        comps.append(
            {
                "id": listing.get("id") or listing.get("listingId"),
                "title": listing.get("title"),
                "price_label": listing.get("price", {}).get("label"),
                "persons": listing.get("personCapacity"),
                "rating": listing.get("rating", {}).get("guestSatisfaction"),
                "reviews": listing.get("rating", {}).get("reviewsCount"),
                "lat": listing.get("coordinates", {}).get("latitude"),
                "lon": listing.get("coordinates", {}).get("longitude"),
                "url": listing.get("url"),
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
