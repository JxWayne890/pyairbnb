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
        # Retrieve room details
        details = pyairbnb.get_details(
            room_id=room,
            checkin=check_in,
            checkout=check_out,
            currency="USD",
            adults=2,
            proxy_url="",
            language="en"
        )

        # Retrieve calendar availability
        calendar = pyairbnb.get_calendar(room_id=room, checkin=check_in, checkout=check_out, proxy_url="")

        # Return both in JSON response
        return JSONResponse({
            "calendar": calendar,
            "details": details
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
