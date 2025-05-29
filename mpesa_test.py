import requests
import base64
from datetime import datetime

# Hardcoded credentials and parameters
consumer_key = "i7zGAABbKUU5x8KnDUqty7cJcuOFwS8REKePF7HnNG2J2yAE"
consumer_secret = "P4y1g6xaIUhNGBPxjDYclmTN7tlagiSwgAalrOJm9J9FkyK9do9vfSagLStp9xil"
business_shortcode = "174379"
passkey = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
phone_number = "254798292862"
callback_url = "https://yourdomain.com/callback"

# Function to obtain access token
def get_access_token():
    auth_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(auth_url, auth=(consumer_key, consumer_secret))
    response.raise_for_status()
    return response.json()["access_token"]

# Function to initiate STK Push
def initiate_stk_push():
    access_token = get_access_token()
    api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password_str = business_shortcode + passkey + timestamp
    password = base64.b64encode(password_str.encode()).decode()
    payload = {
        "BusinessShortCode": business_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": 1,
        "PartyA": phone_number,
        "PartyB": business_shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": callback_url,
        "AccountReference": "Test123",
        "TransactionDesc": "Payment for testing"
    }
    response = requests.post(api_url, json=payload, headers=headers)
    response.raise_for_status()
    print(response.json())

if __name__ == "__main__":
    initiate_stk_push()
    print("STK Push initiated successfully.")
    print("Check your phone for the payment request.")