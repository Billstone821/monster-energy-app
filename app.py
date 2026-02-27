import os
import json
import base64
import requests
import random
import re
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
    
def spin(text):
    """Randomly chooses words between { | } brackets"""
    while "{" in text:
        match = re.search(r'\{([^{}]*)\}', text)
        if not match: break
        options = match.group(1).split("|")
        text = text[:match.start()] + random.choice(options) + text[match.end():]
    return text

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
         force_https=True, 
         session_cookie_secure=True, 
         strict_transport_security=False)      

# 3. APPLY COMPRESSION
Compress(app)

MAINTENANCE_MODE = True

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

@app.before_request
def check_for_maintenance():
    # Allow static files (images/css) and your secret admin gate to remain accessible
    allowed_paths = ['/static', '/akile-login-gate']
    if MAINTENANCE_MODE and not any(request.path.startswith(path) for path in allowed_paths):
        return render_template('maintenance.html'), 503
        
# --- PLACE 1: THE EMAIL MACHINE (UPDATED VERSION) ---
def send_monster_email(email, full_name, uid):

    # 2. Setup Variables
    short_id = uid[:8].upper()
    brand_name = "Monster Partner"
    
    random_data = {
        "name": full_name,
        "brand": brand_name,
        "color": "#95D600",
        "padding": random.randint(20, 30),
        "short_id": short_id,
        "uid": uid
    }

    
    try:
        raw_html = render_template('email_template.html', **random_data)
        final_html = spin(raw_html)
    except Exception as e:
        print(f"CRITICAL ERROR: Template render failed: {e}")
        return

    
    # Randomize the Sender Name metadata
    final_subject = f"Regarding your inquiry, {full_name} (Ref: #{short_id})"
    final_sender_name = "Monster Support Team"

    # 5. Brevo Send
    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": email, "name": full_name}],
        sender={"email": FROM_EMAIL, "name": final_sender_name}, 
        reply_to={"email": "support@monstercampaigns.info", "name": "Monster Support"},
        subject=final_subject,
        html_content=final_html
    )

    try:
        api_instance.send_transac_email(send_smtp_email)
        print(f"SUCCESS: Inbox-optimized email sent to {email}")
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

admin = Admin(app, name='Monster Admin', url='/akile-login-gate', template_mode='bootstrap3')
admin.add_view(AuthenticatedModelView(Submission, db.session))

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/thankyou')
def thankyou_page():
    return render_template('thank_you.html')
    
@app.route('/privacy')
def privacy_page():
    return render_template('privacy.html')
    
@app.route('/terms')
def terms_page():
    return render_template('terms.html')
    
@app.route('/robots.txt')
@app.route('/sitemap.xml')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])

@app.route('/unsubscribe')
def unsubscribe_page():
    return render_template('unsubscribe.html')
    
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        # 1. Capture the form data
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject') or "General Inquiry"
        message = request.form.get('message')

        # 2. Format the message for Telegram
        contact_alert = (
            f"<b>📩 NEW CONTACT INQUIRY</b>\n\n"
            f"<b>👤 Name:</b> {name}\n"
            f"<b>📧 Email:</b> {email}\n"
            f"<b>📝 Subject:</b> {subject}\n"
            f"<b>💬 Message:</b>\n{message}"
        )

        # 3. Send the alert using your existing function
        try:
            send_telegram_alert(contact_alert)
        except Exception as e:
            print(f"Contact Alert Error: {e}")

        # 4. Trigger the success state in contact.html
        return render_template('contact.html', success=True)
        
    return render_template('contact.html')
    
@app.route('/sitemap.xml')
def serve_sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/submit', methods=['POST'])
def submit_application():
    try:
        # If this hidden field is filled, it's a bot.
        if request.form.get('website'):
            return "OK", 200 # Silent kill: Bot thinks it succeeded
            
        # 1. Capture data from form
        full_name = request.form.get('name')
        email = request.form.get('email', '').lower().strip()
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
        
        # --- NEW: BACKEND REGEX VALIDATION ---
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        # List of common temporary email providers
        blacklist = [
            'tempmail.com', '10minutemail.com', 'guerrillamail.com', 
            'mailinator.com', 'dispostable.com', 'temp-mail.org', 
            'getnada.com', 'yopmail.com'
        ]

        if not re.match(email_regex, email):
            return "Invalid email format. Please go back.", 400

        # Check if the domain is in our blacklist
        domain = email.split('@')[-1]
        if domain in blacklist:
            return "To ensure you receive our partnership updates, please provide a standard email address. We are unable to send responses to temporary or disposable domains.", 400
        
        # --- NEW: DUPLICATE PROTECTION ---
        # Check if this email already exists in our database
        existing_user = Submission.query.filter_by(email=email).first()
        
        if existing_user:
            # If they already exist, don't save anything! 
            # Just show them the thank you page so they don't try again.
            return render_template('thank_you.html')
        
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
            fingerprint_id=uid
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
        send_monster_email(email, full_name, uid)

        # Send alert to YOUR Telegram (Place this here!)
        alert_text = (
            f"<b>🔥 NEW APPLICATION MONSTER!</b>\n\n"
            f"<b>🆔 Case Ref:</b> <code>{uid[:8].upper()}</code>\n"
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
if __name__ == "__main__":
    with app.app_context():
        try:
            db.create_all()
            print("[INFO] Database tables checked/created.")
        except Exception as e:
            print(f"[ERROR] Database creation failed: {e}")

    # Bind to 0.0.0.0 and the Starter Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

