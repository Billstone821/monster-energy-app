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
from sendgrid.helpers.mail import Email, To, PlainTextContent, Mail # ADDED Mail here
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from rag_utils import load_webpage_content_for_rag, retrieve_relevant_chunks
from dotenv import load_dotenv

# Load environment variables from .env file at the very beginning
load_dotenv()

# --- Configuration from .env ---
API_KEY = os.getenv("GEMINI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")
REPLY_TO_EMAIL = os.getenv("REPLY_TO")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY") # New: reCAPTCHA Secret Key

# --- Environment Variable Checks ---
if not API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from .env. Please set it to run the application.")
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
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Database Initialization ---
db = SQLAlchemy(app)
migrate = Migrate(app, db) # Initialize Flask-Migrate

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
            pass # Continue to return False if parsing fails
        print("[DEBUG] Fallback: Returning False (e.g., non-basic auth or other error).")
        return False

    def inaccessible_callback(self, name, **kwargs):
        print("[DEBUG] inaccessible_callback called. Sending 401 Unauthorized.")
        return Response("Unauthorized. Please log in.", 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})

admin = Admin(app, name='Monster Admin', template_mode='bootstrap3')
admin.add_view(AuthenticatedModelView(Submission, db.session))

# --- RAG Retriever Initialization ---
rag_retriever = None

# Initialize RAG retriever within an app context when the app starts
with app.app_context():
    try:
        index_html_path = os.path.join(app.root_path, 'templates', 'index.html')
        print(f"[DEBUG] Attempting to load index.html for RAG from: {index_html_path}")
        rag_retriever = load_webpage_content_for_rag(index_html_path)
        if rag_retriever:
            print("[INFO] index.html content loaded and indexed for RAG successfully.")
        else:
            print("[ERROR] RAG retriever could not be created. Check rag_utils.py errors.")
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to initialize RAG retriever: {e}")
        rag_retriever = None

# --- Generative AI Model Initialization ---
try:
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.2, google_api_key=API_KEY)
    print("[INFO] Gemini LLM initialized successfully.")
except Exception as e:
    print(f"[CRITICAL ERROR] Failed to initialize Gemini LLM: {e}")
    llm = None

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/thankyou')
def thankyou_page():
    return render_template('thank_you.html')

@app.route('/chat/greeting', methods=['GET'])
def get_initial_greeting():
    initial_message = "Hello! I'm Rose, Welcome to Monster Energy Pay to Drive Program! Let me know how i can assist you today"
    history = [
        SystemMessage(content="You are a friendly and helpful Monster Energy Drink advertising campaign assistant. Your goal is to answer user questions accurately and concisely based *only* on the information provided in the Monster Energy Drink 'Drive & Earn' campaign webpage. Do not invent information. Do not use phrases like 'Based on the provided information', 'The text states', 'According to the document', 'The webpage says', or similar explicit citations. Just directly answer the question using the information you have. If the information is not available in the webpage, state that you cannot find the answer there. Maintain a positive and energetic tone."),
        AIMessage(content=initial_message)
    ]
    # Use model_dump() instead of dict() to avoid PydanticDeprecatedSince20 warning
    session['chat_history'] = [msg.model_dump() for msg in history]
    return jsonify({"response": initial_message, "history": [msg.model_dump() for msg in history]})

@app.route('/chat', methods=['POST'])
def chat():
    user_message_text = request.json.get('message')
    conversation_history_dicts = session.get('chat_history', [])

    conversation_history = []
    for msg_dict in conversation_history_dicts:
        if msg_dict['type'] == 'human':
            conversation_history.append(HumanMessage(content=msg_dict['content']))
        elif msg_dict['type'] == 'ai':
            conversation_history.append(AIMessage(content=msg_dict['content']))
        elif msg_dict['type'] == 'system':
            conversation_history.append(SystemMessage(content=msg_dict['content']))

    if not user_message_text:
        return jsonify({"response": "Please type a message.", "history": conversation_history_dicts}), 400

    context_chunks = []
    if rag_retriever:
        try:
            context_chunks = retrieve_relevant_chunks(rag_retriever, user_message_text)
            print(f"[INFO] Retrieved {len(context_chunks)} context chunks for RAG.")
        except Exception as e:
            print(f"[ERROR] Error retrieving context chunks for RAG: {e}")
    else:
        print("[WARNING] RAG retriever not initialized. Chatbot will respond without document context.")

    rag_context_str = "\n".join([chunk.page_content for chunk in context_chunks])

    if not rag_context_str:
        system_prompt_content = "You are a friendly and helpful Monster Energy Drink advertising campaign assistant. Your goal is to answer user questions accurately and concisely. Do not invent information. If you cannot find the answer, state that you cannot find the answer. Maintain a positive and energetic tone. The information from the webpage is currently unavailable."
    else:
        system_prompt_content = f"""You are a friendly and helpful Monster Energy Drink advertising campaign assistant.
Your goal is to answer user questions accurately and concisely based *only* on the following information from the Monster Energy Drink 'Drive & Earn' campaign webpage:

---
{rag_context_str}
---

Do not invent information. Do not use phrases like 'Based on the provided information', 'The text states', 'According to the document', 'The webpage says', or similar explicit citations. Just directly answer the question using the information you have. If the information is not available in the webpage, state that you cannot find the answer there. Maintain a positive and energetic tone.
"""

    if conversation_history and isinstance(conversation_history[0], SystemMessage):
        conversation_history[0].content = system_prompt_content
    else:
        conversation_history.insert(0, SystemMessage(content=system_prompt_content))

    conversation_history.append(HumanMessage(content=user_message_text))

    try:
        if llm is None:
            raise RuntimeError("LLM not initialized. Cannot generate response.")

        print("[DEBUG] Attempting to invoke LLM for user query...")
        ai_response = llm.invoke(conversation_history)
        response_text = ai_response.content
        print("[DEBUG] LLM invoked successfully. Response received.")

        conversation_history.append(AIMessage(content=response_text))
        # Use model_dump() instead of dict() to avoid PydanticDeprecatedSince20 warning
        session['chat_history'] = [msg.model_dump() for msg in conversation_history]

        return jsonify({"response": response_text, "history": [msg.model_dump() for msg in conversation_history]})
    except Exception as e:
        print(f"[CRITICAL ERROR] Error during LLM invocation or chat processing: {e}")
        if conversation_history and isinstance(conversation_history[-1], HumanMessage):
            conversation_history.pop()
        session['chat_history'] = [msg.model_dump() for msg in conversation_history]
        return jsonify({
            "response": "Sorry, I'm currently experiencing a technical issue and cannot respond. Please try again in a moment.",
            "history": [msg.model_dump() for msg in conversation_history]
        }), 500

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

        # --- Server-side reCAPTCHA verification ---
        if not recaptcha_response:
            print("[ERROR] reCAPTCHA response missing.")
            flash('Please complete the reCAPTCHA verification.', 'error')
            return redirect(url_for('index'))

        # Google reCAPTCHA verification URL
        recaptcha_verify_url = "https://www.google.com/recaptcha/api/siteverify"
        recaptcha_payload = {
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response,
            'remoteip': request.remote_addr # Optional: IP address of the user
        }

        try:
            recaptcha_req = requests.post(recaptcha_verify_url, data=recaptcha_payload)
            recaptcha_result = recaptcha_req.json()
            print(f"[DEBUG] reCAPTCHA verification result: {recaptcha_result}")

            if not recaptcha_result.get('success'):
                print(f"[ERROR] reCAPTCHA verification failed: {recaptcha_result.get('error-codes')}")
                flash('reCAPTCHA verification failed. Please try again.', 'error')
                return redirect(url_for('index'))
            # Optional: Check score for reCAPTCHA v3, if implemented
            # if recaptcha_result.get('score', 0) < 0.5:
            #     print("[WARNING] reCAPTCHA score too low, likely bot.")
            #     flash('reCAPTCHA verification failed (low score). Please try again.', 'error')
            #     return redirect(url_for('index'))

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
            
            mail_message = Mail( # Changed from sendgrid.helpers.mail.Mail to Mail
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
        return redirect(url_for('index')) # No error parameter needed, flash handles it

if __name__ == '__main__':
    # --- TEMPORARY DATABASE RESET FOR DEBUGGING ---
    # These lines will drop all tables and recreate them based on your models.
    # THIS SHOULD ONLY BE RUN ONCE FOR INITIAL SETUP OR WHEN SCHEMA IS BROKEN.
    # AFTER THE FIRST SUCCESSFUL RUN, COMMENT THESE TWO LINES OUT AGAIN.
    with app.app_context():
        #db.drop_all()
        #db.create_all()
        #print("[INFO] Database tables DROPPED and RECREATED for debugging.")
         pass # Add this line to satisfy the 'with' statement's indentation requirement
    # --- END TEMPORARY DATABASE RESET ---
    app.run(debug=False, host='0.0.0.0') # Changed host to '0.0.0.0'
