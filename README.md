# AI Appointment Booker

An AI agent that makes outbound phone calls on your behalf to book appointments. You fill in the details, it calls the business, handles the conversation, and lets you know when it's done.

## Demo

[Watch the live demo](https://drive.google.com/file/d/1bJxD-qT02QcMbhTA8LbI57c_a8N98Ao8/view?usp=sharing) — a full simulated run with the agent booking an appointment at a fictional business.

## How it works

1. You submit appointment details through a Gradio UI
2. The app calls the business via Twilio
3. When the call connects, Twilio streams live audio to a FastAPI WebSocket
4. The audio is forwarded to OpenAI's Realtime API, which runs the conversation
5. When the booking is confirmed, the AI invites the business to hang up
6. Twilio records the call and sends it back for transcription via Whisper

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Gradio UI     │───▶│   FastAPI        │───▶│   Twilio        │
│   (Frontend)    │    │   (Server)       │    │   (Phone Calls) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │   OpenAI         │◀───│   WebSocket     │
                       │   (Realtime API) │    │   (Audio Stream)│
                       └──────────────────┘    └─────────────────┘
```

## Setup

**1. Install dependencies**
```bash
uv sync
```

**2. Configure environment variables** — copy `.env.example` to `.env` and fill in:
- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` — from your Twilio console
- `TWILIO_PHONE_NUMBER` — your Twilio number in E.164 format (e.g. +12025551234)
- `OPENAI_API_KEY` — from your OpenAI dashboard
- `WEBSOCKET_URL` — filled in automatically when you run the app

**3. Set up ngrok**

Twilio needs a publicly accessible URL to send audio to your local server. ngrok creates a secure tunnel from the internet to your machine, so Twilio can reach it.

- Sign up at [ngrok.com](https://ngrok.com) and grab your auth token from the dashboard
- Add it once so ngrok remembers it:
```bash
ngrok config add-authtoken <your-token>
```

When you run `python main.py`, ngrok starts automatically and the public URL is written to your `.env` — you don't need to manage it manually.

## Running the app

```bash
python main.py
```

This starts an ngrok tunnel, launches the FastAPI server on port 8000, and opens the Gradio UI at http://localhost:8001.


## Usage

Once the app is running, open http://localhost:8001 and fill in the form:

| Field | Example | Notes |
|---|---|---|
| Your Name | Kevin | Used for the reservation name |
| Appointment Type | restaurant reservation | Tells the AI what it's booking |
| Preferred Times | 7pm | Comma-separated for multiple (e.g. 6pm, 7pm) |
| Acceptable Time Range | 6pm - 9pm | Fallback if preferred time isn't available |
| Date | May 25, 2026 | Any natural format works |
| Business Phone | 2135550199 | 10-digit US number, no country code |
| Additional Details | Party of 2 | Anything the business might ask for |

Click **Make Call** and the AI will handle the rest. The call is recorded and a timestamped transcript is saved to `recordings_and_transcripts/` when it ends, using the format `MM-DD_HH-MM_appointment-type.wav` with a matching `.txt` transcript.

## Troubleshooting

**"Connection error" in Gradio** — make sure the FastAPI server started successfully and is running on port 8000.

**Calls not connecting** — check that ngrok is running and the `WEBSOCKET_URL` in `.env` matches the current ngrok tunnel. Restart `main.py` to get a fresh URL.


## Project structure

```
fastapi_server.py          # API endpoints and WebSocket handler
twilio_openai_handler.py   # Bridges Twilio audio to OpenAI Realtime API
gradio_frontend.py         # UI for submitting call details
main.py                    # Entry point — starts ngrok, FastAPI, and Gradio
test_generate_prompt.py    # Unit tests for the AI prompt generator
recordings_and_transcripts/ # Saved call recordings and Whisper transcripts
```

## Disclaimer

This software is for educational and demonstration purposes. Ensure compliance with local laws and regulations regarding automated calling systems. Always obtain proper consent before making automated calls to businesses or individuals.
