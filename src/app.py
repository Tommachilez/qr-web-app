from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime
import os
from google.cloud import storage


# --- GCS CONFIGURATION ---
# Replace these with your actual details!
BUCKET_NAME = "valid-string-backup-bucket"
SERVICE_ACCOUNT_FILE = "service-account.json"

def backup_to_gcs():
    """Uploads the local SQLite DB file to Google Cloud Storage."""
    try:
        # Initialize the client using the key file
        client = storage.Client.from_service_account_json(SERVICE_ACCOUNT_FILE)
        bucket = client.bucket(BUCKET_NAME)
        
        # Create a 'blob' (file object) in GCS
        blob = bucket.blob("backups/qr_data_backup.db")
        
        # Upload the actual file
        blob.upload_from_filename(DB_FILE)
        print(f"☁️ Cloud Backup Successful: {datetime.now()}")
    except Exception as e:
        print(f"❌ Cloud Backup Failed: {e}")


app = Flask(__name__)


# --- DATABASE SETUP ---
DB_FILE = "qr_data.db"


def init_db():
    """Creates the database and table if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qr_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_string TEXT UNIQUE NOT NULL,
            scan_date TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


# Initialize the DB on startup
init_db()


# --- ROUTES ---

@app.route('/')
def index():
    # This serves your HTML file
    return render_template('index.html')


@app.route('/history', methods=['GET'])
def get_history():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # Fetch the 10 most recent scans
        cursor.execute("SELECT qr_string, scan_date FROM qr_records ORDER BY id DESC LIMIT 10")
        rows = cursor.fetchall()
        
        # Format for JSON: [{"string": "ABC...", "date": "..."}, ...]
        history = [{"qr_string": row[0], "scan_date": row[1]} for row in rows]
        return jsonify(history)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/process-qr', methods=['POST'])
def process_qr():
    data = request.json
    qr_string = data.get('qr_string', '').strip()

    # Basic Validation
    if len(qr_string) != 10:
        return jsonify({"status": "error", "message": "String must be 10 characters."}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 1. Look for the existing string
        cursor.execute("SELECT qr_string, scan_date FROM qr_records WHERE qr_string = ?", (qr_string,))
        result = cursor.fetchone() # This returns a tuple like ('ABC1234567', '2026-02-25 14:30:00')

        if result:
            # result[0] is the string, result[1] is the scan_date
            existing_string = result[0]
            first_submitted_time = result[1]

            return jsonify({
                "status": "duplicate", 
                "message": f"String '{existing_string}' already exists!\nFirst submitted on: {first_submitted_time}"
            })

        # 2. Not found! Save it
        scan_date = datetime.now().strftime("%B %d, %Y at %H:%M:%S")
        cursor.execute(
            "INSERT INTO qr_records (qr_string, scan_date) VALUES (?, ?)", 
            (qr_string, scan_date)
        )
        conn.commit()

        backup_to_gcs() # Trigger the sync

        return jsonify({
            "status": "success", 
            "message": "Record saved successfully!"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    # Run locally
    app.run(debug=True, port=5000)
