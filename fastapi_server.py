from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.get("/")
async def home():
    return HTMLResponse("<h1>Twilio Realtime Server</h1><p>Server is running!</p>")
