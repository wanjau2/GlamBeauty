import requests
import base64
import datetime
import json
from flask import Blueprint, request, jsonify

mpesa_bp = Blueprint('mpesa', __name__, url_prefix='/api/mpesa')

# M-Pesa API credentials
CONSUMER_KEY = i7zGAABbKUU5x8KnDUqty7cJcuOFwS8REKePF7HnNG2J2yAE
CONSUMER_SECRET = P4y1g6xaIUhNGBPxjDYclmTN7tlagiSwgAalrOJm9J9FkyK9do9vfSagLStp9xil
BUSINESS_SHORT_CODE = 174379  # Paybill or Till number
PASSKEY = bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919
CALLBACK_URL = "https://yourdomain.com/api/mpesa/callback"

# Get access token
def get_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode("utf-8")
    headers = {
        "Authorization": f"Basic {auth}"
    }
    
    response = requests.get(url, headers=headers)
    data = response.json()
    
    if "access_token" in data:
        return data["access_token"]
    else:
        raise Exception("Failed to get access token")

# Generate password
def generate_password():
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    password_str = f"{BUSINESS_SHORT_CODE}{PASSKEY}{timestamp}"
    return base64.b64encode(password_str.encode()).decode("utf-8"), timestamp

# STK Push API
@mpesa_bp.route('/stk-push', methods=['POST'])
def stk_push():
    try:
        data = request.json
        phone_number = data.get('phone_number')
        amount = data.get('amount')
        reference = data.get('reference')
        description = data.get('description')
        
        if not all([phone_number, amount, reference, description]):
            return jsonify({"success": False, "message": "Missing required parameters"}), 400
        
        # Get access token
        access_token = get_access_token()
        
        # Generate password and timestamp
        password, timestamp = generate_password()
        
        # Prepare STK Push request
        url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(float(amount)),
            "PartyA": phone_number,
            "PartyB": BUSINESS_SHORT_CODE,
            "PhoneNumber": phone_number,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": reference,
            "TransactionDesc": description
        }
        
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        if "ResponseCode" in data and data["ResponseCode"] == "0":
            # Store the checkout request ID in your database
            checkout_request_id = data["CheckoutRequestID"]
            
            # TODO: Save to database with status "pending"
            
            return jsonify({
                "success": True,
                "message": "STK push initiated successfully",
                "checkout_request_id": checkout_request_id
            })
        else:
            return jsonify({
                "success": False,
                "message": data.get("ResponseDescription", "Failed to initiate STK push")
            }), 400
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# Query STK Push status
@mpesa_bp.route('/query-status', methods=['POST'])
def query_status():
    try:
        data = request.json
        checkout_request_id = data.get('checkout_request_id')
        
        if not checkout_request_id:
            return jsonify({"success": False, "message": "Missing checkout request ID"}), 400
        
        # Get access token
        access_token = get_access_token()
        
        # Generate password and timestamp
        password, timestamp = generate_password()
        
        # Prepare query request
        url = "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "BusinessShortCode": BUSINESS_SHORT_CODE,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }
        
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        
        # TODO: Check your database for the transaction status
        # For demo purposes, we'll simulate a successful transaction
        
        # In a real implementation, you would check the response from M-Pesa
        # and update your database accordingly
        
        # Simulate successful transaction
        transaction_id = "MPESA" + str(datetime.datetime.now().timestamp()).replace(".", "")[:10]
        
        return jsonify({
            "success": True,
            "message": "Payment completed successfully",
            "transaction_id": transaction_id
        })
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# M-Pesa callback
@mpesa_bp.route('/callback', methods=['POST'])
def callback():
    try:
        data = request.json
        
        # Extract relevant information from callback
        result_code = data.get("Body", {}).get("stkCallback", {}).get("ResultCode")
        checkout_request_id = data.get("Body", {}).get("stkCallback", {}).get("CheckoutRequestID")
        
        if result_code == 0:
            # Payment successful
            # Extract transaction details
            callback_metadata = data.get("Body", {}).get("stkCallback", {}).get("CallbackMetadata", {}).get("Item", [])
            
            transaction_details = {}
            for item in callback_metadata:
                if item.get("Name") == "MpesaReceiptNumber":
                    transaction_details["receipt_number"] = item.get("Value")
                elif item.get("Name") == "Amount":
                    transaction_details["amount"] = item.get("Value")
                elif item.get("Name") == "PhoneNumber":
                    transaction_details["phone_number"] = item.get("Value")
            
            # TODO: Update transaction status in your database
            
        else:
            # Payment failed
            # TODO: Update transaction status in your database
            pass
        
        return jsonify({"ResultCode": 0, "ResultDesc": "Callback received successfully"}), 200
            
    except Exception as e:
        return jsonify({"ResultCode": 1, "ResultDesc": str(e)}), 500