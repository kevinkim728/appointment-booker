# gradio_frontend.py
import gradio as gr
import requests
import json

def make_appointment_call(user_name, appointment_type, preferred_times, user_phone, additional_details, business_phone):
    """Make an appointment call using the FastAPI backend"""

    # Convert preferred_times string to list (split by commas)
    times_list = [time.strip() for time in preferred_times.split(',') if time.strip()] # If theres a value in there, then add it to the list

    # Prepare the payload
    payload = {
        "user_name": user_name,
        "appointment_type": appointment_type,
        "preferred_times": times_list,
        "user_phone": '1'+ user_phone,
        "additional_details": additional_details,
        "business_phone": '1'+ business_phone
    }

    try:
        # Make request to your FastAPI backend
        response = requests.post("http://localhost:8000/make-call", json=payload)

        if response.status_code == 200:
            result = response.json()
            return f"✅ Call initiated successfully!\n\nCall SID: {result.get('call_sid')}\nStatus: {result.get('status')}"
        else:
            return f"❌ Error: {response.status_code}\n{response.text}"

    except Exception as e:
        return f"❌ Connection error: {str(e)}\n\nMake sure your FastAPI server is running on http://localhost:8000"
