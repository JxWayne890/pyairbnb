import os
import pyairbnb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/calendar")
def calendar(
    room: str = Query(..., description="Airbnb room ID"),
    check_in: str = Query(..., description="Check-in date in YYYY-MM-DD"),
    check_out: str = Query(..., description="Check-out date in YYYY-MM-DD"),
    token: str = Query(..., description="Authentication token")
):
    # Token validation
    expected_token = os.getenv("API_TOKEN", "changeme")
    if token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # Get raw data
        details, price_input, cookies = pyairbnb.details.get(
            f"https://www.airbnb.com/rooms/{room}",
            "en",  # language
            ""     # proxy_url
        )

        price_data = pyairbnb.price.get(
            api_key=price_input["api_key"],
            cookies=cookies,
            impression_id=price_input["impression_id"],
            product_id=price_input["product_id"],
            checkin=check_in,
            checkout=check_out,
            adults=2,
            currency="USD",
            language="en",
            proxy_url=""
        )

        calendar = pyairbnb.get_calendar(room_id=room, checkin=check_in, checkout=check_out, proxy_url="")

        return JSONResponse({
            "calendar": calendar,
            "details": details,
            "pricing": price_data
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
