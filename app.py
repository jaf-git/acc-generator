import os
import io
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from flask import Flask, request, jsonify
from pypdf import PdfReader, PdfWriter

# =========================================================
# 1. APPLICATION SETUP & CONFIGURATION
# =========================================================
app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_FILE = BASE_DIR / "acc.pdf"

# Secure Email Configuration using Environment Variables
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
    logger.critical("CRITICAL ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD environment variables are missing!")
    logger.critical("You must add these in the Render Dashboard -> Environment variables.")


# =========================================================
# 2. CORE PDF GENERATION LOGIC
# =========================================================
def fill_pdf_in_memory(template_path, data_dict):
    logger.info("Opening PDF template...")
    reader = PdfReader(template_path)
    writer = PdfWriter()
    
    writer.append(reader)

    for page in writer.pages:
        writer.update_page_form_field_values(
            page, 
            data_dict, 
            auto_regenerate=False, 
            flatten=True
        )

    try:
        writer.remove_annotations(subtypes="/Widget")
    except AttributeError:
        pass 

    output_stream = io.BytesIO()
    writer.write(output_stream)
    output_stream.seek(0)
    
    return output_stream


# =========================================================
# 3. CORE EMAIL LOGIC
# =========================================================
def send_acceptance_email(pdf_stream, recipient_email, first_name):
    logger.info(f"Drafting email for {recipient_email}...")
    
    msg = EmailMessage()
    msg['Subject'] = 'Your Acceptance Letter'
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = recipient_email
    
    email_body = f"""Hello {first_name},

Congratulations! Please find your official acceptance letter attached to this email.

Best regards,
The Admissions Team
"""
    msg.set_content(email_body)

    msg.add_attachment(
        pdf_stream.read(),
        maintype='application',
        subtype='pdf',
        filename=f"Acceptance_Letter_{first_name}.pdf"
    )

    logger.info("Connecting to SMTP server...")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls() 
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        
    logger.info("Email successfully dispatched!")


# =========================================================
# 4. THE WEBHOOK ENDPOINT
# =========================================================
@app.route('/webhook/fluent-forms', methods=['POST'])
def handle_fluent_forms():
    try:
        payload = request.json
        if not payload:
            logger.error("Request received but no JSON payload was found.")
            return jsonify({"error": "Invalid or missing data"}), 400
        
        logger.info("Webhook triggered! Extracting data...")

        # ---------------------------------------------------------
        # NEW DEBUG BLOCK: Print the exact data from WordPress
        # ---------------------------------------------------------
        logger.info("========== RAW INCOMING DATA FROM FLUENT FORMS ==========")
        logger.info(payload)
        logger.info("=========================================================")
        # ---------------------------------------------------------

        first_name = payload.get("first_name", "Student").strip().upper()
        surname = payload.get("surname", "").strip().upper()
        user_email = payload.get("email", "").strip()

        if not user_email:
            logger.error("Execution stopped: No email address provided in the form submission.")
            return jsonify({"error": "Email address is required"}), 400

        pdf_data = {
            "first name": first_name, 
            "surname": surname        
        }

        pdf_stream = fill_pdf_in_memory(TEMPLATE_FILE, pdf_data)

        send_acceptance_email(pdf_stream, user_email, first_name)

        return jsonify({
            "status": "success", 
            "message": f"Letter generated and emailed to {user_email}"
        }), 200

    except smtplib.SMTPAuthenticationError:
        logger.error("Email failed: Incorrect email or App Password.")
        return jsonify({"error": "SMTP Authentication failed. Check your App Password."}), 500
        
    except Exception as e:
        logger.error(f"Critical System Error: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
