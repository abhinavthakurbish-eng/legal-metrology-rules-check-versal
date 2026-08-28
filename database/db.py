"""
database/db.py
----------------
SQLite database - "repository of scanned products and compliance history"
wala requirement yahin implement hota hai.

Ab ek scan ke saath product ke multiple side-photos (front, back, waghera)
jude ho sakte hain, isliye "image_filename" (single) ki jagah
"image_filenames" (JSON-encoded list) column use ho raha hai.

Hackathon prototype ke liye SQLite use kar rahe hain kyunki:
  - Koi separate server install nahi karna padta (ek hi file hoti hai)
  - Python mein built-in support hai (sqlite3 module)
Production mein isko PostgreSQL/MySQL mein migrate karna easy hai
kyunki hum sirf standard SQL use kar rahe hain.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "compliance.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows ko dict jaisa access karne dega
    return conn


def init_db():
    """App start hote hi ek baar call hota hai - table nahi hai toh bana deta hai."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            image_filenames TEXT NOT NULL,
            full_text TEXT,
            compliance_json TEXT NOT NULL,
            compliance_score REAL NOT NULL,
            overall_status TEXT NOT NULL,
            ocr_low_confidence INTEGER DEFAULT 0,
            scanned_by TEXT DEFAULT 'demo_officer',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Agar koi purana database hai jisme naya column nahi hai, use add kar do
    # taaki app crash na ho.
    existing_cols = [row["name"] for row in conn.execute("PRAGMA table_info(scans)").fetchall()]
    if "ocr_low_confidence" not in existing_cols:
        conn.execute("ALTER TABLE scans ADD COLUMN ocr_low_confidence INTEGER DEFAULT 0")
        conn.commit()

    # Agar koi purana database hai jisme old "image_filename" (single) column
    # tha, use naye format mein migrate kar do taaki app crash na ho.
    existing_cols = [row["name"] for row in conn.execute("PRAGMA table_info(scans)").fetchall()]
    if "image_filename" in existing_cols and "image_filenames" not in existing_cols:
        conn.execute("ALTER TABLE scans ADD COLUMN image_filenames TEXT")
        old_rows = conn.execute("SELECT id, image_filename FROM scans").fetchall()
        for r in old_rows:
            conn.execute(
                "UPDATE scans SET image_filenames = ? WHERE id = ?",
                (json.dumps([r["image_filename"]]), r["id"])
            )
        conn.commit()

    conn.close()


def save_scan(product_name, image_filenames, full_text, compliance_result, ocr_low_confidence=False):
    """
    Ek naya scan record save karta hai.
    image_filenames: list of filenames (product ke ek ya zyada side-photos).
    ocr_low_confidence: True agar OCR ko koi bhi uploaded photo padhne mein
                         dikkat aayi thi (report mein warning dikhane ke liye).
    Returns the new row's id.
    """
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO scans
           (product_name, image_filenames, full_text, compliance_json,
            compliance_score, overall_status, ocr_low_confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            product_name,
            json.dumps(image_filenames),
            full_text,
            json.dumps(compliance_result),
            compliance_result["compliance_score"],
            compliance_result["overall_status"],
            1 if ocr_low_confidence else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_scan_by_id(scan_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    result = dict(row)
    result["compliance_json"] = json.loads(result["compliance_json"])
    result["image_filenames"] = json.loads(result["image_filenames"])
    return result


def get_all_scans(search_query=None, status_filter=None):
    """Dashboard ke liye - search aur filter dono support karta hai."""
    conn = get_connection()
    query = "SELECT id, product_name, image_filenames, compliance_score, overall_status, created_at FROM scans WHERE 1=1"
    params = []

    if search_query:
        query += " AND product_name LIKE ?"
        params.append(f"%{search_query}%")

    if status_filter and status_filter != "all":
        query += " AND overall_status = ?"
        params.append(status_filter)

    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["image_filenames"] = json.loads(d["image_filenames"])
        results.append(d)
    return results


def get_dashboard_stats():
    """Dashboard ke top pe summary cards ke liye (total scans, compliant %, waghera)."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM scans").fetchone()["c"]
    compliant = conn.execute("SELECT COUNT(*) as c FROM scans WHERE overall_status = 'COMPLIANT'").fetchone()["c"]
    non_compliant = total - compliant
    avg_score_row = conn.execute("SELECT AVG(compliance_score) as avg_s FROM scans").fetchone()
    avg_score = round(avg_score_row["avg_s"], 1) if avg_score_row["avg_s"] else 0
    conn.close()
    return {
        "total_scans": total,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "avg_score": avg_score
    }
