"""
pyairbnb FastAPI wrapper
-----------------------

* /calendar – availability, details & pricing for ONE listing
* /search   – lightweight list of listings (“comps”) in a radius

---------------------------------------------------------------
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ───────────────────────────────────────────────────────────────
API_TOKEN = os.getenv("API_TOKEN", "changeme")   # set in Render
DEG_PER_MILE = 1 / 69.0                          # ~0.0144927°
app = FastAPI()


# ───────────────────────── helpers ─────────────────────────────
def miles_to_deg(mi: float) -> float:
    """Very rough conversion miles → latitude/longitude degrees."""
    return mi * DEG_PER_MILE


def auth_or_401(tkn: str) -> None:
    if tkn != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


# ───────────────────────── endpoints ───────────────────────────
@app.get("/")
def index() -> dict:
    return {"status": "ok"}


@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (numbers only)"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    auth_or_401(token)

    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        price = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],      # ← note spelling in lib!
            price_input["product_id"],
            check_in,
            check_out,
            2,                  # adults
            "USD",
            "en",
            "",
        )

        # get_calendar() in the current version takes **only** room_id (+proxy)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({"calendar": calendar, "details": details, "pricing": price})

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")


@app.get("/search")
def search_listings(
    lat: float = Query(..., description="centre latitude"),
    lon: float = Query(..., description="centre longitude"),
    radius: float = Query(5.0, description="search radius in miles"),
    price_min: int = Query(0, description="minimum nightly price (USD)"),
    price_max: int = Query(100000, description="maximum nightly price (USD)"),
    check_in: Optional[str] = Query(None, description="optional YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="optional YYYY-MM-DD"),
    token: str = Query(..., description="Auth token"),
):
    auth_or_401(token)

    # bounding-box
    delta = miles_to_deg(radius)
    ne_lat, ne_lon = lat + delta, lon + delta
    sw_lat, sw_lon = lat - delta, lon - delta

    # pyairbnb.search_all parameter order (positional!):
    # check_in, check_out, ne_lat, ne_long, sw_lat, sw_long,
    # price_min, price_max, zoom, currency, language, proxy
    try:
        raw = pyairbnb.search_all(
            check_in,
            check_out,
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            price_min,
            price_max,
            12,              # zoom
            "USD",
            "en",
            "",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {err}")

    # --- slim down the payload so n8n / front-end won’t choke ----------
    out: list[dict] = []
    for lst in raw:
        out.append(
            {
                "id": lst.get("id") or lst.get("listingId") or "",
                "title": lst.get("title") or "",
                "price_label": lst.get("price", {}).get("label") or "",
                "persons": lst.get("personCapacity") or None,
                "rating": lst.get("rating", {}).get("guestSatisfaction") or None,
                "reviews": lst.get("rating", {}).get("reviewsCount") or None,
                "lat": lst.get("coordinates", {}).get("latitude"),
                "lon": lst.get("coordinates", {}).get("longitude"),
                "url": lst.get("url") or "",
            }
        )

    return JSONResponse(
        {
            "centre": {"lat": lat, "lon": lon},
            "radius_mi": radius,
            "count": len(out),
            "listings": out,
        }
    )
