"""
FastAPI wrapper for pyairbnb
---------------------------

  •  /               → health-check
  •  /calendar       → details + pricing + calendar for **one** listing
  •  /search         → (optional) light “comps” search in a lat/long radius
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb

# ------------------------------------------------------------------ #
# basic config
# ------------------------------------------------------------------ #
API_TOKEN = os.getenv("API_TOKEN", "changeme")          # ← set on Render
DEG_PER_MILE = 1 / 69.0                                # rough lat/long ≈ miles

app = FastAPI()


# ------------------------------------------------------------------ #
# utilities
# ------------------------------------------------------------------ #
def miles_to_deg(miles: float) -> float:
    """Convert miles → decimal degrees (~ at US latitudes)."""
    return miles * DEG_PER_MILE


# ------------------------------------------------------------------ #
# health check
# ------------------------------------------------------------------ #
@app.get("/")
def index() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------ #
# 1) CALENDAR  •  full detail for **one** listing
# ------------------------------------------------------------------ #
@app.get("/calendar")
def calendar(
    room: str  = Query(..., description="Airbnb room-id   (digits only)"),
    check_in:  str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="must match API_TOKEN"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # --- 2a. listing-level details ------------------------------------
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}",
            "en",
            "",               # no proxy
        )

        # --- 2b. stay-specific pricing  -----------------------------------
        # NB: price.get **positional** signature:
        # (api_key, cookies,  impresion_id, product_id,
        #  checkIn, checkOut, adults,      currency, language, proxy_url)
        pricing = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],    # ← library variable is misspelt
            price_input["product_id"],
            check_in,                        # checkIn  (pos-arg #5)
            check_out,                       # checkOut (pos-arg #6)
            2,                               # adults
            "USD",
            "en",
            "",                              # proxy_url
        )

        # --- 2c. month view availability  ---------------------------------
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse(
            {"calendar": calendar, "details": details, "pricing": pricing}
        )

    except Exception as err:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data from Airbnb: {err}",
        )


# ------------------------------------------------------------------ #
# 2) SEARCH  •  quick “comps” around a point (optional)
# ------------------------------------------------------------------ #
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="centre latitude"),
    lon: float = Query(..., description="centre longitude"),
    radius: float = Query(5.0, description="search radius (miles)"),
    check_in:  Optional[str] = Query(None, description="YYYY-MM-DD (optional)"),
    check_out: Optional[str] = Query(None, description="YYYY-MM-DD (optional)"),
    token: str = Query(..., description="must match API_TOKEN"),
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    # bounding-box for the pyairbnb “search_all”
    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        raw = pyairbnb.search_all(
            check_in      = check_in,
            check_out     = check_out,
            ne_lat        = ne_lat,
            ne_long       = ne_lon,
            sw_lat        = sw_lat,
            sw_long       = sw_lon,
            zoom_value    = 12,
            currency      = "USD",
            language      = "en",
            proxy_url     = "",
        )
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"pyairbnb.search_all failed: {err}")

    # return a slimmed-down payload (keeps Render bandwidth small)
    comps: list[dict] = []
    for lst in raw:
        comps.append(
            {
                "id":      lst.get("id") or lst.get("listingId"),
                "title":   lst.get("title"),
                "price":   lst.get("price", {}).get("label"),
                "beds":    lst.get("personCapacity"),
                "rating":  lst.get("rating", {}).get("guestSatisfaction"),
                "reviews": lst.get("rating", {}).get("reviewsCount"),
                "lat":     lst.get("coordinates", {}).get("latitude"),
                "lon":     lst.get("coordinates", {}).get("longitude"),
                "url":     lst.get("url"),
            }
        )

    return JSONResponse(
        {
            "centre":  {"lat": lat, "lon": lon},
            "radius_mi": radius,
            "count":   len(comps),
            "listings": comps,
        }
    )
