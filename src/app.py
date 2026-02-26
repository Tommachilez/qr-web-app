from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime
import math
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

    if len(qr_string) != 10:
        return jsonify({"status": "error", "message": "String must be 10 characters."}), 400

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Fetch all data to build the TRUE logical state (including all mutations)
        cursor.execute("SELECT * FROM qr_records")
        original_records = cursor.fetchall()

        cursor.execute("SELECT * FROM qr_mutations ORDER BY id ASC")
        mutations = cursor.fetchall()

        records_state = {}
        for r in original_records:
            records_state[r['id']] = {
                'id': r['id'],
                'qr_string': r['qr_string'],
                'original_string': r['qr_string'],
                'scan_date': r['scan_date'],
                'status': 'ACTIVE'
            }

        # Fast-forward through the ghost timeline
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

        # Check if the submitted EXACT string currently exists ANYWHERE in the logical state
        for rec in records_state.values():
            # Exact match (case-sensitive)
            if rec['qr_string'] == qr_string:
                if rec['status'] == 'DELETED':
                    return jsonify({
                        "status": "duplicate", 
                        "message": f"This exact string was previously scanned on {rec['scan_date']}, but it has been deleted by an admin!"
                    })
                elif rec['status'] == 'EDITED' and rec['qr_string'] != rec['original_string']:
                    return jsonify({
                        "status": "duplicate", 
                        "message": f"This exact string is tied to an older record from {rec['scan_date']} that an admin has since altered."
                    })
                else:
                    return jsonify({
                        "status": "duplicate", 
                        "message": f"String '{qr_string}' already exists!\nFirst submitted on: {rec['scan_date']}"
                    })

        # If we made it here, the string is completely new (or a different case) and safe to save!
        scan_date = datetime.now().strftime("%B %d, %Y at %H:%M:%S")
        cursor.execute(
            "INSERT INTO qr_records (qr_string, scan_date) VALUES (?, ?)", 
            (qr_string, scan_date)
        )
        conn.commit()

        backup_to_gcs() # Trigger cloud backup

        return jsonify({
            "status": "success", 
            "message": "Record saved successfully!"
        })

    except sqlite3.IntegrityError:
        # Catches the rare edge case where a string is physically stuck in the original DB
        return jsonify({
            "status": "error",
            "message": "This exact string is locked in the database history. Please restore it via the Admin panel."
        }), 400
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
    search_query = request.args.get('search', '').strip()
    # NEW: Grab the requested page number, default to 1
    page = int(request.args.get('page', 1))
    per_page = 20 

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM qr_records ORDER BY id DESC")
        original_records = cursor.fetchall()

        cursor.execute("SELECT * FROM qr_mutations ORDER BY id ASC")
        mutations = cursor.fetchall()

        records_state = {}
        for r in original_records:
            records_state[r['id']] = {
                'id': r['id'],
                'qr_string': r['qr_string'],
                'original_string': r['qr_string'],
                'original_date': r['scan_date'],
                'status': 'ACTIVE'
            }

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
        final_results = []
        for rec in records_state.values():
            if search_query and search_query not in rec['qr_string']:
                continue
            final_results.append(rec)

        final_results.sort(key=lambda x: x['id'], reverse=True)

        # --- NEW: PAGINATION MATH ---
        total_records = len(final_results)
        total_pages = math.ceil(total_records / per_page)
        if total_pages == 0: total_pages = 1 # Always show at least 1 page

        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_results = final_results[start_idx:end_idx]

        # Send back a rich package containing the records AND the page info!
        return jsonify({
            "records": paginated_results,
            "current_page": page,
            "total_pages": total_pages,
            "total_records": total_records
        })

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
