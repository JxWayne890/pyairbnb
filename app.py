import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import pyairbnb

app = FastAPI()
API_TOKEN = os.getenv("API_TOKEN", "changeme")
_DEG_PER_MILE = 1 / 69.0
def miles_to_deg(mi: float) -> float: return mi * _DEG_PER_MILE

@app.get("/")
def index(): return {"status": "ok"}

@app.get("/calendar")
def calendar(
    room: str, check_in: str, check_out: str, token: str
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}", "en", ""
        )
        price = pyairbnb.price.get(
            price_input["api_key"],
            cookies,
            price_input["impression_id"],   # <- spelling inside lib
            price_input["product_id"],
            check_in, check_out,
            2, "USD", "en", ""
        )
        cal = pyairbnb.get_calendar(room_id=room, proxy_url="")
        return JSONResponse({"calendar": cal, "details": details, "pricing": price})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")

@app.get("/search")
def search_listings(
    lat: float, lon: float,
    radius: float = 5.0,
    price_min: float = Query(0),          # ★ new
    price_max: float = Query(99999),      # ★ new
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    token: str = Query(...)
):
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    deg = miles_to_deg(radius)
    ne_lat, ne_lon = lat + deg, lon + deg
    sw_lat, sw_lon = lat - deg, lon - deg

    try:
        results = pyairbnb.search_all(
            price_min, price_max,
            ne_lat, ne_lon,
            sw_lat, sw_lon,
            12, "USD", "en", ""
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"pyairbnb search failed: {e}")

    slim = [{
        "id":   r.get("id") or r.get("listingId"),
        "title":r.get("title"),
        "price_label": r.get("price",{}).get("label"),
        "persons":     r.get("personCapacity"),
        "rating":      r.get("rating",{}).get("guestSatisfaction"),
        "reviews":     r.get("rating",{}).get("reviewsCount"),
        "lat":         r.get("coordinates",{}).get("latitude"),
        "lon":         r.get("coordinates",{}).get("longitude"),
        "url":         r.get("url"),
    } for r in results]

    return JSONResponse({
        "centre": {"lat": lat, "lon": lon},
        "radius_mi": radius,
        "count": len(slim),
        "listings": slim,
    })
