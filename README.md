# QR Registry Web App 🛡️

A QR code registration system built with **Flask** and **Tailwind CSS**. Designed for reliability in the field, featuring offline support and a transparent audit trail.

## 🚀 Features

- **Smart Scanning**: Scan QR codes directly using your camera or upload a photo from your gallery.

- **Offline First**: If the internet drops out, the app saves scans to local storage and syncs them automatically when you're back online.

- **Append-Only Logic**: Records are never truly deleted or overwritten. "Edits" and "Deletions" are stored as "ghost mutations," preserving a full historical audit trail.

- **Cloud-Synced**: Automatically backs up your SQLite database to Google Cloud Storage after every change.

- **Admin Dashboard**: Search, edit, and restore records with built-in pagination.

## 🛠️ Tech Stack

- **Backend**: Python (Flask)

- **Frontend**: Tailwind CSS, Html5-Qrcode

- **Database**: SQLite (with a mutation-based architecture)

- **Infrastructure**: Docker, Google Cloud Run, Google Cloud Storage

## 📦 Local Setup

1. **Clone the repo:**

```bash
git clone https://github.com/Tommachilez/qr-web-app.git
cd qr-web-app
```

2. **Install dependencies:**

```bash
pip install -r requirements.txt
```

3. **Environment Setup:**

Ensure you have a service account for Google Cloud access (or comment out the GCS functions in app.py for local-only testing).

4. **Run the app:**

```bash
python src/app.py
```

## 🧹 Maintenance

The project includes a special `db_cleanup.py` script. This "Ultimate Janitor" resolves logical collisions and sweeps away redundant mutation logs while maintaining a safety backup.