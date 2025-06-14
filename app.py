"""
FastAPI wrapper for pyairbnb
---------------------------

✔ /            – health-check
✔ /calendar    – details, nightly price & calendar for a single room_id
✔ /search      – lightweight “comps” list inside a radius (miles)

Replace the token below (or set API_TOKEN in your Render dashboard)
and redeploy.
"""

from __future__ import annotations
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb

API_TOKEN = os.getenv("API_TOKEN", "f1a6f9f0a2b14f2fb0d02d7ec23e3e52")
DEG_PER_MILE = 1 / 69.0          # ≈ 0.01449° per mile

app = FastAPI()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def miles_to_deg(mi: float) -> float:
    return mi * DEG_PER_MILE


def auth(token: str) -> None:
    if token != API_TOKEN:
        raise HTTPException(401, "Invalid token")


# ---------------------------------------------------------------------------
@app.get("/")
def index() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
@app.get("/calendar")
def calendar(
    room: str        = Query(..., description="Airbnb room ID"),
    check_in: str    = Query(..., description="YYYY-MM-DD"),
    check_out: str   = Query(..., description="YYYY-MM-DD"),
    token: str       = Query(..., description="Auth token")
):
    auth(token)
    try:
        details, price_inp, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )

        pricing = pyairbnb.price.get(
            price_inp["api_key"], cookies,
            price_inp["impression_id"], price_inp["product_id"],
            check_in, check_out, 2, "USD", "en", ""
        )

        # NOTE: get_calendar() **does NOT** take check-in/out (lib raises the error you saw)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        return JSONResponse({"calendar": calendar,
                             "details":  details,
                             "pricing":  pricing})
    except Exception as err:
        raise HTTPException(502, f"Error fetching data: {err}")


# ---------------------------------------------------------------------------
@app.get("/search")
def search_listings(
    lat: float                    = Query(...,  description="centre lat"),
    lon: float                    = Query(...,  description="centre lon"),
    radius: float                 = Query(5.0,  description="miles"),
    price_min: int                = Query(0,    description="min price/night USD"),
    price_max: int                = Query(2000, description="max price/night USD"),
    check_in: Optional[str]       = Query(None, description="YYYY-MM-DD (optional)"),
    check_out: Optional[str]      = Query(None, description="YYYY-MM-DD (optional)"),
    token: str                    = Query(...,  description="Auth token")
):
    auth(token)

    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        results = pyairbnb.search_all(
            str(check_in or ""), str(check_out or ""),
            str(ne_lat), str(ne_lon),
            str(sw_lat), str(sw_lon),
            str(price_min), str(price_max),
            "USD", "en", "12", ""      # zoom_value 12 is “city/ neighbourhood”
        )
    except Exception as err:
        raise HTTPException(502, f"pyairbnb search failed: {err}")

    slim = [{
        "id":   lst.get("id") or lst.get("listingId"),
        "title": lst.get("title"),
        "price": lst.get("price", {}).get("label"),
        "rating": lst.get("rating", {}).get("guestSatisfaction"),
        "reviews": lst.get("rating", {}).get("reviewsCount"),
        "lat": lst.get("coordinates", {}).get("latitude"),
        "lon": lst.get("coordinates", {}).get("longitude"),
        "url": lst.get("url"),
    } for lst in results]

    return JSONResponse({"centre": {"lat": lat, "lon": lon},
                         "radius_mi": radius,
                         "count": len(slim),
                         "listings": slim})
