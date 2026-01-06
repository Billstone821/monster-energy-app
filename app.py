import os
import json
import base64
import requests
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from dotenv import load_dotenv

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
# --- UI & FEATURE SETTINGS ---
    can_export = True  # Adds the button to download leads as Excel/CSV
    column_default_sort = ('id', True)  # Newest leads show up at the top
    column_searchable_list = ['full_name', 'email', 'phone']  # Adds a search bar
    column_filters = ['state', 'city']  # Adds dropdown filters on the right
    page_size = 50  # Shows 50 leads per page instead of 20
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

        # 2. reCAPTCHA Verification
        recaptcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_req = requests.post(recaptcha_verify_url, data={
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response,
            'remoteip': request.remote_addr
        })
        if not recaptcha_req.json().get('success'):
            flash('reCAPTCHA failed.', 'error')
            return redirect(url_for('index'))

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
            age_18_plus=(age_check == 'yes')
        )
        db.session.add(new_submission)
        db.session.commit()

        # 4. Send Email via BREVO
        try:
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                sender={"email": FROM_EMAIL, "name": "Monster Energy"},
                to=[{"email": NOTIFY_EMAIL}],
                reply_to={"email": email},
                subject=f"New Submission: {full_name}",
                html_content=f"""
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
                )
            api_instance.send_transac_email(send_smtp_email)
            print(f"[INFO] Brevo email sent successfully for {full_name}.")
        except Exception as email_err:
            print(f"[ERROR] Email failed but database saved: {email_err}")

        return redirect(url_for('thankyou_page'))

    except Exception as e:
        db.session.rollback()
        print(f"[CRITICAL ERROR]: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('index'))

# --- Database Creation & App Run ---
with app.app_context():
    try:
        db.create_all()
        print("[INFO] Database tables checked/created.")
    except Exception as e:
        print(f"[ERROR] Database creation failed: {e}")

if __name__ == '__main__':
# 1. First, setup the database tables
    with app.app_context():
        db.create_all()
        print("Database tables created/verified successfully!")
    
    # 2. Then, start the website
    # On Render, 'host' and 'port' are usually handled by the environment
    # but 0.0.0.0 is safe to keep.
    app.run(debug=False, host='0.0.0.0', port=5000)
   