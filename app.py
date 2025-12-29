import os
import json
import base64
import requests
import resend  # Swapped from sendgrid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration from Render/Env ---
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY") # Updated name
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
REPLY_TO_EMAIL = os.getenv("REPLY_TO")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")

# --- Environment Variable Checks ---
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is missing.")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing.")
if not RESEND_API_KEY:
    raise ValueError("RESEND_API_KEY is missing. Please set it in Render settings.")
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise ValueError("Admin credentials missing.")

# Initialize Resend
resend.api_key = RESEND_API_KEY

# --- Flask App Initialization ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Database Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)

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

# --- Flask-Admin Setup ---
class AuthenticatedModelView(ModelView):
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
        full_name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        contact_method = request.form.get('contact_method')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip')
        age_18_plus = request.form.get('age') == 'yes'
        recaptcha_response = request.form.get('g-recaptcha-response')

        # reCAPTCHA Verification
        recaptcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_req = requests.post(recaptcha_verify_url, data={
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response,
            'remoteip': request.remote_addr
        })
        if not recaptcha_req.json().get('success'):
            flash('reCAPTCHA failed.', 'error')
            return redirect(url_for('index'))

        # Save to Database
        new_submission = Submission(
            full_name=full_name, email=email, phone=phone,
            contact_method=contact_method, address=address,
            city=city, state=state, zip_code=zip_code, age_18_plus=age_18_plus
        )
        db.session.add(new_submission)
        db.session.commit()

        # Send Email via RESEND
        try:
            resend.Emails.send({
                "from": FROM_EMAIL,
                "to": NOTIFY_EMAIL,
                "subject": f"New Application: {full_name}",
                "reply_to": email,
                "html": f"""
                    <h3>New Application Details</h3>
                    <hr>
                    <p><b>Name:</b> {full_name}</p>
                    <p><b>Email:</b> {email}</p>
                    <p><b>Phone:</b> {phone}</p>
                    <p><b>Contact Method:</b> {contact_method}</p>
                    <p><b>Address:</b> {address}, {city}, {state}, {zip_code}</p>
                    <p><b>Age 18+:</b> {age_check}</p>
                    <hr>
                    <p><i>Submitted on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i></p>
                """
            }) # This closes the resend.Emails.send function
            print("[INFO] Resend email sent successfully.")
        except Exception as e:
            print(f"[ERROR] Resend failed: {e}")

        return redirect(url_for('thankyou_page'))

    except Exception as e:
        db.session.rollback()
        print(f"[CRITICAL] {e}")
        flash('Server error.', 'error')
        return redirect(url_for('index'))

# --- DATABASE AND RUN COMMANDS (KEEP AT THE BOTTOM) ---
with app.app_context():
    try:
        db.create_all()
        print("[INFO] Database tables checked/created.")
    except Exception as e:
        print(f"[ERROR] Database creation failed: {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)