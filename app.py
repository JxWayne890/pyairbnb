"""
FastAPI wrapper around pyairbnb
──────────────────────────────

•  Install deps locally
      pip install fastapi uvicorn pyairbnb

•  Run locally
      uvicorn app:app --reload

Deploy exactly the same file to Render – the start-command
in your dashboard can stay:
      uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ────────────────────────────────────────────────────────────
# ENV – set API_TOKEN in Render  → Environment  (or keep “changeme” for local tests)
# ────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")

app = FastAPI(title="Justin-RADAR API", version="1.0.0")

# ---------------------------------------------------------------------------
# Helper – convert a distance in *miles* to decimal-degrees
# ( 1° ≈ 69 miles on the lat/lon grid )
# ---------------------------------------------------------------------------
_DEG_PER_MILE = 1 / 69.0


def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE


# ---------------------------------------------------------------------------
# Root – health check
# ---------------------------------------------------------------------------
@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# CALENDAR   ────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID, digits only"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # 1️⃣ listing-level details (and the extra payload needed for price)
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        # 2️⃣ price for the requested stay
        price_data = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],  # <- spelling is correct here
            price_input["product_id"],
            check_in,
            check_out,
            2,           # adults
            "USD",
            "en",
            "",
        )

        # 3️⃣ availability snapshot (Airbnb only gives ~3 months on graphQL)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {"calendar": calendar, "details": details, "pricing": price_data}
        )

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


# ---------------------------------------------------------------------------
# SEARCH  – “comps” inside a radius  (new)
# ---------------------------------------------------------------------------
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, description="Radius in miles (default 5)"),
    check_in: Optional[str] = Query(None, description="Optional check-in YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="Optional check-out YYYY-MM-DD"),
    price_min: int = Query(0, description="Min nightly price filter (USD)"),
    price_max: int = Query(10_000, description="Max nightly price filter (USD)"),
    token: str = Query(..., description="Auth token"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding-box for pyairbnb.search_all
    deg = miles_to_deg(radius)
    ne_lat = lat + deg
    ne_lon = lon + deg
    sw_lat = lat - deg
    sw_lon = lon - deg

    try:
        results = pyairbnb.search_all(
            check_in,
            check_out,
            price_min,
            price_max,
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            12,          # zoom_value (any int  10-15 works)
            "USD",
            "en",
            "",
        )
    except Exception as err:
        raise HTTPException(
            status_code=502, detail=f"pyairbnb.search_all failed: {err}"
        )

    # slim-down each listing to the columns Justin actually uses
    comps: list[dict] = []
    for r in results:
        comps.append(
            {
                "id": r.get("id") or r.get("listingId"),
                "title": r.get("title"),
                "price_label": r.get("price", {}).get("label"),
                "guests": r.get("personCapacity"),
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
