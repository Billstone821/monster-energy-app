The code you need is the full, correct content for your `app.py` file. It includes the routes for the homepage and the sitemap that were causing the `404 Not Found` error.

Please copy and paste this entire block of code into your `app.py` file.

```python
import os
import json
import base64
import requests # Import the requests library for making HTTP requests
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, flash, Response, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, To, PlainTextContent, Mail
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
load_dotenv()

# --- Configuration from .env ---
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
REPLY_TO_EMAIL = os.getenv("REPLY_TO")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")

# --- Environment Variable Checks ---
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is missing from .env. Please set it for Flask sessions.")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing from .env. Please set it (e.g., sqlite:///submissions.db).")
if not SENDGRID_API_KEY:
    raise ValueError("SENDGRID_API_KEY is missing from .env. Please set it for email functionality.")
if not NOTIFY_EMAIL or not FROM_EMAIL or not REPLY_TO_EMAIL:
    raise ValueError("NOTIFY_EMAIL, FROM_EMAIL, or REPLY_TO is missing from .env. Please set them for email functionality.")
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise ValueError("ADMIN_USERNAME or ADMIN_PASSWORD is missing from .env. Please set them for admin access.")
if not RECAPTCHA_SECRET_KEY:
    raise ValueError("RECAPTCHA_SECRET_KEY is missing from .env. Please set it for reCAPTCHA verification.")


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

    def __repr__(self):
        return f'<Submission {self.full_name} - {self.email}>'

# --- Flask-Admin Setup ---
class AuthenticatedModelView(ModelView):
    def is_accessible(self):
        print("[DEBUG] is_accessible called for Flask-Admin.")
        auth_header = request.headers.get('Authorization')
        print(f"[DEBUG] Authorization Header: {auth_header}")
        if not auth_header:
            print("[DEBUG] No Authorization header found. Returning False.")
            return False
        try:
            auth_type, credentials = auth_header.split(None, 1)
            print(f"[DEBUG] Auth Type: {auth_type}, Credentials: {credentials}")
            if auth_type.lower() == 'basic':
                username, password = base64.b64decode(credentials).decode('utf-8').split(':', 1)
                print(f"[DEBUG] Decoded Username: {username}, Password: {password}")
                if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                    print("[DEBUG] Credentials match. Returning True.")
                    return True
                else:
                    print("[DEBUG] Credentials do NOT match. Returning False.")
                    return False
        except Exception as e:
            print(f"[ERROR] Error parsing Authorization header: {e}. Returning False.")
            pass
        print("[DEBUG] Fallback: Returning False (e.g., non-basic auth or other error).")
        return False

    def inaccessible_callback(self, name, **kwargs):
        print("[DEBUG] inaccessible_callback called. Sending 401 Unauthorized.")
        return Response("Unauthorized. Please log in.", 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

admin = Admin(app, name='Monster Admin', template_mode='bootstrap3')
admin.add_view(AuthenticatedModelView(Submission, db.session))

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/thankyou')
def thankyou_page():
    return render_template('thank_you.html')

@app.route('/submit', methods=['POST'])
def submit_application():
    try:
        # Corrected variable names to match index.html form inputs
        full_name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        contact_method = request.form.get('contact_method')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip')
        age_18_plus = request.form.get('age') == 'yes' # Boolean check
        recaptcha_response = request.form.get('g-recaptcha-response')

        # --- Server-side reCAPTCHA verification ---
        if not recaptcha_response:
            print("[ERROR] reCAPTCHA response missing.")
            flash('Please complete the reCAPTCHA verification.', 'error')
            return redirect(url_for('index'))

        recaptcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_payload = {
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response,
            'remoteip': request.remote_addr
        }

        try:
            recaptcha_req = requests.post(recaptcha_verify_url, data=recaptcha_payload)
            recaptcha_result = recaptcha_req.json()
            print(f"[DEBUG] reCAPTCHA verification result: {recaptcha_result}")

            if not recaptcha_result.get('success'):
                print(f"[ERROR] reCAPTCHA verification failed: {recaptcha_result.get('error-codes')}")
                flash('reCAPTCHA verification failed. Please try again.', 'error')
                return redirect(url_for('index'))
        except requests.exceptions.RequestException as e:
            print(f"[CRITICAL ERROR] reCAPTCHA API request failed: {e}")
            flash('reCAPTCHA service unavailable. Please try again later.', 'error')
            return redirect(url_for('index'))
        
        # --- End of Server-side reCAPTCHA verification ---

        new_submission = Submission(
            full_name=full_name,
            email=email,
            phone=phone,
            contact_method=contact_method,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            age_18_plus=age_18_plus
        )
        db.session.add(new_submission)
        db.session.commit()
        print(f"[INFO] Application from {full_name} saved to database.")
        flash('Your application has been submitted successfully!', 'success')

        try:
            message_content = f"""
            New Monster Energy Campaign Application!

            Full Name: {full_name}
            Email: {email}
            Phone: {phone}
            Preferred Contact Method: {contact_method}
            Address: {address}, {city}, {state}, {zip_code}
            Age 18+: {'Yes' if age_18_plus else 'No'}
            Submitted On: {new_submission.timestamp}
            """
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            from_email_obj = Email(FROM_EMAIL)
            to_email_obj = To(NOTIFY_EMAIL)
            plain_text_content = PlainTextContent(message_content)
            
            mail_message = Mail(
                from_email_obj,
                to_email_obj,
                "New Monster Energy Campaign Application",
                plain_text_content
            )
            mail_message.reply_to = Email(REPLY_TO_EMAIL)

            response = sg.send(mail_message)
            print(f"[INFO] Email sent successfully. Status Code: {response.status_code}")
        except Exception as e:
            print(f"[ERROR] Failed to send email: {e}")
            flash('Failed to send confirmation email, but your application was submitted.', 'warning')

        return redirect(url_for('thankyou_page'))

    except Exception as e:
        db.session.rollback()
        print(f"[CRITICAL ERROR] Error processing form submission: {e}")
        flash('Your application could not be submitted due to a server error. Please try again.', 'error')
        return redirect(url_for('index'))

# This is the new, separate route for the sitemap.xml file.
# It must be placed outside of any other function.
@app.route('/sitemap.xml')
def serve_sitemap():
    return send_from_directory('static', 'sitemap.xml')

if __name__ == '__main__':
    with app.app_context():
        # DO NOT uncomment these lines unless you want to reset your database entirely.
        # db.drop_all()
        # db.create_all()
        pass
    app.run(debug=True, host='0.0.0.0')
```