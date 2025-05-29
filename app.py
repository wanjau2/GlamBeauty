from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
from datetime import datetime, timedelta , time as datetime_time
import time
from flask_mail import Mail, Message
import os
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField, PasswordField, SubmitField, BooleanField, SelectField, HiddenField, DateField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from functools import wraps
from functools import wraps
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
import csv
from io import StringIO
from flask import Response

#from notifications import init_scheduler

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Configure app
app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default-secret-key")
app.config["MONGO_URI"] = os.environ.get("MONGO_URI")
app.config["UPLOAD_FOLDER"] = "static/uploads"

app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "True").lower() in ["true", "1", "yes"]
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"])



# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Initialize extensions
try:
    mongo = PyMongo(app)
    # Test the connection
    mongo.db.command('ping')
    print("MongoDB Atlas connection successful!")
except Exception as e:
    print(f"MongoDB Atlas connection error: {e}")
    print("Creating fallback MongoDB connection...")
    
    # Create a fallback connection
    from pymongo import MongoClient
    try:
        client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=5000)
        db = client.get_database("GlamBeauty")
        # Create a wrapper object that mimics PyMongo's structure
        class MongoWrapper:
            def __init__(self, db):
                self.db = db
        
        mongo = MongoWrapper(db)
        print("Fallback MongoDB connection created successfully")
    except Exception as e:
        print(f"Fallback connection also failed: {e}")
        # Create a dummy mongo object for development
        class DummyCollection:
            def __init__(self, name):
                self.name = name
            
            def find(self, *args, **kwargs):
                return []
                
            def find_one(self, *args, **kwargs):
                return None
                
            def count_documents(self, *args, **kwargs):
                return 0
                
            def aggregate(self, *args, **kwargs):
                return []
        
        class DummyDB:
            def __getattr__(self, name):
                return DummyCollection(name)
                
            def list_collection_names(self):
                return []
                
            def command(self, *args, **kwargs):
                return {"ok": 1}
        
        class DummyMongo:
            def __init__(self):
                self.db = DummyDB()
        
        mongo = DummyMongo()
        print("Created dummy MongoDB connection for development")

csrf = CSRFProtect(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


def generate_time_choices(start_hour=9, end_hour=18, interval_minutes=30):
    choices = []
    current_time = datetime_time(start_hour, 0)
    end_time = datetime_time(end_hour, 0)
    while current_time <= end_time:
        choices.append((current_time.strftime('%H:%M'), current_time.strftime('%I:%M %p')))
        current_minute = current_time.minute + interval_minutes
        current_hour = current_time.hour + current_minute // 60
        current_minute %= 60
        if current_hour > 23: break
        current_time = datetime_time(current_hour, current_minute)
    return choices

class AppointmentForm(FlaskForm):
    service_id = HiddenField('Service ID')
    service = SelectField('Service', validators=[DataRequired()], choices=[])
    date = DateField('Appointment Date', validators=[DataRequired()], format='%Y-%m-%d')
    time = SelectField('Appointment Time', validators=[DataRequired()], choices=generate_time_choices())
    location_type = SelectField('Location Type', choices=[('salon', 'Salon Visit'), ('home', 'Home Service')], validators=[DataRequired()])
    county = SelectField('County', choices=[], validators=[Optional()])
    location = SelectField('Location/Sub-county', choices=[], validators=[Optional()])
    address = TextAreaField('Full Address (for Home Service)', validators=[Optional(), Length(max=200)],
                            render_kw={"placeholder": "Enter your street, building, house number etc."})
    notes = TextAreaField('Notes / Special Requests', validators=[Optional(), Length(max=500)],
                          render_kw={"placeholder": "Any specific requests or information?"})
    #sms_notifications = BooleanField('Receive SMS Notifications')
    submit = SubmitField('Confirm Booking')

class Product:
    def __init__(self, name, price, description, category, image=None, original_price=None, tags=None, reviews=None, rating=0, gallery_images=None, stock=0):
        self.name = name
        self.price = price
        self.description = description
        self.category = category
        self.image = image
        self.original_price = original_price
        self.tags = tags or []
        self.reviews = reviews or []
        self.rating = rating
        self.gallery_images = gallery_images or []
        self.stock = stock

        
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.email = user_data.get('email')
        self.name = user_data.get('name')
        self.is_admin = user_data.get('is_admin', False)
        self.phone = user_data.get('phone')
        self.address = user_data.get('address')
        self.birthdate = user_data.get('birthdate')
        self.city = user_data.get('city')
        self.county = user_data.get('county')
        self.postal_code = user_data.get('postal_code')
        self.profile_image = user_data.get('profile_image')
        self.created_at = user_data.get('created_at')
        self.user_data = user_data  # Store the entire user data

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("You don't have permission to access this page.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def credentials_to_dict(creds):
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

@app.route("/authorize_calendar")
def authorize_calendar():
    flow = Flow.from_client_secrets_file(
        "client_secret.json", 
        scopes=["https://www.googleapis.com/auth/calendar.events"],
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    auth_url, _ = flow.authorization_url(prompt="consent")
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        "client_secret.json", 
        scopes=["https://www.googleapis.com/auth/calendar.events"],
        redirect_uri=url_for("oauth2callback", _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = credentials_to_dict(creds)
    # Redirect back to the booking page or wherever appropriate
    return redirect(url_for("book_appointment"))

def add_to_google_calendar(appointment_data):
    """Add appointment to Google Calendar."""
    try:
        # Check if Google Calendar credentials are available
        credentials_file = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS")
        print(f"Credentials file path: {credentials_file}")
        
        if not credentials_file:
            print("Google Calendar credentials environment variable not set.")
            return False
            
        if not os.path.exists(credentials_file):
            print(f"Credentials file not found at path: {credentials_file}")
            return False
            
        # Validate appointment data
        required_fields = ['appointment_date', 'service_duration', 'service_name', 
                          'total_price', 'location_type', 'user_email', 'user_name']
        
        for field in required_fields:
            if field not in appointment_data:
                print(f"Missing required field in appointment data: {field}")
                return False
                
        if appointment_data['location_type'] == 'home' and 'address' not in appointment_data:
            print("Missing address for home service appointment")
            return False
            
        # Load credentials
        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=['https://www.googleapis.com/auth/calendar']
            )
            print("Credentials loaded successfully")
        except Exception as cred_error:
            print(f"Error loading credentials: {cred_error}")
            return False
        
        # Build the service
        try:
            service = build('calendar', 'v3', credentials=credentials)
            print("Calendar service built successfully")
        except Exception as service_error:
            print(f"Error building calendar service: {service_error}")
            return False
        
        # Format appointment data for Google Calendar
        start_time = appointment_data['appointment_date']
        end_time = start_time + timedelta(minutes=appointment_data['service_duration'])
        
        # Create event description
        description = f"Service: {appointment_data['service_name']}\n"
        description += f"Price: KES {appointment_data['total_price']:.2f}\n"
        
        if appointment_data['location_type'] == 'home':
            description += f"Location: Home Service - {appointment_data['address']}\n"
            if 'home_service_fee' in appointment_data and appointment_data['home_service_fee'] > 0:
                description += f"Home Service Fee: KES {appointment_data['home_service_fee']:.2f}\n"
        else:
            description += "Location: Salon Visit\n"
            
        if 'notes' in appointment_data and appointment_data['notes']:
            description += f"Notes: {appointment_data['notes']}\n"
        
        # Add customer information
        description += f"\nCustomer: {appointment_data['user_name']}\n"
        description += f"Email: {appointment_data['user_email']}\n"
        
        if 'county' in appointment_data and appointment_data['county']:
            description += f"County: {appointment_data['county']}\n"
            
        if 'location' in appointment_data and appointment_data['location']:
            description += f"Location: {appointment_data['location']}\n"
            
        # Create the event
        event = {
            'summary': f"Beauty Appointment: {appointment_data['service_name']}",
            'location': 'GlamBeauty Salon' if appointment_data['location_type'] == 'salon' else appointment_data['address'],
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Africa/Nairobi',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Africa/Nairobi',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 60},
                ],
            },
            'attendees': [
                {'email': appointment_data['user_email']},
            ],
            'sendUpdates': 'all',
        }
        
        # Add the event to the primary calendar
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        print(f"Using calendar ID: {calendar_id}")
        
        try:
            event = service.events().insert(calendarId=calendar_id, body=event).execute()
            print(f"Event created: {event.get('htmlLink')}")
            
            # Return the event ID and link
            return {
                'event_id': event.get('id'),
                'event_link': event.get('htmlLink')
            }
        except Exception as insert_error:
            print(f"Error inserting event: {insert_error}")
            return False
        
    except HttpError as error:
        print(f"An error occurred while creating Google Calendar event: {error}")
        print(f"Error details: {error.content}")
        return False
    except Exception as e:
        print(f"Unexpected error creating Google Calendar event: {e}")
        import traceback
        traceback.print_exc()
        return False

        
def send_email(subject, recipients, text_body, html_body):
    """Helper function to send emails."""
    if not isinstance(recipients, list):
        recipients = [recipients]
        
    if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
        print("WARN: MAIL_USERNAME or MAIL_PASSWORD not set. Email sending disabled.")
        return False
    
    try:
        msg = Message(subject, recipients=recipients)
        msg.body = text_body
        msg.html = html_body
        mail.send(msg)
        print(f"Email sent successfully to {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        # Log the error for debugging
        import traceback
        traceback.print_exc()
        return False

@app.route("/test-email")
@admin_required
def test_email():
    """Test email sending (admin only)"""
    try:
        send_email(
            subject="Test Email from GlamBeauty",
            recipients=[current_user.email],
            text_body="This is a test email from GlamBeauty.",
            html_body="<h1>Test Email</h1><p>This is a test email from GlamBeauty.</p>"
        )
        flash("Test email sent successfully!", "success")
    except Exception as e:
        flash(f"Error sending test email: {str(e)}", "danger")
    
    return redirect(url_for("admin_dashboard"))

def sanitize_input(text):
    if not text:
        return text
    
    # Remove MongoDB operators
    for operator in ['$', '{', '}', '(', ')', '[', ']']:
        text = text.replace(operator, '')
    
    return text

def safe_db_operation(operation, error_message="Database operation failed", default_return=None):
    try:
        return operation()
    except Exception as e:
        flash(error_message, "danger")
        print(f"Error: {error_message} - {str(e)}")
        return default_return

def validate_object_id(id_str):
    try:
        ObjectId(id_str)
        return True
    except:
        return False

def initialize_locations():
    """Initialize locations collection if it doesn't exist."""
    try:
        if "locations" not in mongo.db.list_collection_names():
            mongo.db.create_collection("locations")
            
            # Define initial locations data
            locations_data = []
            
            # Define which locations offer home service
            nairobi_home_service = ["Westlands", "Kilimani", "Langata", "Karen"]
            
            # Nairobi locations
            nairobi_locations = ["Nairobi CBD", "Westlands", "Kilimani", "Langata", "Karen", 
                                "South B", "South C", "Embakasi", "Kasarani"]
            for loc in nairobi_locations:
                locations_data.append({
                    "county": "Nairobi",
                    "location": loc,
                    "available_for_home_service": loc in nairobi_locations,
                    "home_service_fee": 500.00
                })
            
            # Kiambu locations
            kiambu_locations = ["Thika", "Juja", "Kiambu Town", "Ruiru"]
            for loc in kiambu_locations:
                locations_data.append({
                    "county": "Kiambu",
                    "location": loc,
                    "available_for_home_service": loc in ["Thika", "Juja","Ruiru","Kiambu Town"],
                    "home_service_fee": 400.00
                })
            
            # Kajiado locations
            kajiado_locations = ["Rongai", "Kitengela", "Ngong"]
            for loc in kajiado_locations:
                locations_data.append({
                    "county": "Kajiado",
                    "location": loc,
                    "available_for_home_service": True,
                    "home_service_fee": 300.00
                })
            
            # Insert locations into the database
            mongo.db.locations.insert_many(locations_data)
            print("Locations data initialized")
    except Exception as e:
        print(f"Error initializing locations: {e}")

# Initialize database collections
def create_collections():
    try:
        # Create collections if they don't exist
        if "users" not in mongo.db.list_collection_names():
            mongo.db.create_collection("users")
            # Create admin users
            if mongo.db.users.count_documents({"is_admin": True}) == 0:
                admin_users = [
                    {
                        "name": "peter",
                        "email": "muragepeter@gmail.com",
                        "password": generate_password_hash("password"),
                        "is_admin": True,
                        "created_at": datetime.now()
                    },
                    {
                        "name": "Eugene",
                        "email": "eugenewanjau@gmail.com",
                        "password": generate_password_hash("password"),
                        "is_admin": True,
                        "created_at": datetime.now()
                    }
                ]

                for user in admin_users:
                    user['wishlist'] = []


                mongo.db.users.insert_many(admin_users)
                print("Admin users created")

                mongo.db.users.update_many(
                    {"is_admin": False, "wishlist": {"$exists": False}},
                    {"$set": {"wishlist": []}}
                )

        
        # Create other collections
        collections = ["products", "categories", "orders","wishlist","testimonials", "appointments", "services","locations"]
        for collection in collections:
            if collection not in mongo.db.list_collection_names():
                mongo.db.create_collection(collection)
                print(f"Collection {collection} created")

        def reset_locations_collection():
            try:
            # Drop the existing collection
                mongo.db.locations.drop()
                print("Locations collection dropped")
                initialize_locations()
                return True
            except Exception as e:
                print(f"Error resetting locations collection: {e}")
                return False

        reset_locations_collection()
        print("Locations collection reset")
       
        # Update services with the new list
        if "services" in mongo.db.list_collection_names():
            # Check if services need to be updated
            if mongo.db.services.count_documents({}) == 0:
                # Define beauty services
                beauty_services = [
                    {"name": "Nail Care", "price": 35.00, "duration": 30, "category": "Nails"},
                    {"name": "Hair Styling", "price": 50.00, "duration": 60, "category": "Hair"},
                    {"name": "Professional Makeup", "price": 65.00, "duration": 45, "category": "Makeup"},
                    {"name": "Deep Conditioning Treatment", "price": 45.00, "duration": 45, "category": "Hair"},
                    {"name": "Basic Manicure", "price": 25.00, "duration": 30, "category": "Nails"},
                    {"name": "Gel Manicure", "price": 40.00, "duration": 45, "category": "Nails"},
                    {"name": "Custom Nail Art", "price": 55.00, "duration": 60, "category": "Nails"},
                    {"name": "Hair Colouring", "price": 85.00, "duration": 120, "category": "Hair"},
                    {"name": "Luxury Pedicure", "price": 50.00, "duration": 60, "category": "Nails"},
                    {"name": "Natural Makeup", "price": 45.00, "duration": 30, "category": "Makeup"},
                    {"name": "Glam Makeup", "price": 75.00, "duration": 60, "category": "Makeup"},
                    {"name": "Bridal Makeup", "price": 120.00, "duration": 90, "category": "Makeup"},
                    {"name": "Classic Lash Extension", "price": 80.00, "duration": 75, "category": "Lashes"},
                    {"name": "Volume Lash Extension", "price": 110.00, "duration": 90, "category": "Lashes"},
                    {"name": "Lash Lift & Tint", "price": 65.00, "duration": 60, "category": "Lashes"},
                    {"name": "Bridal Glam Package", "price": 250.00, "duration": 180, "category": "Packages"},
                    {"name": "Full Glam Package", "price": 180.00, "duration": 150, "category": "Packages"},
                    {"name": "Basic Henna Design", "price": 35.00, "duration": 30, "category": "Henna"},
                    {"name": "Party Henna Design", "price": 65.00, "duration": 60, "category": "Henna"},
                    {"name": "Bridal Henna Design", "price": 150.00, "duration": 120, "category": "Henna"}
                ]
                
                # Insert services into the database
                mongo.db.services.insert_many(beauty_services)
                print("Beauty services created")
            else:
                # Update existing services
                mongo.db.services.delete_many({})
                beauty_services = [
                    {"name": "Nail Care", "price": 500, "duration": 30, "category": "Nails", "image": "nail-care.jpg"},
                    {"name": "Hair Styling", "price": 1300, "duration": 60, "category": "Hair", "image": "hair-styling.jpg"},
                    {"name": "Professional Makeup", "price": 2000, "duration": 45, "category": "Makeup", "image": "professional-makeup.jpg"},
                    {"name": "Deep Conditioning Treatment", "price": 1500.00, "duration": 45, "category": "Hair", "image": "deep-conditioning.jpeg"},
                    {"name": "Basic Manicure", "price": 500, "duration": 30, "category": "Nails", "image": "basic-manicure.jpg"},
                    {"name": "Gel Manicure", "price": 700, "duration": 45, "category": "Nails", "image": "gel-manicure.jpeg"},
                    {"name": "Custom Nail Art", "price": 900, "duration": 60, "category": "Nails", "image": "nail-art.jpeg"},
                    {"name": "Hair Colouring", "price": 400, "duration": 120, "category": "Hair", "image": "hair-colouring.jpg"},
                    {"name": "Luxury Pedicure", "price": 1800, "duration": 60, "category": "Nails", "image": "luxury-pedicure.jpg"},
                    {"name": "Natural Makeup", "price": 800, "duration": 30, "category": "Makeup", "image": "natural-makeup.jpeg"},
                    {"name": "Glam Makeup", "price": 1500, "duration": 60, "category": "Makeup", "image": "glam-makeup.jpeg"},
                    {"name": "Bridal Makeup", "price": 1800, "duration": 90, "category": "Makeup", "image": "bridal-makeup.jpeg"},
                    {"name": "Classic Lash Extension", "price": 1800, "duration": 75, "category": "Lashes", "image": "classic-lash.jpeg"},
                    {"name": "Volume Lash Extension", "price": 3500, "duration": 90, "category": "Lashes", "image": "volume-lash.jpeg"},
                    {"name": "Lash Lift & Tint", "price": 5000, "duration": 60, "category": "Lashes", "image": "lash-lift-tint.jpg"},
                    {"name": "Bridal Glam Package", "price": 8000, "duration": 180, "category": "Packages", "image": "bridal-package.jpeg"},
                    {"name": "Full Glam Package", "price": 6000, "duration": 150, "category": "Packages", "image": "full-glam-package.jpeg"},
                    {"name": "Basic Henna Design", "price": 300, "duration": 30, "category": "Henna", "image": "basic-henna.jpg"},
                    {"name": "Party Henna Design", "price": 800, "duration": 60, "category": "Henna", "image": "party-henna.jpg"},
                    {"name": "Bridal Henna Design", "price": 4000, "duration": 120, "category": "Henna", "image": "bridal-henna.jpg"}
                ]
                mongo.db.services.insert_many(beauty_services)
                print("Beauty services updated")

    except Exception as e:
        print(f"Error creating collections: {e}")

# Call the function to initialize collections
create_collections()

# Helper functions for chart data
def get_sales_chart_data():
    # Get sales data for the last 7 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=6)
    
    labels = []
    data = []
    
    for i in range(7):
        date = start_date + timedelta(days=i)
        next_date = date + timedelta(days=1)
        
        # Format date for label
        labels.append(date.strftime("%b %d"))
        
        # Get total sales for this day
        daily_sales = sum(
            order.get("total_price", 0) 
            for order in mongo.db.orders.find({
                "created_at": {"$gte": date, "$lt": next_date}
            })
        )
        
        data.append(daily_sales)
    
    return {"labels": labels, "data": data}


def get_products_chart_data():
    # Get top 5 selling products
    pipeline = [
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.product_id", "total": {"$sum": "$items.quantity"}}},
        {"$sort": {"total": -1}},
        {"$limit": 5}
    ]
    
    top_products = list(mongo.db.orders.aggregate(pipeline))
    
    labels = []
    data = []
    
    for product in top_products:
        product_info = mongo.db.products.find_one({"_id": product["_id"]})
        if product_info:
            labels.append(product_info["name"])
            data.append(product["total"])
    
    return {"labels": labels, "data": data}

# Add this after your app initialization but before route definitions

@app.context_processor
def inject_design_system():
    """Inject design system variables into all templates"""
    return {
        "design_system": {
            "colors": {
                "background": "hsl(350 100% 98%)",  # Soft Pink
                "primary": "hsl(340 73% 73%)",      # Soft Dusty Rose
                "primary_foreground": "hsl(0 0% 100%)",  # White
                "secondary": "hsl(20 60% 95%)",     # Soft Peach
                "secondary_foreground": "hsl(340 30% 46.9%)",  # Muted Mauve
                "accent": "hsl(43 96% 76%)",        # Soft Gold
                "accent_foreground": "hsl(340 5.9% 10%)",  # Dark Charcoal
                "muted": "hsl(350 60% 96%)",        # Very Light Pink
                "muted_foreground": "hsl(340 30% 46.9%)"  # Soft Mauve
            },
            "typography": {
                "font_family": "system-ui, sans-serif",
                "font_sizes": {
                    "xs": "0.75rem",
                    "sm": "0.875rem",
                    "base": "1rem",
                    "lg": "1.125rem",
                    "xl": "1.25rem",
                    "2xl": "1.5rem",
                    "3xl": "1.875rem",
                    "4xl": "2.25rem",
                    "5xl": "3rem"
                }
            },
            "spacing": {
                "1": "0.25rem",
                "2": "0.5rem",
                "3": "0.75rem",
                "4": "1rem",
                "5": "1.25rem",
                "6": "1.5rem",
                "8": "2rem",
                "10": "2.5rem",
                "12": "3rem",
                "16": "4rem"
            }
        }
    }

# --- DEFINE GLOBAL CONFIGURATION VARIABLES & FUNCTIONS ---
# Define these *before* the inject_global_vars context processor

STANDARD_DELIVERY_FEE = 400.00
HOME_SERVICE_FEE = 400.00
# Set a high threshold if free delivery is purely location-based,
# or adjust if there's also a minimum spend for free delivery.
FREE_DELIVERY_THRESHOLD = 5000.00 # Effectively disables threshold-based free delivery

FREE_DELIVERY_COUNTIES = ["Nairobi"]
FREE_DELIVERY_LOCATIONS = {
    "Kiambu": ["Thika", "Juja"],
    "Kajiado": ["Rongai", "Kitengela", "Ngong"]
}
HOME_SERVICE_LOCATIONS = ["Langata", "Karen", "Rongai", "Kilimani", "Westlands", "South B", "South C","Embakasi","Kasarani"]

# Assumption: Pay on delivery is available in free delivery areas. Adjust if needed.
PAY_ON_DELIVERY_COUNTIES = FREE_DELIVERY_COUNTIES
PAY_ON_DELIVERY_LOCATIONS = FREE_DELIVERY_LOCATIONS

# Define all available locations for dropdowns
AVAILABLE_LOCATIONS = [
    {
        'county': 'Nairobi',
        'locations': [
            {'name': 'Nairobi CBD'}, {'name': 'Westlands'}, {'name': 'Kilimani'},
            {'name': 'Langata'}, {'name': 'Karen'}, {'name': 'South B'},
            {'name': 'South C'}, {'name': 'Embakasi'}, {'name': 'Kasarani'},
            # Add other specific Nairobi locations...
            {'name': 'Other Nairobi'}
        ]
    },
    {
        'county': 'Kiambu',
        'locations': [
            {'name': 'Thika'}, {'name': 'Juja'}, {'name': 'Kiambu Town'},
            {'name': 'Ruiru'},
            # Add other specific Kiambu locations...
            {'name': 'Other Kiambu'}
        ]
    },
    {
        'county': 'Kajiado',
        'locations': [
            {'name': 'Rongai'}, {'name': 'Kitengela'}, {'name': 'Ngong'},
            {'name': 'Kajiado Town'}, {'name': 'Ongata Rongai'},
            # Add other specific Kajiado locations...
            {'name': 'Other Kajiado'}
        ]
    },
    {
        'county': 'Mombasa',
        'locations': [
            {'name': 'Mombasa CBD'}, {'name': 'Nyali'}, {'name': 'Likoni'},
            # Add other specific Mombasa locations...
            {'name': 'Other Mombasa'}
        ]
    },
    # Add other counties and their specific locations...
    {
        'county': 'Nakuru',
        'locations': [{'name':'Nakuru Town'}, {'name':'Naivasha'}, {'name':'Other Nakuru'}]
    },
     {
        'county': 'Kisumu',
        'locations': [{'name':'Kisumu City'}, {'name':'Other Kisumu'}]
    },
    # Fallback for areas not explicitly listed
    {
        'county': 'Other Kenya',
        'locations': [{'name': 'Other Kenya Location'}]
    }
]

# Add pay_on_delivery_allowed and home_service flags dynamically
for county_data in AVAILABLE_LOCATIONS:
    county = county_data['county']
    for loc in county_data['locations']:
        location_name = loc['name']
        # Pay on Delivery Logic
        is_pod_county = county in PAY_ON_DELIVERY_COUNTIES
        is_pod_location = county in PAY_ON_DELIVERY_LOCATIONS and location_name in PAY_ON_DELIVERY_LOCATIONS.get(county, []) # Use .get for safety
        loc['pay_on_delivery_allowed'] = is_pod_county or is_pod_location

        # Home Service Logic (based on location name only in this example)
        loc['home_service'] = location_name in HOME_SERVICE_LOCATIONS


# --- Helper Functions ---
def calculate_delivery_fee(county, location , total=0):
    """Calculates delivery fee based on location."""
    if county is None and current_user.is_authenticated:
        user_data = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
        if user_data:
            county = user_data.get("county")
            location = user_data.get("city")

    if county in FREE_DELIVERY_COUNTIES:
        return 0.00
    if county in FREE_DELIVERY_LOCATIONS and location in FREE_DELIVERY_LOCATIONS.get(county, []): # Use .get for safety
        return 0.00
    # Add logic for FREE_DELIVERY_THRESHOLD if applicable
    if total >= FREE_DELIVERY_THRESHOLD:
        return 0.00
    return STANDARD_DELIVERY_FEE

def is_home_service_available(county, location):
    """Checks if home service is available for a specific location."""
    location_data = safe_db_operation(
        lambda: mongo.db.locations.find_one({
            "county": county,
            "location": location
        }),
        "Failed to check home service availability",
        default_return=None
    )
    
    return location_data and location_data.get("available_for_home_service", False)

def calculate_home_service_fee(county, location):
    """Returns the home service fee from the database if available, otherwise default fee."""
    location_data = safe_db_operation(
        lambda: mongo.db.locations.find_one({
            "county": county,
            "location": location
        }),
        "Failed to fetch location details",
        default_return=None
    )
    
    return location_data.get("home_service_fee", HOME_SERVICE_FEE) if location_data else HOME_SERVICE_FEE
def get_profile_data(user_id):
    # Fetch user data first to get the wishlist
    user_data = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    wishlist_product_ids = []
    if user_data and 'wishlist' in user_data:
        # Ensure IDs are ObjectIds, handling potential strings if necessary
        wishlist_product_ids = [ObjectId(pid) for pid in user_data['wishlist'] if validate_object_id(str(pid))]

    orders = list(mongo.db.orders.find({"user_id": ObjectId(user_id)}).sort("created_at", -1))
    appointments = list(mongo.db.appointments.find({"user_id": ObjectId(user_id)}).sort("appointment_date", -1))

    # Fetch product details for wishlist items
    wishlist_products_list = []
    if wishlist_product_ids:
         wishlist_products_list = list(mongo.db.products.find({"_id": {"$in": wishlist_product_ids}}))

    # Structure wishlist products as a dictionary: {product_id_str: product_doc}
    wishlist_products_dict = {str(product['_id']): product for product in wishlist_products_list}

    # Format dates
    for order in orders:
        # Ensure created_at is a datetime object before formatting
        if isinstance(order.get('created_at'), datetime):
             order['created_at_formatted'] = order['created_at'].strftime('%d %b %Y, %H:%M')
        else:
             order['created_at_formatted'] = "N/A" # Or handle as appropriate

    for appt in appointments:
         # Ensure appointment_date is a datetime object before formatting
        if isinstance(appt.get('appointment_date'), datetime):
            appt['appointment_date_formatted'] = appt['appointment_date'].strftime('%d %b %Y')
        else:
            appt['appointment_date_formatted'] = "N/A" # Or handle as appropriate

    return {
        "orders": orders,
        "appointments": appointments,
        # Pass the dictionary of wishlist products
        "wishlist_items": wishlist_products_dict
    }

# --- END GLOBAL CONFIGURATION VARIABLES & FUNCTIONS ---


@app.context_processor
def inject_global_vars():
    """Inject global variables and functions into all templates"""
    cart_count = 0
    if 'cart' in session:
        cart_count = sum(item['quantity'] for item in session['cart'])

    # Fetch categories for navbar dropdown
    nav_categories = safe_db_operation(
        lambda: list(mongo.db.categories.find().sort("name", 1)),
        "Failed to fetch categories for navbar",
        []
    )

    # Fetch services for navbar dropdown
    nav_services = safe_db_operation(
        lambda: list(mongo.db.services.find().sort("name", 1)),
        "Failed to fetch services for navbar",
        []
    )

    # Variables and functions defined earlier in the file
    return dict(
        cart_count=cart_count, # Use consistent name
        nav_categories=nav_categories, # Add nav categories
        nav_services=nav_services,     # Add nav services
        AVAILABLE_LOCATIONS=AVAILABLE_LOCATIONS, # Pass the structured list with flags
        STANDARD_DELIVERY_FEE=STANDARD_DELIVERY_FEE,
        HOME_SERVICE_FEE=HOME_SERVICE_FEE,
        FREE_DELIVERY_THRESHOLD=FREE_DELIVERY_THRESHOLD,
        # Pass the helper functions
        calculate_delivery_fee=calculate_delivery_fee,
        is_home_service_available=is_home_service_available,
        calculate_home_service_fee=calculate_home_service_fee
    )


@app.route("/profile/appointments")
@login_required
def profile_appointments():
    """Display user appointments tab."""
    profile_data = get_profile_data(current_user.id)
    
    # Split appointments into upcoming and past
    upcoming_appointments = []
    past_appointments = []
    
    if profile_data["appointments"]:

        for appointment in profile_data["appointments"]:
            if appointment.get('status') == "cancelled":
                continue
            # Check if appointment date is in the future
            if isinstance(appointment.get('appointment_date'), datetime) and appointment['appointment_date'] > datetime.now():
                upcoming_appointments.append(appointment)
            else:
                past_appointments.append(appointment)
    
    return render_template(
        "user/profile.html",
        user=current_user,
        orders=profile_data["orders"],
        upcoming_appointments=upcoming_appointments,
        past_appointments=past_appointments,
        wishlist_products=profile_data["wishlist_items"],
        active_tab='appointments' # Set active tab
    )

@app.route("/profile/orders")
@login_required
def profile_orders():
    """Display user orders tab."""
    profile_data = get_profile_data(current_user.id)
    return render_template(
        "user/profile.html",
        user=current_user,
        orders=profile_data["orders"],
        appointments=profile_data["appointments"],
        wishlist_products=profile_data["wishlist_items"],
        active_tab='orders' # Set active tab
    )

@app.route("/profile/wishlist")
@login_required
def profile_wishlist():
    """Display user wishlist tab."""
    profile_data = get_profile_data(current_user.id)
    
    return render_template(
        "user/wishlist.html",
        user=current_user,
        orders=profile_data["orders"],
        appointments=profile_data["appointments"],
        wishlist_items=profile_data["wishlist_items"], # Changed to match the key in get_profile_data
        active_tab='wishlist' # Set active tab
    )

@app.route('/add_to_wishlist/<product_id>', methods=['POST'])
@login_required
def add_to_wishlist(product_id):
    """Adds a product to the current user's wishlist."""
    if not validate_object_id(product_id):
        flash('Invalid product ID.', 'danger')
        return redirect(request.referrer or url_for('shop')) # Redirect back

    product_object_id = ObjectId(product_id)

    # Add the product ObjectId to the user's wishlist array if not already present
    result = mongo.db.users.update_one(
        {'_id': ObjectId(current_user.id)},
        {'$addToSet': {'wishlist': product_object_id}} # Use $addToSet to avoid duplicates
    )

    if result.modified_count > 0:
        flash('Item added to your wishlist!', 'success')
    else:
        # Check if it was already there
        user = mongo.db.users.find_one({'_id': ObjectId(current_user.id), 'wishlist': product_object_id})
        if user:
            flash('Item is already in your wishlist.', 'info')
        else:
             # This case might indicate an issue, but $addToSet handles non-addition gracefully
             flash('Could not add item to wishlist.', 'warning')


    return redirect(request.referrer or url_for('shop'))

@app.route('/remove_from_wishlist/<product_id>', methods=['POST'])
@login_required
def remove_from_wishlist(product_id):
    """Removes a product from the current user's wishlist."""
    if not current_user.is_authenticated:
        flash('Please log in to modify your wishlist.', 'warning')
        return redirect(url_for('login')) # Or adjust redirect as needed

    try:
        product_object_id = ObjectId(product_id)
    except Exception:
        flash('Invalid product ID.', 'danger')
        # Redirect back to profile wishlist or wherever appropriate
        return redirect(request.referrer or url_for('profile_wishlist'))

    try:
        # Remove the product ObjectId from the user's wishlist array
        result = mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$pull': {'wishlist': product_object_id}}
        )

        if result.modified_count > 0:
            flash('Item removed from your wishlist.', 'success')
        else:
            # This could happen if the item wasn't in the wishlist to begin with
            flash('Item not found in your wishlist or already removed.', 'info')

    except Exception as e:
        flash(f'An error occurred while removing the item: {e}', 'danger')
        # Log the error e for debugging if necessary

    # Redirect back to the page the user came from (e.g., profile wishlist or product page)
    return redirect(request.referrer or url_for('profile_wishlist'))



# ============= ADMIN ROUTES =============

@app.route("/admin")
@login_required
def admin_index():
    if not current_user.is_authenticated or not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('home'))
    return redirect(url_for('admin_dashboard'))


def log_admin_action(action_type, details, affected_ids=None):
    """Log admin actions for accountability"""
    try:
        log_entry = {
            "admin_id": current_user.id,
            "admin_name": current_user.name,
            "action_type": action_type,
            "details": details,
            "affected_ids": affected_ids or [],
            "timestamp": datetime.now()
        }
        
        # Create admin_logs collection if it doesn't exist
        if "admin_logs" not in mongo.db.list_collection_names():
            mongo.db.create_collection("admin_logs")
            
        mongo.db.admin_logs.insert_one(log_entry)
        return True
    except Exception as e:
        print(f"Error logging admin action: {e}")
        return False


@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    """Admin dashboard with overview statistics and recent activity"""
    # Calculate date ranges for statistics
    current_date = datetime.now()
    last_month_start = current_date - timedelta(days=30)
    previous_month_start = last_month_start - timedelta(days=30)
    
    # Get total orders and calculate growth
    total_orders = mongo.db.orders.count_documents({})
    current_month_orders = mongo.db.orders.count_documents({"created_at": {"$gte": last_month_start}})
    previous_month_orders = mongo.db.orders.count_documents({
        "created_at": {"$gte": previous_month_start, "$lt": last_month_start}
    })
    
    inventory_alerts = get_inventory_alerts()
    
    # Get popular products
    popular_products = get_popular_products()

    # Calculate order growth percentage
    order_growth = 0
    if previous_month_orders > 0:
        order_growth = round(((current_month_orders - previous_month_orders) / previous_month_orders) * 100)
    
    # Calculate total revenue and growth
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$total_price"}}}]
    revenue_result = list(mongo.db.orders.aggregate(pipeline))
    total_revenue = 0
    if revenue_result:
        total_revenue = round(revenue_result[0]["total"], 2)
    
    # Calculate revenue growth
    current_month_pipeline = [
        {"$match": {"created_at": {"$gte": last_month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$total_price"}}}
    ]
    previous_month_pipeline = [
        {"$match": {"created_at": {"$gte": previous_month_start, "$lt": last_month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$total_price"}}}
    ]
    
    current_month_revenue = list(mongo.db.orders.aggregate(current_month_pipeline))
    previous_month_revenue = list(mongo.db.orders.aggregate(previous_month_pipeline))
    
    current_month_total = current_month_revenue[0]["total"] if current_month_revenue else 0
    previous_month_total = previous_month_revenue[0]["total"] if previous_month_revenue else 0
    
    revenue_growth = 0
    if previous_month_total > 0:
        revenue_growth = round(((current_month_total - previous_month_total) / previous_month_total) * 100)
    
    # Get product stats
    total_products = mongo.db.products.count_documents({})
    new_products = mongo.db.products.count_documents({"created_at": {"$gte": last_month_start}})
    
    # Get user stats
    total_users = mongo.db.users.count_documents({"is_admin": False})
    new_users = mongo.db.users.count_documents({"is_admin": False, "created_at": {"$gte": last_month_start}})
    
    # Get recent appointments with customer names
    recent_appointments = list(mongo.db.appointments.find().sort("appointment_date", -1).limit(5))
    for appointment in recent_appointments:
        user = mongo.db.users.find_one({"_id": appointment.get("user_id")})
        if user:
            appointment["customer_name"] = user.get("name", "Unknown")
        else:
            appointment["customer_name"] = "Unknown"
        
        # Get service name
        service = mongo.db.services.find_one({"_id": appointment.get("service_id")})
        if service:
            appointment["service_name"] = service.get("name", "Unknown Service")
        else:
            appointment["service_name"] = "Unknown Service"
    
    recent_testimonials = safe_db_operation(
        lambda: list(mongo.db.testimonials.find().sort("created_at", -1).limit(5)),
        "Failed to retrieve recent testimonials",
        default_return=[]
    )

    # Get recent orders with customer names
    recent_orders = list(mongo.db.orders.find().sort("created_at", -1).limit(5))
    for order in recent_orders:
        user = mongo.db.users.find_one({"_id": order.get("user_id")})
        if user:
            order["customer_name"] = user.get("name", "Unknown")
        else:
            order["customer_name"] = "Unknown"
    
    # Get categories for product form
    categories = list(mongo.db.categories.find())
    
    # Prepare weekly sales data for chart
    weekly_sales = get_sales_chart_data()
    
    # Prepare product popularity data for chart
    product_popularity = get_products_chart_data()
    
    # Generate order dates and counts for the order statistics chart
    # Get the last 7 days
    last_7_days = [(current_date - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7, 0, -1)]
    
    # Get order counts for each day
    order_counts = []
    for day in last_7_days:
        day_start = datetime.strptime(day, '%Y-%m-%d')
        day_end = day_start + timedelta(days=1)
        count = mongo.db.orders.count_documents({
            "created_at": {"$gte": day_start, "$lt": day_end}
        })
        order_counts.append(count)
    
    # Format dates for display
    order_dates = [(datetime.strptime(date, '%Y-%m-%d')).strftime('%d %b') for date in last_7_days]
    
    # Get order status distribution for pie chart
    pending_orders = mongo.db.orders.count_documents({"status": "pending"})
    processing_orders = mongo.db.orders.count_documents({"status": "processing"})
    shipped_orders = mongo.db.orders.count_documents({"status": "shipped"})
    delivered_orders = mongo.db.orders.count_documents({"status": "delivered"})
    cancelled_orders = mongo.db.orders.count_documents({"status": "cancelled"})
    
    return render_template(
        "admin/dashboard.html",
        total_orders=total_orders,
        order_growth=order_growth,
        total_revenue=total_revenue,
        revenue_growth=revenue_growth,
        total_products=total_products,
        new_products=new_products,
        total_users=total_users,
        new_users=new_users,
        recent_appointments=recent_appointments,
        recent_testimonials=recent_testimonials,
        recent_orders=recent_orders,
        categories=categories,
        weekly_sales=weekly_sales,
        product_popularity=product_popularity,
        order_dates=order_dates,
        order_counts=order_counts,
        pending_orders=pending_orders,
        processing_orders=processing_orders,
        shipped_orders=shipped_orders,
        delivered_orders=delivered_orders,
        cancelled_orders=cancelled_orders,
        inventory_alerts=inventory_alerts,
        popular_products=popular_products
    )


@app.route('/admin/search', methods=['GET'])
@login_required
def admin_global_search():
    """Global search across products, orders, and customers"""
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('home'))
    
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 3:
        flash('Please enter at least 3 characters for search', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    results = {
        'products': [],
        'orders': [],
        'customers': [],
        'appointments': []
    }
    
    try:
        # Search in products
        product_results = list(mongo.db.products.find({
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"description": {"$regex": query, "$options": "i"}},
                {"category": {"$regex": query, "$options": "i"}}
            ]
        }).limit(10))
        results['products'] = product_results
        
        # Search in orders (by ID or status)
        order_results = list(mongo.db.orders.find({
            "$or": [
                {"status": {"$regex": query, "$options": "i"}},
                {"_id": {"$regex": query, "$options": "i"}} if ObjectId.is_valid(query) else {"_id": None}
            ]
        }).limit(10))
        results['orders'] = order_results
        
        # Search in customers
        customer_results = list(mongo.db.users.find({
            "is_admin": False,
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"email": {"$regex": query, "$options": "i"}}
            ]
        }).limit(10))
        results['customers'] = customer_results
        
        # Search in appointments
        appointment_results = list(mongo.db.appointments.find({
            "$or": [
                {"status": {"$regex": query, "$options": "i"}},
                {"notes": {"$regex": query, "$options": "i"}}
            ]
        }).limit(10))
        results['appointments'] = appointment_results
        
        # Log the search action
        log_admin_action(
            action_type="global_search",
            details=f"Global search for: '{query}'"
        )
        
        return render_template(
            'admin/search_results.html',
            query=query,
            results=results,
            product_count=len(results['products']),
            order_count=len(results['orders']),
            customer_count=len(results['customers']),
            appointment_count=len(results['appointments'])
        )
        
    except Exception as e:
        flash(f'Search error: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/export/<collection_name>', methods=['GET'])
@login_required
def admin_export_data(collection_name):

    """Export data as CSV"""
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('home'))
    
    # Define allowed collections and their fields
    allowed_collections = {
        'orders': ['_id', 'user_id', 'items', 'total_price', 'status', 'created_at'],
        'products': ['_id', 'name', 'description', 'price', 'category', 'stock', 'created_at'],
        'customers': ['_id', 'name', 'email', 'created_at']
    }
    
    if collection_name not in allowed_collections:
        flash('Invalid export request', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Get data from the specified collection
        data = list(mongo.db[collection_name].find())
        
        # Create CSV file in memory
        si = StringIO()
        writer = csv.writer(si)
        
        # Write headers
        headers = allowed_collections[collection_name]
        writer.writerow(headers)
        
        # Write data rows
        for item in data:
            row = []
            for field in headers:
                value = item.get(field, '')
                # Handle special cases
                if field == '_id':
                    value = str(value)
                elif field == 'created_at' and value:
                    value = value.strftime('%Y-%m-%d %H:%M:%S')
                elif field == 'items' and isinstance(value, list):
                    value = ', '.join([f"{i.get('name')}({i.get('quantity')})" for i in value])
                row.append(value)
            writer.writerow(row)
        
        # Create response with CSV file
        output = si.getvalue()
        
        # Log the admin action
        log_admin_action(
            action_type=f"export_{collection_name}",
            details=f"Exported {len(data)} {collection_name} records to CSV"
        )
        
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename={collection_name}_export.csv"}
        )
        
    except Exception as e:
        flash(f'Export error: {str(e)}', 'danger')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/products')
@login_required
@admin_required
def admin_products():
    """Admin products management page"""
    products = list(mongo.db.products.find().sort('name', 1))
    categories = list(mongo.db.categories.find())
    return render_template('admin/products.html', products=products, categories=categories)

@app.route('/admin/products/add', methods=['POST'])
@login_required
@admin_required
def admin_add_product():
    """Add a new product"""
    if request.method == 'POST':
        name = request.form.get('name')
        category = request.form.get('category')
        price = float(request.form.get('price', 0))
        stock = int(request.form.get('stock', 0))
        description = request.form.get('description')
        sku = request.form.get('SKU', '')
        tags = request.form.get('tags', '')
        full_description = request.form.get('full_description', '')
        original_price = request.form.get('original_price', 0)
        if original_price:
            original_price = float(original_price)

        print(f"Form data - Name: {name}, Category: {category}, Price: {price}, Description: {description}")
        try:
            price = float(price)
        except ValueError:
            flash('Price must be a valid number', 'danger')
            return redirect(url_for('admin_dashboard'))
            
        try:
            stock = int(stock)
        except ValueError:
            flash('Stock must be a valid number', 'danger')
            return redirect(url_for('admin_dashboard'))
            
        try:
            original_price = float(original_price) if original_price else 0
        except ValueError:
            flash('Original price must be a valid number', 'danger')
            return redirect(url_for('admin_dashboard'))


        if not sku:
            # Generate SKU
            prefix = ''.join(c for c in name if c.isalnum())[:3].upper()
            timestamp = int(time.time())
            sku = f"{prefix}{timestamp}"

        # Validate input
        if not name:
            flash('Product name is required', 'danger')
            return redirect(url_for('admin_dashboard'))
        if not category:
            flash('Category is required', 'danger')
            return redirect(url_for('admin_dashboard'))
        if price <= 0:
            flash('Price must be greater than 0', 'danger')
            return redirect(url_for('admin_dashboard'))
        if not description:
            flash('Description is required', 'danger')
            return redirect(url_for('admin_dashboard'))   
        
        # Validate input
        if not all([name, category, price > 0, description]):
            flash('All fields are required and price must be greater than 0', 'danger')
            return redirect(url_for('admin_dashboard'))
        
        # Handle image upload
        image = 'default-product.jpg'  # Default image
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                # Generate secure filename
                filename = secure_filename(file.filename)
                # Add timestamp to filename to avoid duplicates
                filename = f"{int(time.time())}_{filename}"
                # Save file
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image = filename
        
        # Handle gallery images upload
        gallery_images = []
        if 'gallery_images' in request.files:
            files = request.files.getlist('gallery_images')
            for file in files:
                if file and file.filename:
                    # Generate secure filename
                    filename = secure_filename(file.filename)
                    # Add timestamp to filename to avoid duplicates
                    timestamp = int(time.time())
                    filename = f"{timestamp}_{filename}"
                    # Save file
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    gallery_images.append(filename)
        
        # Process tags
        tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        # Create product
        product = {
            'name': name,
            'category': category,
            'price': price,
            'stock': stock,
            'description': description,
            'full_description': full_description,
            'original_price': original_price,
            'sku': sku,
            'image': image,
            'gallery_images': gallery_images,  # Add gallery images to the product
            'tags': tags_list,
            'created_at': datetime.now()
        }
        
        # Insert product
        mongo.db.products.insert_one(product)
        
        flash('Product added successfully', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return redirect(url_for('admin_dashboard'))
@app.route('/admin/products/<product_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_product(product_id):
    """Edit a product"""
    if request.method == 'POST':
        name = request.form.get('name')
        category = request.form.get('category')
        price = float(request.form.get('price', 0))
        stock = int(request.form.get('stock', 0))
        description = request.form.get('description')
        sku = request.form.get('sku', '')
        tags = request.form.get('tags', '')
        
        # Validate input
        if not all([name, category, price > 0, stock >= 0, description]):
            flash('All fields are required and price must be greater than 0', 'danger')
            return redirect(url_for('admin_products'))
        
        # Get current product
        product = mongo.db.products.find_one({'_id': ObjectId(product_id)})
        if not product:
            flash('Product not found', 'danger')
            return redirect(url_for('admin_products'))
        
        # Handle image upload
        image = product['image']  # Keep current image by default
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                # Generate secure filename
                filename = secure_filename(file.filename)
                # Add timestamp to filename to avoid duplicates
                filename = f"{int(time.time())}_{filename}"
                # Save file
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image = filename
        
        # Process tags
        tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
        
        # Update product
        mongo.db.products.update_one(
            {'_id': ObjectId(product_id)},
            {'$set': {
                'name': name,
                'category': category,
                'price': price,
                'stock': stock,
                'description': description,
                'sku': sku,
                'image': image,
                'tags': tags_list,
                'updated_at': datetime.now()
            }}
        )
        
        flash('Product updated successfully', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/categories')
@login_required
@admin_required
def admin_categories():
    """Admin categories management page"""
    categories = list(mongo.db.categories.find().sort('name', 1))
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/categories/add', methods=['POST'])
@login_required
@admin_required
def admin_add_category():
    """Add a new category"""
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            mongo.db.categories.insert_one({'name': name, 'created_at': datetime.now()})
            flash('Category added successfully', 'success')
        else:
            flash('Category name is required', 'danger')
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/<category_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_category(category_id):
    """Edit a category"""
    if request.method == 'POST':
        name = request.form.get('name')
        if name and validate_object_id(category_id):
            mongo.db.categories.update_one(
                {'_id': ObjectId(category_id)},
                {'$set': {'name': name, 'updated_at': datetime.now()}}
            )
            flash('Category updated successfully', 'success')
        else:
            flash('Invalid data or category ID', 'danger')
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/<category_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_category(category_id):
    """Delete a category"""
    if validate_object_id(category_id):
        # Optional: Check if any products use this category before deleting
        mongo.db.categories.delete_one({'_id': ObjectId(category_id)})
        flash('Category deleted successfully', 'success')
    else:
        flash('Invalid category ID', 'danger')
    return redirect(url_for('admin_categories'))

@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    """Admin orders management page"""
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Number of orders per page
    
    # Apply filters if provided
    filter_query = {}
    
    # Date range filter
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    if date_from:
        filter_query['created_at'] = {'$gte': datetime.strptime(date_from, '%Y-%m-%d')}
    if date_to:
        if 'created_at' in filter_query:
            filter_query['created_at']['$lte'] = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        else:
            filter_query['created_at'] = {'$lte': datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)}
    
    # Status filters
    payment_status = request.args.get('payment_status')
    if payment_status:
        filter_query['payment_status'] = payment_status
        
    order_status = request.args.get('order_status')
    if order_status:
        filter_query['status'] = order_status
    
    # Count total orders for pagination
    total_orders = mongo.db.orders.count_documents(filter_query)
    total_pages = (total_orders + per_page - 1) // per_page  # Ceiling division
    
    # Get orders for current page
    skip = (page - 1) * per_page
    orders = list(mongo.db.orders.find(filter_query).sort('created_at', -1).skip(skip).limit(per_page))
    
    # Fetch user names for orders
    for order in orders:
        user = mongo.db.users.find_one({"_id": order.get("user_id")})
        order['customer_name'] = user.get('name', 'N/A') if user else 'N/A'
    
    # Determine if there are previous/next pages
    has_prev = page > 1
    has_next = page < total_pages
    
    return render_template(
        'admin/orders.html', 
        orders=orders,
        page=page,
        total_pages=total_pages,
        has_prev=has_prev,
        has_next=has_next
    )

@app.route('/admin/orders/<order_id>')
@login_required
@admin_required
def admin_order_details(order_id):
    """View details of a specific order"""
    if not validate_object_id(order_id):
        flash('Invalid order ID.', 'danger')
        return redirect(url_for('admin_orders'))

    order = mongo.db.orders.find_one({'_id': ObjectId(order_id)})
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders'))

    user = mongo.db.users.find_one({"_id": order.get("user_id")})
    order['customer_name'] = user.get('name', 'N/A') if user else 'N/A'
    order['customer_email'] = user.get('email', 'N/A') if user else 'N/A'

    # Fetch product details for items in the order
    for item in order.get('items', []):
        product = mongo.db.products.find_one({"_id": item.get("product_id")})
        item['name'] = product.get('name', 'Product Not Found') if product else 'Product Not Found'

    return render_template('admin/order_details.html', order=order)


@app.route('/admin/orders/<order_id>/update_status', methods=['POST'])
@login_required
@admin_required
def admin_update_order_status(order_id):
    """Update the status of an order"""
    if not validate_object_id(order_id):
        flash('Invalid order ID.', 'danger')
        return redirect(url_for('admin_orders'))

    new_status = request.form.get('status')
    if not new_status:
        flash('Status is required.', 'danger')
        return redirect(url_for('admin_order_details', order_id=order_id))

    result = mongo.db.orders.update_one(
        {'_id': ObjectId(order_id)},
        {'$set': {'status': new_status, 'updated_at': datetime.now()}}
    )

    if result.modified_count > 0:
        flash('Order status updated successfully.', 'success')
        # Optional: Send email notification to customer about status update
    else:
        flash('Failed to update order status or status unchanged.', 'warning')

    return redirect(url_for('admin_order_details', order_id=order_id))

@app.route('/admin/orders/bulk-action', methods=['POST'])
@login_required
def admin_bulk_order_action():
    """Handle bulk actions for orders"""
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('home'))
    
    action = request.form.get('action')
    order_ids = request.form.getlist('order_ids[]')
    new_status = request.form.get('status')
    
    if not order_ids:
        flash('No orders selected', 'warning')
        return redirect(url_for('admin_orders'))
    
    # Convert string IDs to ObjectId
    object_ids = [ObjectId(id) for id in order_ids]
    
    try:
        if action == 'update_status' and new_status:
            # Update status for all selected orders
            result = mongo.db.orders.update_many(
                {"_id": {"$in": object_ids}},
                {"$set": {"status": new_status}}
            )
            flash(f'{result.modified_count} orders updated to {new_status}', 'success')
            
        elif action == 'delete':
            # Delete all selected orders
            result = mongo.db.orders.delete_many({"_id": {"$in": object_ids}})
            flash(f'{result.deleted_count} orders deleted', 'success')
        
        # Log the admin action
        log_admin_action(
            action_type=f"bulk_{action}_orders",
            details=f"Bulk {action} action on {len(order_ids)} orders" + (f" to status: {new_status}" if new_status else ""),
            affected_ids=order_ids
        )
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('admin_orders'))

@app.route('/admin/appointments')
@login_required
@admin_required
def admin_appointments():
    """Admin appointments management page"""
    appointments = list(mongo.db.appointments.find().sort('appointment_date', 1))
    # Fetch user and service names
    for appt in appointments:
        user = mongo.db.users.find_one({"_id": appt.get("user_id")})
        appt['customer_name'] = user.get('name', 'N/A') if user else 'N/A'
        service = mongo.db.services.find_one({"_id": appt.get("service_id")})
        appt['service_name'] = service.get('name', 'N/A') if service else 'N/A'
    return render_template('admin/appointments.html', appointments=appointments)

@app.route('/admin/appointments/calendar-data')
@login_required
@admin_required
def admin_appointments_calendar_data():
    # Fetch appointments from database
    appointments = list(mongo.db.appointments.find().sort('appointment_date', 1))
    
    # Format appointments for FullCalendar
    calendar_events = []
    for appointment in appointments:
        # Get user and service names
        user = mongo.db.users.find_one({"_id": appointment.get("user_id")})
        customer_name = user.get('name', 'N/A') if user else 'N/A'
        
        service = mongo.db.services.find_one({"_id": appointment.get("service_id")})
        service_name = service.get('name', 'N/A') if service else 'N/A'
        
        # Get appointment duration (default to 60 minutes if not specified)
        duration = appointment.get('duration', 60)
        
        # Create event object
        calendar_events.append({
            'id': str(appointment.get('_id')),
            'title': f"{service_name} - {customer_name}",
            'start': appointment.get('appointment_date').isoformat(),
            'end': (appointment.get('appointment_date') + timedelta(minutes=duration)).isoformat(),
            'url': url_for('admin_appointments'),  # You can create a detail view later
            'backgroundColor': get_status_color(appointment.get('status', 'pending'))
        })
    
    return jsonify(calendar_events)

@app.route("/admin/testimonials")
@admin_required
def admin_testimonials():
    """Admin testimonials management page"""
    testimonials = safe_db_operation(
        lambda: list(mongo.db.testimonials.find().sort("created_at", -1)),
        "Failed to retrieve testimonials",
        default_return=[]
    )
    
    return render_template("admin/testimonials.html", testimonials=testimonials)

# ... existing code ...

@app.route('/admin/testimonials/bulk-action', methods=['POST'])
@login_required
def admin_bulk_testimonial_action():
    """Handle bulk actions for testimonials"""
    if not current_user.is_admin:
        flash('Admin access required', 'danger')
        return redirect(url_for('home'))
    
    action = request.form.get('action')
    testimonial_ids = request.form.getlist('testimonial_ids[]')
    
    if not testimonial_ids:
        flash('No testimonials selected', 'warning')
        return redirect(url_for('admin_testimonials'))
    
    # Convert string IDs to ObjectId
    object_ids = [ObjectId(id) for id in testimonial_ids]
    
    try:
        if action == 'approve':
            # Approve all selected testimonials
            result = mongo.db.testimonials.update_many(
                {"_id": {"$in": object_ids}},
                {"$set": {"approved": True}}
            )
            flash(f'{result.modified_count} testimonials approved', 'success')
            
        elif action == 'delete':
            # Delete all selected testimonials
            result = mongo.db.testimonials.delete_many({"_id": {"$in": object_ids}})
            flash(f'{result.deleted_count} testimonials deleted', 'success')
            
        # Log the admin action
        log_admin_action(
            action_type=f"bulk_{action}_testimonials",
            details=f"Bulk {action} action on {len(testimonial_ids)} testimonials",
            affected_ids=testimonial_ids
        )
            
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('admin_testimonials'))

# ... existing code ...

@app.route("/admin/testimonials/approve/<testimonial_id>")
@admin_required
def admin_approve_testimonial(testimonial_id):
    """Approve a testimonial"""
    if not validate_object_id(testimonial_id):
        flash("Invalid testimonial ID.", "danger")
        return redirect(url_for("admin_testimonials"))
    
    result = safe_db_operation(
        lambda: mongo.db.testimonials.update_one(
            {"_id": ObjectId(testimonial_id)},
            {"$set": {"approved": True}}
        ),
        "Failed to approve testimonial",
        default_return=None
    )
    
    if result and result.modified_count > 0:
        flash("Testimonial approved successfully.", "success")
    else:
        flash("Failed to approve testimonial.", "danger")
    
    return redirect(url_for("admin_testimonials"))

@app.route("/admin/testimonials/delete/<testimonial_id>")
@admin_required
def admin_delete_testimonial(testimonial_id):
    """Delete a testimonial"""
    if not validate_object_id(testimonial_id):
        flash("Invalid testimonial ID.", "danger")
        return redirect(url_for("admin_testimonials"))
    
    result = safe_db_operation(
        lambda: mongo.db.testimonials.delete_one({"_id": ObjectId(testimonial_id)}),
        "Failed to delete testimonial",
        default_return=None
    )
    
    if result and result.deleted_count > 0:
        flash("Testimonial deleted successfully.", "success")
    else:
        flash("Failed to delete testimonial.", "danger")
    
    return redirect(url_for("admin_testimonials"))

def get_status_color(status):
    """Return color based on appointment status"""
    status_colors = {
        'confirmed': '#28a745',  # green
        'pending': '#ffc107',    # yellow
        'cancelled': '#dc3545',  # red
        'completed': '#17a2b8'   # blue
    }
    return status_colors.get(status, '#6c757d')

@app.route('/admin/appointments/<appointment_id>', methods=['GET'])
@admin_required
def admin_appointment_details(appointment_id):
    """
    Display detailed information about a specific appointment
    """
    # Get the appointment from the database
    appointment = mongo.db.appointments.find_one({"_id": ObjectId(appointment_id)})
    
    if not appointment:
        flash('Appointment not found', 'danger')
        return redirect(url_for('admin_appointments'))
    
    # Get the user who made the appointment
    user = mongo.db.users.find_one({"_id": appointment.get("user_id")})    
    # Get the service details
    service = mongo.db.services.find_one({"_id": appointment.get("service_id")})

    return render_template('admin/appointment_details.html', 
                          appointment=appointment, 
                          user=user, 
                          service=service)

@app.route('/admin/appointments/<appointment_id>/update_status', methods=['POST'])
@login_required
@admin_required
def admin_update_appointment_status(appointment_id):
    """Update the status of an appointment"""
    if not validate_object_id(appointment_id):
        flash('Invalid appointment ID.', 'danger')
        return redirect(url_for('admin_appointments'))

    new_status = request.form.get('status')
    if not new_status:
        flash('Status is required.', 'danger')
        # Redirect back to the specific appointment details page if it exists, otherwise to the list
        # return redirect(url_for('admin_appointment_details', appointment_id=appointment_id))
        return redirect(url_for('admin_appointments'))


    result = mongo.db.appointments.update_one(
        {'_id': ObjectId(appointment_id)},
        {'$set': {'status': new_status, 'updated_at': datetime.now()}}
    )

    if result.modified_count > 0:
        flash('Appointment status updated successfully.', 'success')
        # Optional: Send email notification to customer
    else:
        flash('Failed to update appointment status or status unchanged.', 'warning')

    return redirect(url_for('admin_appointments'))

@app.route('/admin/appointments/<appointment_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_appointment(appointment_id):
    """Delete an appointment"""
    if validate_object_id(appointment_id):
        result = mongo.db.appointments.delete_one({'_id': ObjectId(appointment_id)})
        if result.deleted_count > 0:
            flash('Appointment deleted successfully.', 'success')
        else:
            flash('Appointment not found.', 'danger')
    else:
        flash('Invalid appointment ID.', 'danger')
    return redirect(url_for('admin_appointments'))


@app.route('/admin/services')
@login_required
@admin_required
def admin_services():
    """Admin services management page"""
    services = list(mongo.db.services.find().sort('name', 1))
    return render_template('admin/services.html', services=services)

@app.route('/admin/services/add', methods=['POST'])
@login_required
@admin_required
def admin_add_service():
    """Add a new service"""
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        duration = request.form.get('duration')
        category = request.form.get('category')
        description = request.form.get('description', '') # Optional description

        try:
            price = float(price)
            duration = int(duration)
            if name and price > 0 and duration > 0 and category:
                mongo.db.services.insert_one({
                    'name': name,
                    'price': price,
                    'duration': duration, # Duration in minutes
                    'category': category,
                    'description': description,
                    'created_at': datetime.now()
                })
                flash('Service added successfully', 'success')
            else:
                flash('Invalid service data. Name, positive price, positive duration, and category are required.', 'danger')
        except (ValueError, TypeError):
            flash('Invalid price or duration format.', 'danger')

    return redirect(url_for('admin_services'))


@app.route('/admin/services/<service_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_service(service_id):
    """Edit a service"""
    if request.method == 'POST' and validate_object_id(service_id):
        name = request.form.get('name')
        price = request.form.get('price')
        duration = request.form.get('duration')
        category = request.form.get('category')
        description = request.form.get('description', '')

        try:
            price = float(price)
            duration = int(duration)
            if name and price > 0 and duration > 0 and category:
                mongo.db.services.update_one(
                    {'_id': ObjectId(service_id)},
                    {'$set': {
                        'name': name,
                        'price': price,
                        'duration': duration,
                        'category': category,
                        'description': description,
                        'updated_at': datetime.now()
                    }}
                )
                flash('Service updated successfully', 'success')
            else:
                flash('Invalid service data. Name, positive price, positive duration, and category are required.', 'danger')
        except (ValueError, TypeError):
            flash('Invalid price or duration format.', 'danger')
    elif not validate_object_id(service_id):
        flash('Invalid service ID.', 'danger')

    return redirect(url_for('admin_services'))


@app.route('/admin/services/<service_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_service(service_id):
    """Delete a service"""
    if validate_object_id(service_id):
        # Optional: Check if service is used in appointments before deleting
        result = mongo.db.services.delete_one({'_id': ObjectId(service_id)})
        if result.deleted_count > 0:
            flash('Service deleted successfully', 'success')
        else:
            flash('Service not found.', 'danger')
    else:
        flash('Invalid service ID.', 'danger')
    return redirect(url_for('admin_services'))

@app.route('/admin/products/<product_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_product(product_id):
    """Delete a product"""
    # Check if product exists
    product = mongo.db.products.find_one({'_id': ObjectId(product_id)})
    
    if not product:
        flash('Product not found', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    # Delete product
    mongo.db.products.delete_one({'_id': ObjectId(product_id)})
    
    flash('Product deleted successfully', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    """Admin users management page"""
    # Get search and sort parameters
    search = request.args.get('search', '')
    sort_by = request.args.get('sort', 'name')
    order = request.args.get('order', 'asc')
    
    # Build the query
    query = {'is_admin': {'$ne': True}}
    if search:
        search = sanitize_input(search)
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'email': {'$regex': search, '$options': 'i'}},
            {'phone': {'$regex': search, '$options': 'i'}}
        ]
    
    # Determine sort direction
    sort_direction = 1 if order == 'asc' else -1
    
    # Get users with sorting
    users = list(mongo.db.users.find(query).sort(sort_by, sort_direction))
    
    return render_template('admin/customers.html', users=users)

def get_inventory_alerts():
    """Get inventory alerts for low stock products"""
    try:
        # Get products with low stock (less than 5 items)
        low_stock_products = list(mongo.db.products.find({"stock": {"$lt": 5}}).sort("stock", 1))
        
        # Get products that need restocking (out of stock)
        out_of_stock = list(mongo.db.products.find({"stock": 0}))
        
        return {
            "low_stock": low_stock_products,
            "out_of_stock": len(out_of_stock),
            "low_stock_count": len(low_stock_products)
        }
    except Exception as e:
        print(f"Error getting inventory alerts: {e}")
        return {"low_stock": [], "out_of_stock": 0, "low_stock_count": 0}

def get_popular_products(limit=5):
    """Get most popular products based on order frequency"""
    try:
        pipeline = [
            {"$unwind": "$items"},
            {"$group": {"_id": "$items.product_id", "count": {"$sum": "$items.quantity"}}},
            {"$sort": {"count": -1}},
            {"$limit": limit}
        ]
        
        popular_product_ids = list(mongo.db.orders.aggregate(pipeline))
        
        # Get product details
        popular_products = []
        for item in popular_product_ids:
            product = mongo.db.products.find_one({"_id": item["_id"]})
            if product:
                product["order_count"] = item["count"]
                popular_products.append(product)
        
        return popular_products
    except Exception as e:
        print(f"Error getting popular products: {e}")
        return []


@app.route('/admin/users/export', methods=['POST'])
@login_required
@admin_required
def admin_users_export():
    """Export users data"""
    # Implementation would depend on your export requirements
    # This is a placeholder
    flash('Export functionality not yet implemented.', 'info')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<user_id>')
@login_required
@admin_required
def admin_user_details(user_id):
    """View details of a specific user"""
    if not validate_object_id(user_id):
        flash('Invalid user ID.', 'danger')
        return redirect(url_for('admin_users'))

    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))

    # Fetch user's orders and appointments (optional, could be heavy)
    user_orders = list(mongo.db.orders.find({'user_id': ObjectId(user_id)}).sort('created_at', -1).limit(10))
    user_appointments = list(mongo.db.appointments.find({'user_id': ObjectId(user_id)}).sort('appointment_date', -1).limit(10))

    return render_template('admin/user_details.html', user=user, orders=user_orders, appointments=user_appointments)

@app.route('/admin/users/<user_id>/toggle_admin', methods=['POST'])
@login_required
@admin_required
def admin_toggle_admin_status(user_id):
    """Toggle admin status for a user"""
    if not validate_object_id(user_id):
        flash('Invalid user ID.', 'danger')
        return redirect(url_for('admin_users'))

    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))

    # Prevent current admin from removing their own admin status via this route
    if str(user['_id']) == current_user.id:
         flash('You cannot change your own admin status here.', 'warning')
         return redirect(url_for('admin_users'))

    new_status = not user.get('is_admin', False)
    mongo.db.users.update_one(
        {'_id': ObjectId(user_id)},
        {'$set': {'is_admin': new_status}}
    )
    flash(f"User '{user.get('name')}' admin status set to {new_status}.", 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_user_delete(user_id):
    """Delete a user"""
    if not validate_object_id(user_id):
        flash('Invalid user ID.', 'danger')
        return redirect(url_for('admin_users'))
    
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))
    
    # Prevent deleting admin users through this route
    if user.get('is_admin', False):
        flash('Cannot delete admin users through this route.', 'danger')
        return redirect(url_for('admin_users'))
    
    # Delete the user
    mongo.db.users.delete_one({'_id': ObjectId(user_id)})
    flash(f"User '{user.get('name')}' has been deleted.", 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/sales')
@login_required
@admin_required
def admin_sales():
    """Admin sales reports page"""
    # Example: Fetch total sales, sales by period, etc.
    # This requires more complex aggregation queries based on date ranges
    total_revenue_pipeline = [{"$group": {"_id": None, "total": {"$sum": "$total_price"}}}]
    revenue_result = list(mongo.db.orders.aggregate(total_revenue_pipeline))
    total_revenue = revenue_result[0]['total'] if revenue_result else 0

    # You would typically add date filters and more complex aggregations here
    # For now, just pass total revenue
    return render_template('admin/sales.html', total_revenue=total_revenue)

@app.route('/admin/inventory')
@login_required
@admin_required
def admin_inventory():
    """Admin inventory report page"""
    # Fetch products with low stock (e.g., stock < 5)
    low_stock_threshold = 5
    low_stock_products = list(mongo.db.products.find({'stock': {'$lt': low_stock_threshold}}).sort('stock', 1))
    all_products = list(mongo.db.products.find().sort('name', 1)) # For a full inventory list

    return render_template('admin/inventory.html', low_stock_products=low_stock_products, all_products=all_products, low_stock_threshold=low_stock_threshold)

# ============= MAIN ROUTES =============

@app.route("/reorder/<order_id>")
@login_required
def reorder(order_id):
    """Add all items from a previous order to the cart"""
    # Validate order_id
    if not validate_object_id(order_id):
        flash("Invalid order ID.", "danger")
        return redirect(url_for("profile_orders"))
    
    # Find the order and verify it belongs to the current user
    order = safe_db_operation(
        lambda: mongo.db.orders.find_one({
            "_id": ObjectId(order_id),
            "user_id": ObjectId(current_user.id)
        }),
        "Error retrieving order details",
        default_return=None
    )
    
    if not order:
        flash("Order not found or you don't have permission to access it.", "danger")
        return redirect(url_for("profile_orders"))
    
    # Initialize cart if it doesn't exist
    if "cart" not in session:
        session["cart"] = []
    
    # Track which items were successfully added and which were not
    added_items = []
    unavailable_items = []
    
    # Add each item from the order to the cart
    for item in order.get("items", []):
        # Check if product still exists and is in stock
        product = safe_db_operation(
            lambda: mongo.db.products.find_one({"_id": item["product_id"]}),
            "Error checking product availability",
            default_return=None
        )
        
        if not product:
            unavailable_items.append(item.get("name", "Unknown product"))
            continue
        
        # Check if product is in stock (if your system tracks inventory)
        if product.get("stock", 0) < item.get("quantity", 1):
            unavailable_items.append(product.get("name", "Unknown product"))
            continue
        
        # Add to cart
        cart_item = {
            "product_id": str(item["product_id"]),
            "name": product.get("name", "Unknown product"),
            "price": product.get("price", 0),
            "quantity": item.get("quantity", 1),
            "image": product.get("image", "default.jpg")
        }
        
        # Check if item already exists in cart
        existing_item = next((i for i in session["cart"] if i["product_id"] == cart_item["product_id"]), None)
        if existing_item:
            # Update quantity if item already in cart
            existing_item["quantity"] += cart_item["quantity"]
        else:
            # Add new item to cart
            session["cart"].append(cart_item)
        
        added_items.append(product.get("name", "Unknown product"))
    
    # Save cart to session
    session.modified = True
    
    # Provide feedback to user
    if added_items:
        if unavailable_items:
            flash(f"Added {len(added_items)} items to your cart. {len(unavailable_items)} items were unavailable: {', '.join(unavailable_items)}", "warning")
        else:
            flash(f"Successfully added all {len(added_items)} items from your previous order to cart!", "success")
    else:
        flash("Could not add any items from your previous order. They may no longer be available.", "danger")
    
    # Redirect to cart page
    return redirect(url_for("cart"))

@app.route('/get-locations')
def get_locations():
    """Endpoint to dynamically load location options based on type for HTMX."""
    location_type = request.args.get('location_type', 'salon') # Default to salon if not provided

    # Fetch counties from database instead of using hardcoded AVAILABLE_LOCATIONS
    counties = safe_db_operation(
        lambda: mongo.db.locations.distinct("county"),
        "Failed to load counties",
        default_return=[]
    )
    
    # Prepare county choices from database data
    county_choices = [('', 'Select County')] + [(county, county) for county in counties]

    # Prepare location choices (initially empty, populated by JS/HTMX based on county)
    location_choices = [('', 'Select Location/Sub-county')]

    # Render a partial HTML snippet for the location details section
    # We use render_template_string to avoid creating a new template file
    from flask import render_template_string

    template_string = """
        {% if location_type == 'home' %}
            <div class="mb-3">
                <label for="county" class="form-label">County</label>
                <select id="county" name="county" class="form-select" hx-get="{{ url_for('get_sub_locations') }}" hx-target="#location" hx-swap="innerHTML">
                    {% for value, label in county_choices %}
                        <option value="{{ value }}">{{ label }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="mb-3">
                <label for="location" class="form-label">Location/Sub-county</label>
                <select id="location" name="location" class="form-select">
                    {% for value, label in location_choices %}
                        <option value="{{ value }}">{{ label }}</option>
                    {% endfor %}
                </select>
                <small class="form-text text-muted">Select county first.</small>
            </div>
            <div class="mb-3">
                <label for="address" class="form-label">Full Address</label>
                <textarea id="address" name="address" class="form-control" rows="3" placeholder="Enter your street, building, house number etc."></textarea>
            </div>
        {% else %}
            <!-- Salon visit doesn't require specific location fields here -->
            <p>Please visit us at our salon location.</p> {# Or provide salon address details #}
        {% endif %}
    """
    return render_template_string(template_string,
                                location_type=location_type,
                                county_choices=county_choices,
                                location_choices=location_choices,
                                url_for=url_for) # Pass url_for to the template context # Pass url_for to the template context

@app.route('/get-sub-locations')
def get_sub_locations():
    """Endpoint to dynamically load sub-location options based on county."""
    county = request.args.get('county', '')
    
    if not county:
        return '<option value="">Select Location/Sub-county</option>'
    
    # Fetch locations for the selected county from database
    locations = safe_db_operation(
        lambda: list(mongo.db.locations.find(
            {"county": county},
            {"location": 1, "available_for_home_service": 1, "home_service_fee": 1}
        )),
        "Failed to fetch locations",
        default_return=[]
    )
    
    # Build options HTML
    options_html = '<option value="">Select Location/Sub-county</option>'
    
    for loc in locations:
        if loc.get("location"):
            location_name = loc.get("location")
            available = loc.get("available_for_home_service", False)
            
            # Add a visual indicator for locations where home service is available
            indicator = " ✓" if available else ""
            options_html += f'<option value="{location_name}" data-available="{str(available).lower()}">{location_name}{indicator}</option>'
    
    return options_html

# ... existing code ...

@app.route('/api/availability')
def get_availability():
    """API endpoint to get unavailable time slots for a specific date."""
    date_str = request.args.get('date')
    
    if not date_str:
        return jsonify({"error": "Date parameter is required"}), 400
    
    try:
        # Parse the date string to a datetime object
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Find all appointments for the selected date
        appointments = safe_db_operation(
            lambda: list(mongo.db.appointments.find(
                {"appointment_date": {"$regex": f"^{date_str}"}},
                {"appointment_time": 1, "service_id": 1}
            )),
            "Failed to fetch appointments",
            default_return=[]
        )
        
        # Extract unavailable time slots
        unavailable_slots = []
        for appointment in appointments:
            time_slot = appointment.get("appointment_time")
            if time_slot:
                unavailable_slots.append(time_slot)
        
        return jsonify({
            "date": date_str,
            "unavailable_slots": unavailable_slots
        })
    
    except Exception as e:
        print(f"Error fetching availability: {e}")
        return jsonify({"error": "Failed to fetch availability"}), 500

@app.route('/api/locations')
def get_locations_api():
    """API endpoint to get locations for a specific county."""
    county = request.args.get('county', '')
    
    if not county:
        return jsonify({"error": "County parameter is required"}), 400
    
    # Fetch locations for the selected county from database
    locations = safe_db_operation(
        lambda: list(mongo.db.locations.find(
            {"county": county},
            {"location": 1, "available_for_home_service": 1, "home_service_fee": 1, "_id": 0}
        )),
        "Failed to fetch locations",
        default_return=[]
    )
    
    # Format the response
    formatted_locations = []
    for loc in locations:
        if loc.get("location"):
            formatted_locations.append({
                "name": loc.get("location"),
                "available_for_home_service": loc.get("available_for_home_service", False),
                "home_service_fee": loc.get("home_service_fee", 0)
            })
    
    return jsonify({"locations": formatted_locations})



@app.template_filter('format_currency')
def format_currency(value):
    """Format a value as KSh currency."""
    if value is None:
        return "KSh 0.00" # Or handle None as you see fit
    try:
        # Format with commas for thousands and two decimal places
        return f"KSh {value:,.2f}"
    except (ValueError, TypeError):
        return str(value)

@app.route("/")
def home():
    """Home page"""
    # Get featured services (limit to 4)
    try:
        services = list(mongo.db.services.find().limit(4))
        print(f"Retrieved {len(services)} services from database")
    except Exception as e:
        print(f"Error retrieving services: {e}")
        services = []
    
    # Get featured products (limit to 4)
    try:
        featured_products = list(mongo.db.products.find().limit(4))
    except Exception as e:
        print(f"Error retrieving products: {e}")
        featured_products = []
    
    # Get testimonials
    try:
        testimonials = list(mongo.db.testimonials.find().limit(3))
    except Exception as e:
        print(f"Error retrieving testimonials: {e}")
        testimonials = []
    
    return render_template("index.html", 
                          services=services, 
                          featured_products=featured_products, 
                          testimonials=testimonials)

@app.route("/privacy")
def privacy():
    """Display privacy policy page"""
    return render_template("privacy.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user_data = mongo.db.users.find_one({"email": email})
        
        if user_data and check_password_hash(user_data["password"], password):
            user = User(user_data)
            login_user(user)
            
            next_page = request.args.get("next")
            if next_page:
                return redirect(next_page)
            
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("home"))
        
        flash("Invalid email or password", "danger")
    
    return render_template("auth/login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Handle password reset requests"""
    if request.method == "POST":
        email = request.form.get("email")
        
        # Check if email exists
        user = mongo.db.users.find_one({"email": email})
        if user:
            # Generate a reset token (in a real app, you'd use a secure token)
            reset_token = generate_password_hash(email + str(datetime.now()))[:20]
            
            # Store the token in the database with an expiration time
            mongo.db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {
                    "reset_token": reset_token,
                    "reset_token_expires": datetime.now() + timedelta(hours=1)
                }}
            )
            
            # Create reset link
            reset_link = url_for('reset_password', token=reset_token, _external=True)
            
            # Send password reset email (placeholder)
            html_body = render_template('emails/password_reset.html', 
                                    user=user, 
                                    reset_link=reset_link,
                                    current_year=datetime.now().year)
            send_email(subject='Password Reset Request',
                    recipients=[email],
                    text_body=f"Reset your password: {reset_link}",
                    html_body=html_body)
            
            flash("Password reset instructions sent to your email", "info")
            return redirect(url_for("login"))
        else:
            # Don't reveal if email exists for security
            flash("If your email is registered, you will receive reset instructions", "info")
            return redirect(url_for("login"))
    
    return render_template("auth/forgot_password.html")

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Reset password using token"""
    # Find user with this token
    user = mongo.db.users.find_one({
        "reset_token": token,
        "reset_token_expires": {"$gt": datetime.now()}
    })
    
    if not user:
        flash("Invalid or expired reset token", "danger")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not password or password != confirm_password:
            flash("Passwords don't match", "danger")
            return render_template("auth/reset_password.html", token=token)
        
        # Update password and remove token
        hashed_password = generate_password_hash(password)
        mongo.db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {"password": hashed_password},
                "$unset": {"reset_token": "", "reset_token_expires": ""}
            }
        )
        
        flash("Password has been reset successfully. Please log in.", "success")
        return redirect(url_for("login"))
    
    return render_template("auth/reset_password.html", token=token)

@app.route("/about")
def about():
    """About page"""
    return render_template("about.html")

@app.route("/faqs")
def faqs():
    """FAQs page"""
    return render_template("faqs.html")
# Add the missing contact route
@app.route("/contact")
def contact():
    """Contact page"""
    return render_template("contact.html")

@app.route("/terms")
def terms():
    """Terms of Service page"""
    return render_template("terms.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone", "")  # Added phone field, optional
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        # Validate input
        print(request.form)
        if not all([name, email, password, confirm_password]):
            flash("All required fields must be filled", "danger")
            return render_template("auth/register.html")
        
        # Check if passwords match
        if password != confirm_password:
            flash("Passwords don't match", "danger")
            return render_template("auth/register.html")
        
        # Check if email already exists
        if mongo.db.users.find_one({"email": email}):
            flash("Email already registered", "danger")
            return render_template("auth/register.html")
        
        # Create user
        hashed_password = generate_password_hash(password)
        user = {
            "name": name,
            "email": email,
            "phone": phone,
            "password": hashed_password,
            "is_admin": False,
            "created_at": datetime.now()
        }
        
        # Insert user
        result = mongo.db.users.insert_one(user)
        
        # Log in the user
        user["_id"] = result.inserted_id
        login_user(User(user))
        
        flash("Registration successful!", "success")
        return redirect(url_for("home"))
    
    return render_template("auth/register.html")

# --- User Profile Routes ---

@app.route("/profile")
@login_required
def profile():
    """Display user profile page."""
    # Fetch user's orders and appointments
    orders = list(mongo.db.orders.find({"user_id": ObjectId(current_user.id)}).sort("created_at", -1))
    appointments = list(mongo.db.appointments.find({"user_id": ObjectId(current_user.id)}).sort("appointment_date", -1))

    # Format dates for display
    for order in orders:
        order['created_at_formatted'] = order['created_at'].strftime('%d %b %Y, %H:%M')
    for appt in appointments:
        appt['appointment_date_formatted'] = appt['appointment_date'].strftime('%d %b %Y')

    return render_template(
        "user/profile.html",
        user=current_user, # Pass the current_user object directly
        orders=orders,
        appointments=appointments,
        active_tab='account'  # Set the active tab to 'account'
    )

@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    """Edit user profile"""
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone", "")
        
        # Validate input
        if not all([name, email]):
            flash("Name and email are required", "danger")
            return redirect(url_for("edit_profile"))
        
        # Check if email is already taken by another user
        existing_user = mongo.db.users.find_one({"email": email, "_id": {"$ne": ObjectId(current_user.id)}})
        if existing_user:
            flash("Email already in use by another account", "danger")
            return redirect(url_for("edit_profile"))
        
        # Update user
        mongo.db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {
                "name": name,
                "email": email,
                "phone": phone,
                "updated_at": datetime.now()
            }}
        )
        
        # Update current_user
        current_user.user_data["name"] = name
        current_user.user_data["email"] = email
        current_user.user_data["phone"] = phone
        
        flash("Profile updated successfully", "success")
        return redirect(url_for("profile"))
    
    return render_template("user/edit_profile.html", user=current_user.user_data)

@app.route("/profile/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change user password"""
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        # Validate input
        if not all([current_password, new_password, confirm_password]):
            flash("All fields are required", "danger")
            return redirect(url_for("change_password"))
        
        # Check if current password is correct
        user = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
        if not check_password_hash(user["password"], current_password):
            flash("Current password is incorrect", "danger")
            return redirect(url_for("change_password"))
        
        # Check if new passwords match
        if new_password != confirm_password:
            flash("New passwords don't match", "danger")
            return redirect(url_for("change_password"))
        
        # Update password
        hashed_password = generate_password_hash(new_password)
        mongo.db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {"password": hashed_password}}
        )
        
        flash("Password changed successfully", "success")
        return redirect(url_for("profile"))
    
    return render_template("auth/reset_password.html")

@app.route("/profile/update-address", methods=["POST"])
@login_required
def update_address():
    """Update user address"""
    if request.method == "POST":
        address_line1 = request.form.get("address_line1", "")
        address_line2 = request.form.get("address_line2", "")
        city = request.form.get("city", "")
        county = request.form.get("county", "")
        postal_code = request.form.get("postal_code", "")
        
        # Create address object
        address = {
            "line1": address_line1,
            "line2": address_line2,
            "city": city,
            "county": county,
            "postal_code": postal_code,
            "updated_at": datetime.now()
        }
        
        # Update user
        mongo.db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {"address": address}}
        )
        
        flash("Address updated successfully", "success")
        return redirect(url_for("profile"))
    
    return redirect(url_for("profile"))
    
    
# ============= STORE ROUTES =============
@app.route("/shop")
def shop():
    """Shop page with products"""
    # Get query parameters
    category = request.args.get("category")
    tag = request.args.get('tag')
    search = request.args.get("search")
    sort = request.args.get("sort", "name_asc")
    page = int(request.args.get("page", 1))
    per_page = 12
    
    # Build query
    query = {}
    if category:
        query["category"] = category
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
            {"tags": {"$in": [search]}}
        ]
    
    # Get total products count
    total_products = mongo.db.products.count_documents(query)
    
    # Calculate pagination
    total_pages = (total_products + per_page - 1) // per_page
    skip = (page - 1) * per_page
    
    # Sort products
    sort_options = {
        "name_asc": ("name", 1),
        "name_desc": ("name", -1),
        "price_asc": ("price", 1),
        "price_desc": ("price", -1),
        "newest": ("created_at", -1)
    }
    sort_field, sort_order = sort_options.get(sort, ("name", 1))
    
    # Get products
    products = list(mongo.db.products.find(query).sort(sort_field, sort_order).skip(skip).limit(per_page))
    
    # Get categories for filter
    categories = list(mongo.db.categories.find())
    
    return render_template("store.html", 
                          products=products, 
                          categories=categories,
                          current_category=category,
                          current_search=search,
                          current_sort=sort,
                          page=page,
                          total_pages=total_pages,
                          total_products=total_products,
                          design_system={
                              "colors": {
                                  "primary": "hsl(340 73% 73%)",
                                  "secondary": "hsl(20 60% 95%)",
                                  "background": "hsl(350 100% 98%)"
                              }
                          })

@app.route("/product/<product_id>")
def product_detail(product_id):
    """Product detail page"""
    # Validate product_id
    if not validate_object_id(product_id):
        flash("Invalid product ID", "danger")
        return redirect(url_for("shop"))
    
    # Get product
    product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        flash("Product not found", "danger")
        return redirect(url_for("shop"))

    if 'rating' not in product:
        product['rating'] = 0
    if 'reviews' not in product:
        product['reviews'] = []
    
    
    # Get related products (same category, excluding current product)
    related_products = list(mongo.db.products.find({
        "category": product["category"],
        "_id": {"$ne": ObjectId(product_id)}
    }).limit(4))
    
    return render_template("store/product_detail.html", product=product, related_products=related_products)

@app.route('/product/review/<product_id>', methods=['POST'])
@login_required
def add_review(product_id):
    if not validate_object_id(product_id):
        flash("Invalid product ID", "danger")
        return redirect(url_for('shop'))
    
    # Get form data
    rating = request.form.get('rating')
    comment = request.form.get('comment')
    
    # Validate input
    if not rating or not comment:
        flash("Rating and comment are required", "danger")
        return redirect(url_for('product_detail', product_id=product_id))
    
    try:
        # Create review object
        review = {
            "user_id": current_user.id,
            "user_name": current_user.name,
            "rating": int(rating),
            "comment": sanitize_input(comment),
            "date": datetime.now()
        }
        
        # Update product with new review
        result = mongo.db.products.update_one(
            {"_id": ObjectId(product_id)},
            {"$push": {"reviews": review}}
        )
        
        if result.modified_count > 0:
            # Update product rating
            product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
            reviews = product.get('reviews', [])
            if reviews:
                avg_rating = sum(review['rating'] for review in reviews) / len(reviews)
                mongo.db.products.update_one(
                    {"_id": ObjectId(product_id)},
                    {"$set": {"rating": round(avg_rating, 1)}}
                )
            
            flash("Your review has been added successfully", "success")
        else:
            flash("Failed to add review", "danger")
            
    except Exception as e:
        print(f"Error adding review: {e}")
        flash("An error occurred while adding your review", "danger")
    
    return redirect(url_for('product_detail', product_id=product_id))

@app.route("/check-stock")
def check_stock():
    """API endpoint to check product stock availability"""
    product_id = request.args.get("product_id")
    quantity = int(request.args.get("quantity", 1))
    
    # Validate product_id
    if not validate_object_id(product_id):
        return jsonify({"available": False, "message": "Invalid product ID"})
    
    # Get product
    product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        return jsonify({"available": False, "message": "Product not found"})
    
    # Check stock
    if product["stock"] <= 0:
        return jsonify({"available": False, "message": "Product is out of stock"})
    
    if product["stock"] < quantity:
        return jsonify({
            "available": False, 
            "message": f"Only {product['stock']} items available",
            "available_stock": product["stock"]
        })
    
    return jsonify({"available": True, "stock": product["stock"]})


@app.route("/cart")
def cart():
    """Shopping cart page"""
    # Get cart from session
    cart_items = session.get("cart", [])
    
    # Get product details for cart items
    products = []
    total = 0
    
    for item in cart_items:
        if not validate_object_id(item.get("product_id")):
            print(f"Warning: Invalid product_id format found in session cart: {item.get('product_id')}")
            continue

        product = mongo.db.products.find_one({"_id": ObjectId(item["product_id"])})

        if product:
            quantity = item["quantity"]
            price = product["price"]
            subtotal = price * quantity
            
            products.append({
                "id": str(product["_id"]),
                "name": product["name"],
                "price": price,
                "image": product["image"],
                "quantity": quantity,
                "subtotal": subtotal
            })
            
            total += subtotal
    
    # Get delivery location from session if available
    county = None
    location = None

    if current_user.is_authenticated:
        user_data = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
        if user_data:
            county = user_data.get("county")
            location = user_data.get("city")

    if not county:
        county = session.get("delivery_county")
        location = session.get("delivery_location")
    
    # Check if eligible for free delivery based on location
    shipping = calculate_delivery_fee(county, location, total)
    
    return render_template("store/cart.html", products=products, total=total, shipping=shipping)


@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    product_id = request.form.get("product_id")
    quantity = int(request.form.get("quantity", 1))
    
    # Validate product_id
    if not validate_object_id(product_id):
        flash("Invalid product ID", "danger")
        return redirect(url_for("shop"))
    
    # Get product
    product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        flash("Product not found", "danger")
        return redirect(url_for("shop"))
    
    # Check if product is in stock
    if product["stock"] <= 0:
        flash("Sorry, this product is out of stock", "danger")
        return redirect(url_for("product_detail", product_id=product_id))
    
    # Check if requested quantity is available
    if quantity > product["stock"]:
        flash(f"Sorry, only {product['stock']} items available", "warning")
        quantity = product["stock"]  # Adjust quantity to available stock
    
    # Initialize cart if it doesn't exist
    if "cart" not in session:
        session["cart"] = []
    
    # Check if product already in cart
    cart = session["cart"]
    product_in_cart = False
    
    for item in cart:
        if item["product_id"] == product_id:
            # Update quantity if product already in cart
            new_quantity = item["quantity"] + quantity
            
            # Check if new quantity exceeds available stock
            if new_quantity > product["stock"]:
                flash(f"Cannot add more. Only {product['stock']} items available", "warning")
                new_quantity = product["stock"]
                
            item["quantity"] = new_quantity
            product_in_cart = True
            break
    
    # Add product to cart if not already there
    if not product_in_cart:
        cart.append({
            "product_id": product_id,
            "name": product["name"],
            "price": product["price"],
            "quantity": quantity,
            "image": product.get("image", "default-product.jpg")
        })
    
    # Save cart to session
    session["cart"] = cart
    flash(f"{product['name']} added to cart", "success")
    
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/cart/update", methods=["POST","GET"])
def update_cart():
    """Update cart quantities"""
    product_id = request.form.get("product_id")
    quantity = int(request.form.get("quantity", 1))
    
    # Validate product_id
    if not validate_object_id(product_id):
        flash("Invalid product ID", "danger")
        return redirect(url_for("cart"))
    
    # Get product
    product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        flash("Product not found", "danger")
        return redirect(url_for("cart"))
    
    # Check stock
    if product["stock"] < quantity:
        flash("Not enough stock available", "danger")
        return redirect(url_for("cart"))
    
    # Get cart from session
    cart = session.get("cart", [])
    
    # Update quantity
    for item in cart:
        if item["product_id"] == product_id:
            item["quantity"] = quantity
            break
    
    session["cart"] = cart
    flash("Cart updated", "success")
    
    return redirect(url_for("cart"))

@app.route("/cart/remove", methods=["POST","GET"])
def remove_from_cart():
    """Remove product from cart"""
    product_id = request.form.get("product_id")
    
    # Get cart from session
    cart = session.get("cart", [])
    
    # Remove product from cart
    cart = [item for item in cart if item["product_id"] != product_id]
    
    session["cart"] = cart
    flash("Product removed from cart", "success")
    
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["POST","GET"])
@login_required
def checkout():
    """Process checkout and create order"""
    # Get cart from session
    cart = session.get("cart", [])
    
    if not cart:
        flash("Your cart is empty", "warning")
        return redirect(url_for("cart"))
    
    # Get form data
    payment_method = request.form.get("payment_method")
    shipping_address = request.form.get("shipping_address")
    county = request.form.get("county")
    location = request.form.get("location")
    phone = request.form.get("phone")
    
    # Validate input
    if not all([payment_method, shipping_address, county, location, phone]):
        flash("Please fill all required fields", "danger")
        return redirect(url_for("cart"))
    
    # Calculate totals
    subtotal = sum(item["price"] * item["quantity"] for item in cart)
    shipping = calculate_delivery_fee(county, location)
    #tax = subtotal * 0.16  # 16% tax
    total = subtotal + shipping
    
    # Verify stock availability and update product quantities
    order_items = []
    stock_issues = []
    
    for item in cart:
        product_id = item["product_id"]
        quantity = item["quantity"]
        
        # Get product from database
        product = mongo.db.products.find_one({"_id": ObjectId(product_id)})
        
        if not product:
            stock_issues.append(f"Product '{item['name']}' is no longer available")
            continue
        
        if product["stock"] < quantity:
            if product["stock"] > 0:
                stock_issues.append(f"Only {product['stock']} units of '{product['name']}' are available")
            else:
                stock_issues.append(f"'{product['name']}' is out of stock")
            continue
        
        # Add to order items
        order_items.append({
            "product_id": ObjectId(product_id),
            "name": product["name"],
            "price": product["price"],
            "quantity": quantity,
            "total": product["price"] * quantity,
            "image": product.get("image", "default-product.jpg")
        })
        
        # Update product stock
        new_stock = product["stock"] - quantity
        mongo.db.products.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": {"stock": new_stock}}
        )
    
    # If there are stock issues, redirect back to cart
    if stock_issues:
        for issue in stock_issues:
            flash(issue, "danger")
        return redirect(url_for("cart"))
    
    # Create order
    order = {
        "user_id": ObjectId(current_user.id),
        "items": order_items,
        "subtotal": subtotal,
        "shipping": shipping,
        "tax": tax,
        "total_price": total,
        "payment_method": payment_method,
        "customer_info": {
            "name": current_user.name,
            "email": current_user.email,
            "phone": phone,
            "address": shipping_address,
            "county": county,
            "location": location
        },
        "status": "pending",
        "is_paid": False,
        "is_processed": False,
        "is_shipped": False,
        "is_delivered": False,
        "created_at": datetime.now()
    }
    
    # Insert order
    result = mongo.db.orders.insert_one(order)
    html_body = render_template(
        'emails/order_confirmation.html',
        order=order,
        current_year=datetime.now().year
    )
    
    text_body = f"""
    Hello {order['shipping_address']['name']},
    
    Thank you for your order #${order['_id']}!
    
    Your order has been received and is being processed.
    
    You can view your order details at: {url_for('order_details', order_id=order['_id'], _external=True)}
    
    Best regards,
    GlamBeauty Team
    """
    
    send_email(
        subject='Your GlamBeauty Order Confirmation',
        recipients=[current_user.email],
        text_body=text_body,
        html_body=html_body
    )
    
    # Clear cart
    session["cart"] = []
    
    flash("Order placed successfully!", "success")
    return redirect(url_for("order_confirmation", order_id=result.inserted_id))

@app.route("/order-confirmation/<order_id>")
@login_required
def order_confirmation(order_id):
    """Order confirmation page"""
    # Validate order_id
    if not validate_object_id(order_id):
        flash("Invalid order ID", "danger")
        return redirect(url_for("profile"))
    
    # Get order
    order = mongo.db.orders.find_one({"_id": ObjectId(order_id), "user_id": ObjectId(current_user.id)})
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for("profile"))
    
    return render_template("order_confirmation.html", order=order)

# ============= APPOINTMENT ROUTES =============

@app.route("/appointments")
def appointments():
    """Appointments page"""
    # Get services
    services = list(mongo.db.services.find().sort("name", 1))
    
    # Group services by category
    service_categories = {}
    for service in services:
        category = service.get("category", "Other")
        if category not in service_categories:
            service_categories[category] = []
        service_categories[category].append(service)
    
    return render_template("appointments.html", service_categories=service_categories)

@app.route("/servicess")
def services():
    """Services page"""
    try:
        # Get all services from the database
        all_services = list(mongo.db.services.find().sort("name", 1))
        
        # Group services by category
        services_by_category = {}
        for service in all_services:
            category = service.get("category", "Other")
            if category not in services_by_category:
                services_by_category[category] = []
            services_by_category[category].append(service)
        
        # Get all categories for filtering
        categories = sorted(services_by_category.keys())
        google_maps_api_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
        print(f"Retrieved {len(all_services)} services across {len(categories)} categories")
        
        return render_template(
            "services.html", 
            services_by_category=services_by_category,
            google_maps_api_key=google_maps_api_key,
            categories=categories
        )
    except Exception as e:
        print(f"Error retrieving services: {e}")
        flash("An error occurred while loading services", "danger")
        return render_template("services.html", services_by_category={}, categories=[])

@app.route("/appointments/book", methods=["GET", "POST"])
@login_required
def book_appointment():
    """Book appointment page"""
    form = AppointmentForm()

    # Populate service choices dynamically from database
    services_list = safe_db_operation(
        lambda: list(mongo.db.services.find().sort("name", 1)),
        "Failed to load services",
        default_return=[]
    )
    form.service.choices = [(str(s['_id']), f"{s['name']} (KSH {s.get('price', 0)})") for s in services_list]

    # Get today's date for minimum date selection
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    # Generate time slots based on business hours with 30-minute intervals
    start_hour = 9  # 9 AM
    end_hour = 18   # 6 PM
    interval_minutes = 30
    
    time_slots = []
    current_time = datetime_time(start_hour, 0)
    end_time = datetime_time(end_hour, 0)
    
    while current_time <= end_time:
        time_slots.append((current_time.strftime('%H:%M'), current_time.strftime('%I:%M %p')))
        current_minute = current_time.minute + interval_minutes
        current_hour = current_time.hour + current_minute // 60
        current_minute %= 60
        if current_hour > 23: break
        current_time = datetime_time(current_hour, current_minute)
    
    form.time.choices = time_slots
    
    # Fetch locations from database instead of using hardcoded AVAILABLE_LOCATIONS
    counties = safe_db_operation(
        lambda: mongo.db.locations.distinct("county"),
        "Failed to load counties",
        default_return=[]
    )
    county_choices = [('', '-- Select County --')] + [(county, county) for county in counties]
    form.county.choices = county_choices

    # Get unavailable time slots for today from database
    today_start = datetime.combine(datetime.now().date(), datetime_time.min)
    today_end = datetime.combine(datetime.now().date(), datetime_time.max)
    
    unavailable_slots = []
    today_appointments = safe_db_operation(
        lambda: list(mongo.db.appointments.find({
            "appointment_date": {
                "$gte": today_start,
                "$lte": today_end
            }
        })),
        "Failed to check appointment availability",
        default_return=[]
    )
    
    # Mark slots as unavailable based on existing appointments and service durations
    for appointment in today_appointments:
        service_id = appointment.get("service_id")
        if not service_id:
            continue
            
        # Get the service to determine its duration
        service = safe_db_operation(
            lambda: mongo.db.services.find_one({"_id": service_id}),
            "Failed to fetch service details",
            default_return=None
        )
        
        if not service:
            continue
            
        # Get appointment time and calculate blocked slots
        appointment_datetime = appointment.get("appointment_date")
        if not appointment_datetime:
            continue
            
        appointment_time = appointment_datetime.time()
        service_duration = service.get("duration", 30)  # Default to 30 minutes if not specified
        
        # Block the initial slot
        unavailable_slots.append(appointment_time.strftime('%H:%M'))
        
        # Block additional slots based on service duration
        blocks_needed = (service_duration // interval_minutes)
        current_slot = appointment_datetime
        
        for i in range(1, blocks_needed):
            next_slot = current_slot + timedelta(minutes=interval_minutes)
            unavailable_slots.append(next_slot.time().strftime('%H:%M'))
            current_slot = next_slot

    # --- POST Request Handling ---
    if form.validate_on_submit():
        service_id = form.service_id.data
        print(f"Debug - Service ID from form: {service_id}")
        form.service.data = service_id
        appointment_date = form.date.data
        appointment_time_str = form.time.data
        location_type = form.location_type.data
        county = form.county.data
        location = form.location.data
        address = form.address.data
        notes = form.notes.data

        # Validate service_id
        if not validate_object_id(service_id):
            flash("Invalid service ID.", "danger")
            return render_template("appointments/book.html", 
                                  form=form, 
                                  services=services_list, 
                                  selected_service=None,
                                  unavailable_slots=unavailable_slots,
                                  today_date=today_date)

        # Fetch the selected service
        service = safe_db_operation(
            lambda: mongo.db.services.find_one({"_id": ObjectId(service_id)}),
            "Error fetching service details",
            default_return=None
        )
        if not service:
            flash("Service not found.", "danger")
            return render_template("appointments/book.html", 
                                  form=form, 
                                  services=services_list, 
                                  selected_service=None,
                                  unavailable_slots=unavailable_slots,
                                  today_date=today_date)

        # Parse time string and combine with date
        try:
            time_obj = datetime.strptime(appointment_time_str, "%H:%M").time()
            appointment_datetime = datetime.combine(appointment_date, time_obj)

            # Check if appointment is in the past
            if appointment_datetime < datetime.now():
                form.date.errors.append("Appointment date and time must be in the future.")
                flash("Appointment date and time must be in the future.", "danger")
                return render_template("appointments/book.html", 
                                      form=form, 
                                      services=services_list, 
                                      selected_service=service,
                                      unavailable_slots=unavailable_slots,
                                      today_date=today_date)
                                      
            # Check if the selected time slot is available
            if appointment_time_str in unavailable_slots:
                form.time.errors.append("This time slot is not available.")
                flash("The selected time slot is not available.", "danger")
                return render_template("appointments/book.html", 
                                      form=form, 
                                      services=services_list, 
                                      selected_service=service,
                                      unavailable_slots=unavailable_slots,
                                      today_date=today_date)
                                      
            # Check if there's enough time before closing
            service_duration = service.get("duration", 30)
            end_time_minutes = time_obj.hour * 60 + time_obj.minute + service_duration
            if end_time_minutes > (end_hour * 60):
                form.time.errors.append("Service would end after business hours.")
                flash("The selected service would end after business hours.", "danger")
                return render_template("appointments/book.html", 
                                      form=form, 
                                      services=services_list, 
                                      selected_service=service,
                                      unavailable_slots=unavailable_slots,
                                      today_date=today_date)
                
        except ValueError:
            form.time.errors.append("Invalid time format selected.")
            flash("Invalid time format.", "danger")
            return render_template("appointments/book.html", 
                                  form=form, 
                                  services=services_list, 
                                  selected_service=service,
                                  unavailable_slots=unavailable_slots,
                                  today_date=today_date)

        # --- Home Service Specific Logic ---
        home_service_fee = 0.00
        final_address = None
        if location_type == 'home':
            if not county or not location or not address:
                flash("County, Location/Sub-county, and Full Address are required for Home Service.", "danger")
                if not county: form.county.errors.append("County is required for home service.")
                if not location: form.location.errors.append("Location/Sub-county is required for home service.")
                if not address: form.address.errors.append("Full Address is required for home service.")
                return render_template("appointments/book.html", 
                                      form=form, 
                                      services=services_list, 
                                      selected_service=service,
                                      unavailable_slots=unavailable_slots,
                                      today_date=today_date)

            # Check if home service is available in this location from database
            home_service_available = safe_db_operation(
                lambda: mongo.db.locations.find_one({
                    "county": county,
                    "location": location,
                    "available_for_home_service": True
                }),
                "Failed to check home service availability",
                default_return=None
            )
            
            if not home_service_available:
                flash(f"Sorry, home service is not available in {location}, {county}.", "warning")
                form.location.errors.append(f"Home service not available in {location}.")
                return render_template("appointments/book.html", 
                                      form=form, 
                                      services=services_list, 
                                      selected_service=service,
                                      unavailable_slots=unavailable_slots,
                                      today_date=today_date)

            # Get home service fee from database
            location_data = safe_db_operation(
                lambda: mongo.db.locations.find_one({
                    "county": county,
                    "location": location
                }),
                "Failed to fetch location details",
                default_return=None
            )
            
            home_service_fee = location_data.get("home_service_fee", HOME_SERVICE_FEE) if location_data else HOME_SERVICE_FEE
            final_address = f"{address}, {location}, {county}"
        # --- End Home Service Logic ---

        # Create appointment dictionary
        appointment_data = {
            "user_id": ObjectId(current_user.id),
            "user_name": current_user.name,
            "user_email": current_user.email,
            "service_id": ObjectId(service_id),
            "service_name": service.get('name', 'N/A'),
            "service_price": service.get('price', 0.00),
            "service_duration": service.get('duration', 30),
            "appointment_date": appointment_datetime,
            "appointment_time": appointment_time_str,
            "location_type": location_type,
            "county": county if county else None,
            "location": location if location else None,
            "address": final_address,
            "home_service_fee": home_service_fee,
            "total_price": service.get('price', 0.00) + home_service_fee,
            "notes": notes,
            "status": "pending",
            "created_at": datetime.now()
        }

        # Insert appointment
        inserted_id = safe_db_operation(
            lambda: mongo.db.appointments.insert_one(appointment_data).inserted_id,
            "Failed to book appointment. Please try again.",
            default_return=None
        )

        if not inserted_id:
            return render_template("appointments/book.html", 
                                  form=form, 
                                  services=services_list, 
                                  selected_service=service,
                                  unavailable_slots=unavailable_slots,
                                  today_date=today_date)

        calendar_event = None
        try:
            calendar_event = add_to_google_calendar(appointment_data)
            if calendar_event:
                    # Update appointment with calendar event info
                mongo.db.appointments.update_one(
                    {"_id": inserted_id},
                    {"$set": {
                        "calendar_event_id": calendar_event.get('event_id'),
                        "calendar_event_link": calendar_event.get('event_link')
                    }}
                )
        except Exception as e:
            print(f"Error adding appointment to Google Calendar: {e}")


    

        # Send appointment confirmation email
        try:
            html_body = render_template(
            'emails/appointment_confirmation.html',
            user=current_user,
            appointment=appointment_data,
            calendar_event=calendar_event,
            current_year=datetime.now().year
            )
        
            text_body = f"""
            Hello {current_user.name},
            
            Your appointment for {appointment_data['service_name']} on {appointment_data['appointment_date'].strftime('%A, %B %d, %Y at %I:%M %p')} has been confirmed.
            
            Service: {appointment_data['service_name']}
            Date & Time: {appointment_data['appointment_date'].strftime('%A, %B %d, %Y at %I:%M %p')}
            Type: {'Home Service' if appointment_data['location_type'] == 'home' else 'Salon Visit'}
            Total Price: KES {appointment_data['total_price']:.2f}
            
            You can manage your appointment at: {url_for('profile_appointments', _external=True)}
            
            Best regards,
            GlamBeauty Team
            """
            
            send_email(
                subject='Your GlamBeauty Appointment Confirmation',
                recipients=[current_user.email],
                text_body=text_body,
                html_body=html_body
            )    

            flash("Appointment booked successfully and confirmation email sent.", "success")
        except Exception as e:
            print(f"Error sending confirmation email for appointment {inserted_id}: {e}")
            if calendar_event:
                flash("Appointment booked successfully and added to your Google Calendar, but confirmation email could not be sent.", "warning")
            else:
                flash("Appointment booked successfully, but confirmation email could not be sent.", "warning")
            

        return redirect(url_for("profile_appointments"))

    # --- GET Request Handling ---
    else:
        if request.method == "POST":
            flash("Please correct the errors below.", "danger")
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in {field}: {error}", "warning")

        service_id_get = request.args.get("service_id")
        selected_service = None

        if service_id_get:
            if not validate_object_id(service_id_get):
                flash("Invalid service ID provided in URL.", "warning")
            else:
                selected_service = safe_db_operation(
                    lambda: mongo.db.services.find_one({"_id": ObjectId(service_id_get)}),
                    "Error fetching selected service details",
                    default_return=None
                )

                if not selected_service:
                    flash("Selected service not found.", "warning")
                elif request.method == "GET":
                    form.service.data = service_id_get
                    form.service_id.data = service_id_get

        return render_template("appointments/book.html",
                              form=form,
                              services=services_list,
                              selected_service=selected_service,
                              unavailable_slots=unavailable_slots,
                              today_date=today_date)

@app.route("/appointments/<appointment_id>/cancel", methods=["POST","GET"])
@login_required
def cancel_appointment(appointment_id):
    """Cancel appointment"""
    # Validate appointment_id
    if not validate_object_id(appointment_id):
        flash("Invalid appointment ID", "danger")
        return redirect(url_for("profile"))
    
    # Get appointment
    appointment = mongo.db.appointments.find_one({
        "_id": ObjectId(appointment_id),
        "user_id": ObjectId(current_user.id)
    })
    
    if not appointment:
        flash("Appointment not found", "danger")
        return redirect(url_for("profile"))
    
    # Check if appointment is in the past
    if appointment["appointment_date"] < datetime.now():
        flash("Cannot cancel past appointments", "danger")
        return redirect(url_for("profile"))
    
    # Update appointment status
    mongo.db.appointments.update_one(
        {"_id": ObjectId(appointment_id)},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now()}}
    )
    
    flash("Appointment cancelled successfully", "success")
    return redirect(url_for("profile"))

@app.route("/appointments/<appointment_id>/reschedule", methods=["GET", "POST"])
@login_required
def reschedule_appointment(appointment_id):
    """Handle appointment rescheduling."""
    # Validate appointment_id
    if not validate_object_id(appointment_id):
        flash("Invalid appointment ID", "danger")
        return redirect(url_for("profile_appointments"))
    
    # Get appointment
    appointment = mongo.db.appointments.find_one({
        "_id": ObjectId(appointment_id),
        "user_id": ObjectId(current_user.id)
    })
    
    if not appointment:
        flash("Appointment not found", "danger")
        return redirect(url_for("profile_appointments"))
    
    # Check if appointment is in the past
    if appointment.get("appointment_date") < datetime.now():
        flash("Cannot reschedule past appointments", "danger")
        return redirect(url_for("profile_appointments"))

    today = datetime.now()

    # Handle form submission
    if request.method == "POST":
        date_str = request.form.get("date")
        time_str = request.form.get("time")
        
        try:
            # Parse the date and time
            new_date = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            
            # Ensure the new date is in the future
            if new_date < datetime.now():
                flash("Cannot reschedule to a past date and time", "danger")
                return redirect(url_for("reschedule_appointment", appointment_id=appointment_id))
            
            # Update appointment
            mongo.db.appointments.update_one(
                {"_id": ObjectId(appointment_id)},
                {
                    "$set": {
                        "appointment_date": new_date,
                        "time": time_str,
                        "updated_at": datetime.now(),
                        "rescheduled": True
                    }
                }
            )
            
            flash("Appointment rescheduled successfully", "success")
            return redirect(url_for("profile_appointments"))
            
        except ValueError:
            flash("Invalid date or time format", "danger")
    
    # For GET request, display the form
    return render_template(
        "appointments/reschedule.html", 
        appointment=appointment,
        today=today
    )

@app.route("/appointments/<appointment_id>/reschedule", methods=["POST"])
@login_required
def reschedule_appointment_post(appointment_id):
    """Process appointment reschedule"""
    # Validate appointment_id
    if not validate_object_id(appointment_id):
        flash("Invalid appointment ID", "danger")
        return redirect(url_for("profile"))
    
    # Get appointment
    appointment = mongo.db.appointments.find_one({
        "_id": ObjectId(appointment_id),
        "user_id": ObjectId(current_user.id)
    })
    
    if not appointment:
        flash("Appointment not found", "danger")
        return redirect(url_for("profile"))
    
    # Check if appointment is in the past
    if appointment["appointment_date"] < datetime.now():
        flash("Cannot reschedule past appointments", "danger")
        return redirect(url_for("profile"))
    
    # Get form data
    date_str = request.form.get("date")
    time_str = request.form.get("time")
    
    try:
        # Parse the date and time
        new_date = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        
        # Ensure the new date is in the future
        if new_date < datetime.now():
            flash("Cannot reschedule to a past date and time", "danger")
            return redirect(url_for("reschedule_appointment", appointment_id=appointment_id))
        
        # Update appointment
        mongo.db.appointments.update_one(
            {"_id": ObjectId(appointment_id)},
            {
                "$set": {
                    "appointment_date": new_date,
                    "time": time_str,
                    "updated_at": datetime.now(),
                    "rescheduled": True
                }
            }
        )
        
        flash("Appointment rescheduled successfully", "success")
        return redirect(url_for("profile"))
        
    except ValueError:
        flash("Invalid date or time format", "danger")
        return redirect(url_for("reschedule_appointment", appointment_id=appointment_id))

# ... existing code ...

@app.route("/appointments/review/<appointment_id>", methods=["GET", "POST"])
@login_required
def leave_review(appointment_id):
    """Leave a review for a completed appointment"""
    # Validate appointment ID
    if not validate_object_id(appointment_id):
        flash("Invalid appointment ID.", "danger")
        return redirect(url_for("profile_appointments"))
    
    # Get the appointment
    appointment = safe_db_operation(
        lambda: mongo.db.appointments.find_one({"_id": ObjectId(appointment_id), "user_id": current_user.id}),
        "Failed to retrieve appointment details",
        default_return=None
    )
    
    if not appointment:
        flash("Appointment not found or you don't have permission to review it.", "danger")
        return redirect(url_for("profile_appointments"))
    
    # Check if appointment is completed
    if appointment.get("status") != "completed":
        flash("You can only review completed appointments.", "warning")
        return redirect(url_for("profile_appointments"))
    
    # Check if already reviewed
    existing_review = safe_db_operation(
        lambda: mongo.db.testimonials.find_one({"appointment_id": ObjectId(appointment_id)}),
        "Failed to check for existing review",
        default_return=None
    )
    
    if existing_review:
        flash("You have already reviewed this appointment.", "info")
        return redirect(url_for("profile_appointments"))
    
    # Handle form submission
    if request.method == "POST":
        # Get form data
        rating = int(request.form.get("rating", 5))
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        recommend = "recommend" in request.form
        
        # Validate form data
        if not title or not content:
            flash("Please provide both a title and review content.", "danger")
        elif rating < 1 or rating > 5:
            flash("Please provide a valid rating between 1 and 5.", "danger")
        else:
            # Get service details
            service_id = appointment.get("service_id")
            service = None
            if service_id:
                service = safe_db_operation(
                    lambda: mongo.db.services.find_one({"_id": service_id}),
                    "Failed to retrieve service details",
                    default_return=None
                )
            
            # Create testimonial document
            testimonial = {
                "user_id": current_user.id,
                "name": current_user.name,
                "appointment_id": ObjectId(appointment_id),
                "service_id": service_id,
                "service": service.get("name") if service else appointment.get("service_name", "Beauty Service"),
                "rating": rating,
                "title": title,
                "text": content,
                "recommend": recommend,
                "created_at": datetime.now(),
                "approved": False  # Require admin approval before displaying
            }
            
            # Insert testimonial
            result = safe_db_operation(
                lambda: mongo.db.testimonials.insert_one(testimonial),
                "Failed to save your review",
                default_return=None
            )
            
            if result:
                # Mark appointment as reviewed
                safe_db_operation(
                    lambda: mongo.db.appointments.update_one(
                        {"_id": ObjectId(appointment_id)},
                        {"$set": {"reviewed": True}}
                    ),
                    "Failed to update appointment review status",
                    default_return=None
                )
                
                flash("Thank you for your review! It will be displayed after approval.", "success")
                return redirect(url_for("profile_appointments"))
            else:
                flash("Failed to submit your review. Please try again.", "danger")
    
    # Render the review form
    return render_template("user/leave_review.html", appointment=appointment)

# ============= ERROR HANDLERS =============

@app.errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_url_params(request, required_params=None, optional_params=None):
    """Validate URL parameters"""
    required_params = required_params or []
    optional_params = optional_params or []
    
    # Check required parameters
    for param in required_params:
        if param not in request.args:
            return False, f"Missing required parameter: {param}"
    
    # Return success
    return True, None

# ============= STATIC FILES =============

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# Run the app
if __name__ == "__main__":
    #init_scheduler()
    app.run(host='0.0.0.0',port=5000,debug=True)