"""
FastAPI app for Airbnb data
===========================

Routes implemented
------------------
* **/calendar** – unchanged from earlier; returns availability, details and pricing for a single Airbnb *room_id*.
* **/search**   – NEW.  Given a lat/lon centre and a radius in **miles**, returns a *slim* list of nearby listings – this is Justin’s “comps”.

Drop this file into the repo (or copy just the new route into your existing
`app.py`) and redeploy.
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

import pyairbnb

# ---------------------------------------------------------------------------
# FastAPI instance
# ---------------------------------------------------------------------------
app = FastAPI()

# ---------------------------------------------------------------------------
# Helper – convert miles to degrees (rounded)
# 1 degree ≈ 69 miles ⇒ 1 mile ≈ 0.0144927536°
# ---------------------------------------------------------------------------
_DEG_PER_MILE = 1 / 69.0  # ~0.0144927

def miles_to_deg(mi: float) -> float:
    return mi * _DEG_PER_MILE

# ---------------------------------------------------------------------------
# CALENDAR endpoint (unchanged – keep if you already have it)
# ---------------------------------------------------------------------------
@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token")
):
    if token != os.getenv("API_TOKEN", "changeme"):
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        price = pyairbnb.price.get(
            api_key=price_input["api_key"],
            cookies=cookies,
            impression_id=price_input["impression_id"],
            product_id=price_input["product_id"],
            checkin=check_in,
            checkout=check_out,
            adults=2,
            currency="USD",
            language="en",
            proxy_url="",
        )

        calendar = pyairbnb.get_calendar(room_id=room, checkin=check_in, checkout=check_out, proxy_url="")

        return JSONResponse({"calendar": calendar, "details": details, "pricing": price})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")

# ---------------------------------------------------------------------------
# SEARCH / COMPS endpoint (NEW)
# ---------------------------------------------------------------------------
@app.get("/search")
def search_listings(
    lat: float = Query(..., description="Centre latitude"),
    lon: float = Query(..., description="Centre longitude"),
    radius: float = Query(5.0, description="Search radius in miles (default 5)"),
    check_in: Optional[str] = Query(None, description="Optional check‑in date YYYY‑MM‑DD"),
    check_out: Optional[str] = Query(None, description="Optional check‑out date YYYY‑MM‑DD"),
    token: str = Query(..., description="Auth token")
):
    """Return a light list of comparable Airbnb listings inside the radius."""
    if token != os.getenv("API_TOKEN", "changeme"):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Bounding box from centre & radius
    deg = miles_to_deg(radius)
    ne_lat = lat + deg
    ne_lon = lon + deg
    sw_lat = lat - deg
    sw_lon = lon - deg

    try:
        results = pyairbnb.search_all(
            check_in=check_in,
            check_out=check_out,
            ne_lat=ne_lat,
            ne_long=ne_lon,
            sw_lat=sw_lat,
            sw_long=sw_lon,
            zoom_value=12,
            currency="USD",
            language="en",
            proxy_url="",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {e}")

    # Keep only the key fields Justin needs – keeps payload light
    slim: list[dict] = []
    for listing in results:
        slim.append({
            "id": listing.get("id") or listing.get("listingId"),
            "title": listing.get("title"),
            "price_label": listing.get("price", {}).get("label"),
            "persons": listing.get("personCapacity"),
            "rating": listing.get("rating", {}).get("guestSatisfaction"),
            "reviews": listing.get("rating", {}).get("reviewsCount"),
            "lat": listing.get("coordinates", {}).get("latitude"),
            "lon": listing.get("coordinates", {}).get("longitude"),
            "url": listing.get("url"),
        })

    return JSONResponse({"centre": {"lat": lat, "lon": lon}, "radius_mi": radius, "count": len(slim), "listings": slim})

