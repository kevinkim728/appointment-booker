import os
import json
import asyncio
import websockets
import requests
import whisper
from dotenv import load_dotenv
from twilio.rest import Client
from datetime import datetime

load_dotenv()

class TwilioRealtimeServer:
    def __init__(self):
        self.openai_ws = None
        self.twilio_connections = {}
        self.current_call_sid = None
        self.call_start_time = None            # timestamp of when the stream opened, used to skip the Twilio trial message
        self.twilio_client = Client(
            os.getenv('TWILIO_ACCOUNT_SID'),
            os.getenv('TWILIO_AUTH_TOKEN')
        )

    async def make_outbound_call(self, business_phone: str, user_context: dict):
        """Initiate an outbound call to a business"""
        try:
            self.call_context = user_context

            call = self.twilio_client.calls.create(
                to=business_phone,
                from_=os.getenv('TWILIO_PHONE_NUMBER'),
                url=f"{os.getenv('WEBSOCKET_URL').replace('wss://', 'https://').replace('/media-stream', '')}/webhook/voice",
                method='POST',
                record=True,
                recording_channels='mono',
                recording_status_callback=f"{os.getenv('WEBSOCKET_URL').replace('wss://', 'https://').replace('/media-stream', '')}/recording"
            )

            self.current_call_sid = call.sid
            print(f"✅ Call initiated. Call SID: {self.current_call_sid}")
            await self.connect_to_openai()         # pre-connect while the phone is still ringing
            return {
                "success": True,
                "call_sid": self.current_call_sid,
                "status": call.status
                }

        except Exception as e:
            print(f"❌ Failed to make outbound call: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def handle_twilio_message(self, data, twilio_ws):
        """Process messages from Twilio"""
        event = data.get('event')

        if event == 'start':
            if not self.openai_ws:
                await self.connect_to_openai()         # fallback if pre-connect didn't happen
            self.twilio_connections[data.get('streamSid')] = twilio_ws
            self.call_start_time = datetime.now()
            asyncio.create_task(self.silence_watchdog())

        elif event == 'media':
            audio_payload = data.get('media', {}).get('payload', '')
            elapsed = (datetime.now() - self.call_start_time).seconds if self.call_start_time else 0
            if audio_payload and self.openai_ws and elapsed >= 2:
                await self.send_audio_to_openai(audio_payload)

        elif event == 'stop':
            print("🛑 Call ended")
            if self.openai_ws:
                await self.openai_ws.close()
                self.openai_ws = None
            stream_sid = data.get('streamSid')
            if stream_sid in self.twilio_connections:
                del self.twilio_connections[stream_sid]

    async def connect_to_openai(self):
        """Open a WebSocket connection to OpenAI Realtime API and configure the session"""
        if self.openai_ws:
            return None

        url = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"
        }

        try:
            self.openai_ws = await websockets.connect(url, additional_headers=headers)
            print("✅ Connected to OpenAI Realtime API")

            instructions = self.generate_prompt()

            session_update = {
                "type": "session.update",
                "session": {
                    "type": "realtime",                      # required by the new OpenAI Realtime API
                    "instructions": instructions,
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},  # G.711 μ-law — matches Twilio's format so no conversion needed
                            "noise_reduction": {
                                "type": "near_field"           # filters background noise for close-talking mic (phone handset)
                            },
                            "turn_detection": {
                                "type": "semantic_vad",        # uses a model to detect when the user is truly done speaking
                                "eagerness": "auto"
                            }
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},  # G.711 μ-law — matches Twilio's format so no conversion needed
                            "voice": "marin",
                            "speed": 1.0
                        }
                    },
                    "tools": [
                    ]
                }
            }

            await self.openai_ws.send(json.dumps(session_update))
            asyncio.create_task(self.handle_openai_messages())

        except Exception as e:
            print(f"❌ Failed to connect to OpenAI: {e}")
            self.openai_ws = None

    def generate_prompt(self):
        """Generate dynamic prompt based on user context"""
        if not self.call_context:
            return "You are an AI assistant for booking appointments. Help the user schedule appointments on the users behalf."

        user_name = self.call_context.get('user_name', 'the user')
        appointment_type = self.call_context.get('appointment_type', 'an appointment')
        preferred_times = self.call_context.get('preferred_times', [])
        date = self.call_context.get('date', '')
        additional_details = self.call_context.get('additional_details', '')
        acceptable_range = self.call_context.get('acceptable_range', '')

        time_prefs = f"{', '.join(preferred_times)}" if preferred_times else ""

        prompt = f"""
## Role & Objective
You are a professional AI assistant making an outbound call on behalf of {user_name} to book a {appointment_type} for {date}. You are the caller — the person who answers is a business employee. Do not switch roles at any point in the conversation. Your goal is to confirm a booking at one of the preferred times. Success means a fully confirmed booking or a clear determination that no availability exists.

## Personality & Tone
- Friendly, concise, and professional
- 2-3 sentences per turn maximum
- Do NOT include sound effects or onomatopoeic expressions
- The conversation will be in English only

## Handling Unclear Audio
- IF you cannot hear or understand what was said, ask for clarification: "I'm sorry, could you repeat that?"
- Do NOT guess or assume what was said if the audio is unclear

## Conversation Flow
Follow these phases in order:

**Phase 1 — Introduction**
- Greet the business and state your purpose
- Example: "Hi, I'm calling on behalf of {user_name} to book a {appointment_type} for {date}. Do you have availability at {time_prefs}?"
- Your opening question must ask specifically about availability at {time_prefs} — do not ask the business what times they have open
- Exit criteria: business has responded to your greeting

**Handling Pauses**
- Long silences are normal on booking calls — the business may be checking a calendar or system
- If you get a turn after a long pause and the conversation is still in progress, wait silently rather than filling the gap
- Only speak if the silence has been unusually long, and keep it minimal: "I'm still here whenever you're ready"
- Never interpret silence as a "no" or a signal to move the conversation forward

**Phase 2 — Confirm Availability**
- If available at a preferred time: confirm which time and move to Phase 3
- If preferred time is unavailable, ask if there are any available times within the range provided: {acceptable_range}
- If nothing is available within the preferred time or acceptable range: move to Phase 4
- Exit criteria: availability is clearly confirmed or denied

> Remember: your role is the caller. Whatever the business asks, it's your job to answer. You do not act on behalf of the business.

**Phase 3 — Collect Details**
- Answer any questions the business asks (name, party size, contact, etc.)
- Name for the reservation: {user_name}
- Additional details to provide when asked: {additional_details}
- Do NOT volunteer all details at once — answer each question as it comes
- If asked for information you don't have, do NOT make it up. Tell them {user_name} will call back with that information.
- Exit criteria: business has confirmed all details and the booking is complete

**Phase 4 — Farewell & End Call**
- Thank the business and let them know they can hang up
- Example: "We're all set! Go ahead and hang up whenever you're ready." / "Thanks so much for your help, feel free to hang up!"
- Do NOT call any tools — wait for the business to end the call
"""

        return prompt

    async def send_audio_to_openai(self, audio_payload):
        """Send audio from Twilio to OpenAI"""
        if not self.openai_ws:
            return

        message = {
            "type": "input_audio_buffer.append",
            "audio": audio_payload
        }

        try:
            await self.openai_ws.send(json.dumps(message))
        except Exception as e:
            print(f"Error sending audio to OpenAI: {e}")


    async def handle_openai_messages(self):
        """Handle responses from OpenAI and send back to Twilio"""
        transcript_buffer = ""
        try:
            async for message in self.openai_ws:
                data = json.loads(message)

                if data.get('type') == 'response.output_audio_transcript.delta':
                    transcript_buffer += data.get('delta', '')

                elif data.get('type') == 'response.output_audio_transcript.done':
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] AI: {transcript_buffer}")
                    transcript_buffer = ""

                elif data.get('type') == 'response.output_audio.delta':
                    audio_data = data.get('delta', '')
                    if audio_data:
                        await self.send_audio_to_twilio(audio_data)

                elif data.get('type') == 'response.function_call_arguments.done':
                    function_name = data.get('name')
                    if function_name == 'terminate_call':
                        args = json.loads(data.get('arguments', '{}'))
                        reason = args.get('reason', 'ai_completed')
                        await self.terminate_call(self.current_call_sid, reason)
        except websockets.exceptions.ConnectionClosed:
            print("OpenAI connection closed")
        except Exception as e:
            print(f"Error handling OpenAI messages: {e}")


    async def send_audio_to_twilio(self, audio_data):
      """Send audio from OpenAI back to all active Twilio connections"""
      for stream_sid, twilio_ws in list(self.twilio_connections.items()): # list() prevents RuntimeError if we delete during iteration
          try:
              twilio_message = {
                  "event": "media",
                  "streamSid": stream_sid,
                  "media": {
                      "payload": audio_data
                  }
              }
              await twilio_ws.send_text(json.dumps(twilio_message))
          except Exception as e:
              print(f"Error sending audio to Twilio {stream_sid}: {e}")
              if stream_sid in self.twilio_connections:
                  del self.twilio_connections[stream_sid]


    async def silence_watchdog(self):
        """Terminate the call after 10 minutes regardless of state"""
        await asyncio.sleep(600)
        if self.openai_ws:
            print("⏱️ Max call duration reached — terminating")
            await self.terminate_call(self.current_call_sid, "max_duration")

    async def terminate_call(self, call_sid: str, reason: str = "completed"):
      """Terminate an active call"""
      try:
          self.twilio_client.calls(call_sid).update(status='completed')
          print(f"📞 Call terminated: {call_sid} - Reason: {reason}")
          await asyncio.sleep(2)

          if self.openai_ws:
              await self.openai_ws.close()
              self.openai_ws = None

          self.twilio_connections.clear()

          return {"success": True, "call_sid": call_sid, "reason": reason}

      except Exception as e:
          print(f"❌ Failed to terminate call {call_sid}: {e}")
          return {"success": False, "error": str(e)}


    async def transcribe_recording(self, recording_url: str, recording_sid: str):
      """Download recording from Twilio and transcribe using Whisper"""
      try:
          print(f"🎯 Starting download and transcription for recording: {recording_sid}")

          os.makedirs("recordings_and_transcripts", exist_ok=True)

          appointment_type = self.call_context.get('appointment_type', 'appointment') if self.call_context else 'appointment'
          clean_appointment_type = appointment_type.replace(' ', '_').replace('/', '_')

          auth = (os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
          response = requests.get(recording_url + '.wav', auth=auth)

          if response.status_code == 200:
              recording_filename = f"recordings_and_transcripts/{datetime.now().strftime('%m-%d_%H-%M')}_{clean_appointment_type}.wav"

              with open(recording_filename, 'wb') as f:
                  f.write(response.content)
              print(f"💾 Recording saved: {recording_filename}")

              if not hasattr(self, 'whisper_model'):
                  print("🔄 Loading Whisper model...")
                  self.whisper_model = whisper.load_model("base.en")

              print("🎤 Starting transcription...")
              result = self.whisper_model.transcribe(recording_filename)
              print("✅ Transcription completed")

              timestamped_lines = []
              for segment in result["segments"]: # one segment is roughly one sentence
                  start = segment["start"]
                  end = segment["end"]
                  text = segment["text"].strip()
                  timestamped_lines.append(f"[{start:.1f}s - {end:.1f}s]: {text}")

              transcript_filename = f"recordings_and_transcripts/{datetime.now().strftime('%m-%d_%H-%M')}_{clean_appointment_type}.txt"
              with open(transcript_filename, 'w') as f:
                  f.write('\n'.join(timestamped_lines))
              print(f"📝 Transcript saved: {transcript_filename}")

          else:
              print(f"❌ Failed to download recording: {response.status_code}")
              return None

      except Exception as e:
          print(f"❌ Download and transcription failed: {e}")
