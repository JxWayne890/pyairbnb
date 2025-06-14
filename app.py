import os, pyairbnb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/calendar")
def calendar(
    room: str = Query(...),
    check_in: str = Query(...),
    check_out: str = Query(...),
    token: str = Query(...)
):
    if token != os.getenv("API_TOKEN", "changeme"):
        raise HTTPException(status_code=401, detail="Invalid token")

    data = pyairbnb.get_details(
        room_id=room,
        checkin=check_in,
        checkout=check_out,
        currency="USD",
        adults=2,
        proxy_url="",
        language="en"
    )

    calendar = pyairbnb.get_calendar(room, "", "")
    return JSONResponse({"calendar": calendar, "details": data})
