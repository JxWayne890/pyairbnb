import os
from datetime import datetime
import pyairbnb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI()

# ------------------------------------------------------------------
# Set this in Render → Environment  (or keep “changeme” for local tests)
API_TOKEN = os.getenv("API_TOKEN", "changeme")
# ------------------------------------------------------------------


@app.get("/")
def index() -> dict:
    """Health-check endpoint."""
    return {"status": "ok"}


@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID (numbers only)"),
    check_in: str = Query(..., description="YYYY-MM-DD"),
    check_out: str = Query(..., description="YYYY-MM-DD"),
    token: str = Query(..., description="Auth token matching API_TOKEN"),
):
    # ── 1. simple token-based auth ────────────────────────────────
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # ── 2. listing-level details  ──────────────────────────────
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}",
            "en",   # language
            ""      # proxy_url (none)
        )

        # ── 3. pricing for the requested stay  ─────────────────────
        price_data = pyairbnb.price.get(
            price_input["api_key"],          # ← 1st positional arg
            cookies,                         # ← 2nd
            price_input["impression_id"],    # ← 3rd  (spelling inside lib is ‘impresion_id’)
            price_input["product_id"],
            check_in,
            check_out,
            2,                               # adults
            "USD",
            "en",
            ""                                # proxy_url
        )

        # ── 4. availability calendar  ─────────────────────────────
        # current-month snapshot (pyairbnb::get_calendar takes only room_id + optional proxy)
        calendar = pyairbnb.get_calendar(room_id=room, proxy_url="")

        # ── 5. bundle it all up  ──────────────────────────────────
        return JSONResponse(
            {
                "calendar": calendar,
                "details":  details,
                "pricing":  price_data,
            }
        )

    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {err}")
