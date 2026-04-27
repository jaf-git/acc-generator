import os
import io
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

# Flask is our web framework that listens for incoming web requests
from flask import Flask, request, jsonify

# pypdf handles the reading and writing of the PDF fields
from pypdf import PdfReader, PdfWriter

# =========================================================
# 1. APPLICATION SETUP & CONFIGURATION
# =========================================================

# Initialize the Flask application
app = Flask(__name__)

# Set up logging so we can track errors and successes in the server console
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

# Define exactly where our PDF template lives. 
# BASE_DIR ensures we look in the exact folder where this script is located.
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_FILE = BASE_DIR / "ACCEPTEANCE LETTER FORM_2.pdf"

# Secure Email Configuration using Environment Variables
# NEVER hardcode your password here. PythonAnywhere's WSGI file will inject these.
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")


# =========================================================
# 2. CORE PDF GENERATION LOGIC
# =========================================================

def fill_pdf_in_memory(template_path, data_dict):
    """
    Takes the template and the Fluent Forms data, fills the fields, 
    flattens it (makes it uneditable), and returns the file inside server RAM.
    """
    logger.info("Opening PDF template...")
    reader = PdfReader(template_path)
    writer = PdfWriter()
    
    # Copy all pages from the template to our new writer object
    writer.append(reader)

    # Loop through the pages and inject the data matching the PDF field names
    for page in writer.pages:
        writer.update_page_form_field_values(
            page, 
            data_dict, 
            auto_regenerate=False, 
            flatten=True # Flatten=True locks the text so users cannot edit the final PDF
        )

    # Clean up the leftover interactive widget boxes since we flattened the text
    try:
        writer.remove_annotations(subtypes="/Widget")
    except AttributeError:
        pass # If the version of pypdf doesn't support this, just skip it safely

    # Create an in-memory byte stream (a virtual file) to hold the new PDF
    output_stream = io.BytesIO()
    writer.write(output_stream)
    
    # Rewind the stream back to the beginning so it's ready to be read by the emailer
    output_stream.seek(0)
    
    return output_stream


# =========================================================
# 3. CORE EMAIL LOGIC
# =========================================================

def send_acceptance_email(pdf_stream, recipient_email, first_name):
    """
    Takes the in-memory PDF, attaches it to an email, and sends it via Gmail.
    """
    logger.info(f"Drafting email for {recipient_email}...")
    
    # Build the email headers and body
    msg = EmailMessage()
    msg['Subject'] = 'Your Acceptance Letter'
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = recipient_email
    
    # The actual text inside the email
    email_body = f"""Hello {first_name},

Congratulations! Please find your official acceptance letter attached to this email.

Best regards,
The Admissions Team
"""
    msg.set_content(email_body)

    # Attach the virtual PDF file we created in the previous step
    msg.add_attachment(
        pdf_stream.read(),
        maintype='application',
        subtype='pdf',
        filename=f"Acceptance_Letter_{first_name}.pdf"
    )

    # Connect to Gmail's server and dispatch the email securely
    logger.info("Connecting to SMTP server...")
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls() # Encrypt the connection
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        
    logger.info("Email successfully dispatched!")


# =========================================================
# 4. THE WEBHOOK ENDPOINT (THE API LISTENER)
# =========================================================

# This tells Flask to listen at a specific URL for POST requests from WordPress
@app.route('/webhook/fluent-forms', methods=['POST'])
def handle_fluent_forms():
    try:
        # Step A: Catch the JSON data sent by Fluent Forms
        payload = request.json
        if not payload:
            logger.error("Request received but no JSON payload was found.")
            return jsonify({"error": "Invalid or missing data"}), 400
        
        logger.info("Webhook triggered! Extracting data...")

        # Step B: Extract the specific fields. 
        # The text inside the quotes ("first_name") MUST match your Fluent Forms Name Attributes.
        # We use .upper() to ensure the PDF looks professional and uniform.
        first_name = payload.get("first_name", "Student").strip().upper()
        surname = payload.get("surname", "").strip().upper()
        user_email = payload.get("email", "").strip()

        # Step C: Validation to ensure we have somewhere to send the email
        if not user_email:
            logger.error("Execution stopped: No email address provided in the form submission.")
            return jsonify({"error": "Email address is required"}), 400

        # Step D: Map the extracted data to the exact Field Names inside your PDF template
        pdf_data = {
            "first name": first_name, # "first name" is the field name inside your PDF
            "surname": surname        # "surname" is the field name inside your PDF
        }

        # Step E: Trigger the PDF Generation
        pdf_stream = fill_pdf_in_memory(TEMPLATE_FILE, pdf_data)

        # Step F: Trigger the Email Dispatcher
        send_acceptance_email(pdf_stream, user_email, first_name)

        # Step G: Send a success signal back to WordPress
        return jsonify({
            "status": "success", 
            "message": f"Letter generated and emailed to {user_email}"
        }), 200

    except smtplib.SMTPAuthenticationError:
        logger.error("Email failed: Incorrect email or App Password.")
        return jsonify({"error": "SMTP Authentication failed"}), 500
        
    except Exception as e:
        # If anything unexpectedly crashes, log it and tell WordPress it failed
        logger.error(f"Critical System Error: {e}")
        return jsonify({"error": "Internal server error"}), 500

# This allows you to run the app locally for testing if needed
if __name__ == "__main__":
    app.run(debug=True, port=5000)