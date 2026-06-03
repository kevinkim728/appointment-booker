import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import List, Optional
from twilio.twiml.voice_response import VoiceResponse
from twilio_openai_handler import TwilioRealtimeServer

load_dotenv()
app = FastAPI()
server = TwilioRealtimeServer()

class CallDetails(BaseModel):
    user_name: str = "user name"
    appointment_type: str = "restaurant reservation"
    preferred_times: List[str] = ["Tuesday 12-2"]
    date: Optional[str] = "date of reservation"
    additional_details: Optional[str] = "Party for 2"
    acceptable_range: Optional[str] = ""
    business_phone: str = "business-phone-number"

@app.get("/")
async def home():
    """
    Generic home page to validate if the server is running
    """
    return HTMLResponse("<h1>Twilio Realtime Server</h1><p>Server is running!</p>")

@app.post("/make-call")
async def initiate_outbound_call(request: CallDetails):
    """
    API endpoint to initiate outbound calls.
    Accepts CallDetails, strips out the business phone
    Triggers the outbound call
    """
    user_context = request.model_dump()
    business_phone = user_context['business_phone']

    if not business_phone:
      return {"error": "business_phone is required"}

    result = await server.make_outbound_call(business_phone, user_context)
    return result

@app.post("/webhook/voice")
async def handle_voice_webhook():
    """Handles incoming and outgoing Twilio voice calls"""
    response = VoiceResponse()
    connect = response.connect()
    connect.stream(url=os.getenv('WEBSOCKET_URL'))
    return Response(content=str(response), media_type="application/xml")

@app.post("/recording")
async def handle_recording_webhook(request: Request):
    form_data = await request.form() # Twilio sends recording callbacks as .form() data, not JSON
    recording_url = form_data.get('RecordingUrl')
    recording_sid = form_data.get('RecordingSid')
    recording_duration = form_data.get('RecordingDuration')

    print(f"📼 Recording completed: {recording_sid}")
    print(f"🔗 Recording URL: {recording_url}")
    print(f"⏱️  Duration: {recording_duration} seconds")

    await server.transcribe_recording(recording_url, recording_sid)

    return {"status": "received"}

@app.websocket("/media-stream")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Twilio Media Streams"""
    await websocket.accept()
    print("Twilio connected via FastAPI WebSocket")

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await server.handle_twilio_message(message, websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        print("Twilio WebSocket disconnected")

def start_server():
    """Start the FastAPI Server"""
    print("🌐 Starting FastAPI server on port 8000")
    print("📞 WebSocket ready on same port at /media-stream")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    start_server()
