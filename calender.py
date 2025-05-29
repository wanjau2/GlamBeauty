import os
from flask import Flask, redirect, request, session, url_for
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") # Use a secure random key in prod

# Allow OAuth2 over HTTP (dev only)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # :contentReference[oaicite:7]{index=7}

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def credentials_to_dict(creds):
    """Convert Credentials object to dict for storing in session."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

@app.route("/authorize")
def authorize():
    """Step 1: Redirect user to Google's OAuth 2.0 consent screen."""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    return redirect(auth_url)  # :contentReference[oaicite:8]{index=8}

@app.route("/oauth2callback")
def oauth2callback():
    """Step 2: Handle OAuth2 callback and store credentials."""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = credentials_to_dict(creds)
    return redirect(url_for("book"))

@app.route("/book")
def book():
    """Step 3: Create a calendar event after booking."""
    if "credentials" not in session:
        return redirect(url_for("authorize"))

    creds = Credentials(**session["credentials"])
    service = build("calendar", "v3", credentials=creds)

    # Example appointment details; replace with real booking data
    start_time = datetime.utcnow() + timedelta(hours=1)
    end_time = start_time + timedelta(minutes=60)

    event = {
        "summary": "Customer Appointment",
        "description": "Service booked via Flask app",
        "start": {
            "dateTime": start_time.isoformat() + "Z",
            "timeZone": "Africa/Nairobi",
        },
        "end": {
            "dateTime": end_time.isoformat() + "Z",
            "timeZone": "Africa/Nairobi",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 24 * 60},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    created_event = service.events().insert(calendarId="primary", body=event).execute()
    # Store updated credentials in session in case tokens were refreshed
    session["credentials"] = credentials_to_dict(creds)
    link = created_event.get("htmlLink")
    return f"✅ Appointment added to your Google Calendar: <a href='{link}' target='_blank'>{link}</a>"
