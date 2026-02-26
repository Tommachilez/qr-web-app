from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime
import os
from google.cloud import storage


# --- GCS CONFIGURATION ---
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
    """Creates the databases and tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Your original table (UNTOUCHED)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qr_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_string TEXT UNIQUE NOT NULL,
            scan_date TEXT NOT NULL
        )
    ''')

    # NEW: The append-only ghost table!
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS qr_mutations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            action TEXT NOT NULL, 
            new_string TEXT, 
            mutation_date TEXT NOT NULL,
            FOREIGN KEY(record_id) REFERENCES qr_records(id)
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
    conn.row_factory = sqlite3.Row # Lets us access columns by name
    cursor = conn.cursor()

    try:
        # 1. Fetch all records and mutations
        cursor.execute("SELECT * FROM qr_records")
        original_records = cursor.fetchall()

        cursor.execute("SELECT * FROM qr_mutations ORDER BY id ASC")
        mutations = cursor.fetchall()

        # 2. Rebuild the current state in memory
        records_state = {}
        for r in original_records:
            records_state[r['id']] = {
                'id': r['id'],
                'qr_string': r['qr_string'],
                'original_string': r['qr_string'],
                'scan_date': r['scan_date'],
                'status': 'ACTIVE'
            }

        # 3. Fast-forward through history
        for m in mutations:
            rec_id = m['record_id']
            if rec_id in records_state:
                if m['action'] == 'DELETE':
                    records_state[rec_id]['status'] = 'DELETED'
                elif m['action'] == 'EDIT':
                    records_state[rec_id]['status'] = 'EDITED'
                    records_state[rec_id]['qr_string'] = m['new_string']
                elif m['action'] == 'RESTORE':
                    is_edited = records_state[rec_id]['qr_string'] != records_state[rec_id]['original_string']
                    records_state[rec_id]['status'] = 'EDITED' if is_edited else 'ACTIVE'

        # 4. Filter out deleted records and format for the frontend
        active_records = [rec for rec in records_state.values() if rec['status'] != 'DELETED']

        # 5. Sort descending by ID (newest first) and grab the top 10
        active_records.sort(key=lambda x: x['id'], reverse=True)
        top_10 = active_records[:10]

        # Format for JSON exactly how index.html expects it
        history = [{"qr_string": r["qr_string"], "scan_date": r["scan_date"]} for r in top_10]

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
    conn.row_factory = sqlite3.Row # Allows us to access columns by name easily
    cursor = conn.cursor()

    try:
        # 1. Look for the existing string in the original records table
        cursor.execute("SELECT id, qr_string, scan_date FROM qr_records WHERE qr_string = ?", (qr_string,))
        original_result = cursor.fetchone()

        if original_result:
            record_id = original_result['id']
            first_submitted_time = original_result['scan_date']

            # 2. String exists physically! Let's check its "Ghost" state
            cursor.execute("SELECT action, new_string FROM qr_mutations WHERE record_id = ? ORDER BY id ASC", (record_id,))
            mutations = cursor.fetchall()

            status = 'ACTIVE'
            current_string = original_result['qr_string']

            # Fast-forward through this specific record's history
            for m in mutations:
                if m['action'] == 'DELETE':
                    status = 'DELETED'
                elif m['action'] == 'EDIT':
                    status = 'EDITED'
                    current_string = m['new_string']
                elif m['action'] == 'RESTORE':
                    status = 'EDITED' if current_string != original_result['qr_string'] else 'ACTIVE'

            # 3. Return the smart messages based on the final state
            if status == 'DELETED':
                return jsonify({
                    "status": "duplicate", 
                    "message": f"This string was previously scanned on {first_submitted_time}, but it has been deleted by an admin!"
                })
            elif status == 'EDITED' and current_string != qr_string:
                return jsonify({
                    "status": "duplicate", 
                    "message": f"This string is tied to an older record from {first_submitted_time} that an admin has since altered."
                })
            else:
                return jsonify({
                    "status": "duplicate", 
                    "message": f"String '{qr_string}' already exists!\nFirst submitted on: {first_submitted_time}"
                })

        # 4. Not found in the database at all! Safe to save.
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


@app.route('/admin')
def admin_page():
    """Serves the new Admin HTML page."""
    return render_template('admin.html')


@app.route('/admin/api/records', methods=['GET'])
def get_admin_records():
    """Fetches records, applies mutations in memory, and handles search."""
    search_query = request.args.get('search', '').strip().upper()

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Lets us access columns by name
    cursor = conn.cursor()

    try:
        # 1. Fetch all original records
        cursor.execute("SELECT * FROM qr_records ORDER BY id DESC")
        original_records = cursor.fetchall()

        # 2. Fetch all mutations in chronological order
        cursor.execute("SELECT * FROM qr_mutations ORDER BY id ASC")
        mutations = cursor.fetchall()

        # 3. Apply the 'ghost' state in Python memory!
        records_state = {}
        for r in original_records:
            records_state[r['id']] = {
                'id': r['id'],
                'qr_string': r['qr_string'],
                'original_string': r['qr_string'], # Keep track of the original
                'original_date': r['scan_date'],
                'status': 'ACTIVE'
            }

        # Fast-forward through history
        for m in mutations:
            rec_id = m['record_id']
            if rec_id in records_state:
                if m['action'] == 'DELETE':
                    records_state[rec_id]['status'] = 'DELETED'
                elif m['action'] == 'EDIT':
                    records_state[rec_id]['status'] = 'EDITED'
                    records_state[rec_id]['qr_string'] = m['new_string']
                elif m['action'] == 'RESTORE':
                    # If restored, check if the string matches the original
                    is_edited = records_state[rec_id]['qr_string'] != records_state[rec_id]['original_string']
                    records_state[rec_id]['status'] = 'EDITED' if is_edited else 'ACTIVE'
        
        # 4. Filter by the Search Query
        final_results = []
        for rec in records_state.values():
            if search_query and search_query not in rec['qr_string']:
                continue
            final_results.append(rec)

        # Re-sort descending by ID so newest is top
        final_results.sort(key=lambda x: x['id'], reverse=True)

        return jsonify(final_results)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/admin/api/mutate', methods=['POST'])
def mutate_record():
    """Appends a new action to the ghost table (NO UPDATES/DELETES)."""
    data = request.json
    record_id = data.get('record_id')
    action = data.get('action') # 'EDIT', 'DELETE', or 'RESTORE'
    new_string = data.get('new_string')

    if not record_id or action not in ['EDIT', 'DELETE', 'RESTORE']:
        return jsonify({"status": "error", "message": "Invalid data."}), 400

    mutation_date = datetime.now().strftime("%B %d, %Y at %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        # We exclusively INSERT. Original data remains pristine!
        cursor.execute(
            "INSERT INTO qr_mutations (record_id, action, new_string, mutation_date) VALUES (?, ?, ?, ?)",
            (record_id, action, new_string, mutation_date)
        )
        conn.commit()

        # Trigger your existing GCS Backup!
        backup_to_gcs()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


if __name__ == '__main__':
    # Run locally
    app.run(debug=True, port=5000)
