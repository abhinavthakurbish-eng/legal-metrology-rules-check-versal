"""
app.py
-------
Yeh poore system ka entry point hai. Isko chalane ke liye:
    python3 app.py
phir browser mein: http://localhost:5000

Flow (yeh dhyaan se padhna, poori pipeline yahin connect hoti hai):
  1. User "/" pe product ke ek ya zyada side-photos upload karta hai
     (front, back, ingredients label, MRP sticker, waghera)
  2. "/scan" route saari images ko save karta hai, phir teen steps chalata hai:
       a) ocr/extractor.py       -> har image se text + bounding boxes nikaalta hai
                                     aur ek combined result banata hai
       b) rules_engine/engine.py -> har rule check karta hai (saari photos ke
                                     combined text/words ke against)
       c) database/db.py         -> result ko SQLite mein save karta hai
  3. User ko "/report/<id>" pe redirect kiya jaata hai jahan result dikhta hai
     (saari uploaded photos annotated boxes ke saath dikhti hain)
  4. "/report/<id>/pdf" se PDF download ho sakta hai
  5. "/dashboard" pe saare past scans dikhte hain (search/filter ke saath)
"""

import os
import uuid
import time
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, Response

from ocr.extractor import extract_text_and_boxes_multi
from rules_engine.engine import run_compliance_check
from reports.generator import generate_pdf_report
from reports.annotate import create_annotated_image
from database import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
REPORTS_FOLDER = os.path.join(BASE_DIR, "generated_reports")
ANNOTATED_FOLDER = os.path.join(BASE_DIR, "static", "annotated")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORTS_FOLDER, exist_ok=True)
os.makedirs(ANNOTATED_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_SIDES = 6  # ek product ki max itni side-photos ek saath accept karenge

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024 * MAX_SIDES  # sabhi files milaake max size

# App start hote hi database table taiyar kar do (agar pehle se nahi hai toh)
db.init_db()


# ============================================================
# GLOBAL REQUEST TIMING - har single request (scan, report page,
# image load, sab) ka time terminal mein print karta hai. Agar
# kahin bhi slowness hai, yeh EXACTLY dikha dega kaunsa URL slow hai -
# guesswork khatam.
# ============================================================
@app.before_request
def _log_request_start():
    request._start_time = time.time()


@app.after_request
def _log_request_end(response):
    duration = time.time() - getattr(request, "_start_time", time.time())
    print(f"[REQUEST] {request.method} {request.path} -> {response.status_code} | {round(duration, 2)}s")
    return response


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def home():
    """Upload page - system ka landing page."""
    stats = db.get_dashboard_stats()
    return render_template("upload.html", stats=stats)


@app.route("/scan", methods=["POST"])
def scan():
    """
    Yahan poori pipeline chalti hai jab user ek ya zyada label photos submit karta hai.

    TIMING LOGS: Har major step ka time terminal mein print hota hai (jahan
    'python3 app.py' chal raha hai). Agar scan slow lage, terminal check karo -
    exactly pata chal jaayega kaun sa step (OCR / rules / annotation) slow hai,
    guesswork nahi karna padega.
    """
    scan_start_time = time.time()

    # "label_images" naam se multiple files aate hain (upload.html mein
    # <input type="file" name="label_images" multiple> use hota hai)
    files = [f for f in request.files.getlist("label_images") if f and f.filename]
    product_name = request.form.get("product_name", "").strip() or "Unnamed Product"

    if not files:
        return "Koi image upload nahi hui. Product ki kam se kam ek photo chahiye.", 400

    if len(files) > MAX_SIDES:
        return f"Ek baar mein max {MAX_SIDES} photos upload kar sakte ho.", 400

    for f in files:
        if not allowed_file(f.filename):
            return f"Invalid file: {f.filename}. Sirf PNG/JPG/JPEG/WEBP allowed hai.", 400

    # Har uploaded side-photo ko unique filename ke saath save karo
    # (taaki do users ki files overwrite na ho, aur front/back/side sab alag rahein)
    unique_filenames = []
    image_paths = []
    for f in files:
        ext = f.filename.rsplit(".", 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{ext}"
        image_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        f.save(image_path)
        unique_filenames.append(unique_filename)
        image_paths.append(image_path)
    print(f"[TIMING] {len(files)} file(s) saved to disk: {round(time.time() - scan_start_time, 2)}s")

    # ---- STEP A: OCR (saari side-photos ek saath process, combined result) ----
    t_ocr = time.time()
    try:
        ocr_result = extract_text_and_boxes_multi(image_paths)
    except Exception as e:
        return f"OCR processing mein error aayi: {str(e)}", 500
    print(f"[TIMING] OCR (extract_text_and_boxes_multi): {round(time.time() - t_ocr, 2)}s")

    # ---- STEP B: Rule engine (combined text/words ke against har rule check) ----
    t_rules = time.time()
    compliance_result = run_compliance_check(ocr_result)
    print(f"[TIMING] Rule matching: {round(time.time() - t_rules, 2)}s")

    # ---- STEP C: Save to database ----
    t_db = time.time()
    scan_id = db.save_scan(
        product_name=product_name,
        image_filenames=unique_filenames,
        full_text=ocr_result["full_text"],
        compliance_result=compliance_result,
        ocr_low_confidence=ocr_result.get("any_low_confidence", False)
    )
    print(f"[TIMING] Database save: {round(time.time() - t_db, 2)}s")

    # ---- STEP D: Har side-photo ke liye display-ready image banao (green/red boxes
    # + resize, taaki report page pe fast load ho - poori camera-resolution
    # image seedha browser ko bhejna page ko bahut slow kar deta hai) ----
    t_annotate = time.time()
    for idx, unique_filename in enumerate(unique_filenames):
        annotated_filename = f"annotated_{unique_filename}"
        annotated_path = os.path.join(ANNOTATED_FOLDER, annotated_filename)
        try:
            create_annotated_image(
                image_paths[idx], compliance_result["results"], annotated_path, image_index=idx
            )
        except Exception:
            # Annotate/resize genuinely fail ho jaaye (bahut rare), tab bhi
            # kam se kam ek resized display copy bana do taaki page slow na ho -
            # sirf original ko as-is copy mat karo.
            try:
                from PIL import Image
                img = Image.open(image_paths[idx]).convert("RGB")
                if max(img.size) > 1400:
                    scale = 1400 / max(img.size)
                    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
                img.save(annotated_path, quality=82, optimize=True)
            except Exception:
                pass  # genuinely kuch nahi ho saka - fallback original hi dikhega
    print(f"[TIMING] Annotation + resize ({len(unique_filenames)} image(s)): {round(time.time() - t_annotate, 2)}s")
    print(f"[TIMING] TOTAL scan time: {round(time.time() - scan_start_time, 2)}s")
    print("-" * 50)

    return redirect(url_for("view_report", scan_id=scan_id))


@app.route("/report/<int:scan_id>")
def view_report(scan_id):
    """Ek specific scan ka detailed report page dikhata hai - saari uploaded photos ke saath."""
    scan = db.get_scan_by_id(scan_id)
    if scan is None:
        return "Scan nahi mila", 404

    # Har uploaded side-photo ke liye decide karo: annotated version dikhayein ya original
    images = []
    for idx, filename in enumerate(scan["image_filenames"]):
        annotated_filename = f"annotated_{filename}"
        annotated_exists = os.path.exists(os.path.join(ANNOTATED_FOLDER, annotated_filename))
        images.append({
            "side_num": idx + 1,
            "filename": annotated_filename if annotated_exists else filename,
            "annotated": annotated_exists
        })

    ocr_low_confidence = bool(scan.get("ocr_low_confidence", 0))

    return render_template(
        "report.html",
        scan=scan,
        compliance=scan["compliance_json"],
        images=images,
        ocr_low_confidence=ocr_low_confidence
    )


@app.route("/report/<int:scan_id>/pdf")
def download_pdf(scan_id):
    """PDF report generate karke download karwata hai (saari side-photos ke saath)."""
    scan = db.get_scan_by_id(scan_id)
    if scan is None:
        return "Scan nahi mila", 404

    image_paths = [os.path.join(UPLOAD_FOLDER, fname) for fname in scan["image_filenames"]]
    pdf_filename = f"compliance_report_{scan_id}.pdf"
    pdf_path = os.path.join(REPORTS_FOLDER, pdf_filename)

    generate_pdf_report(
        scan_id=scan_id,
        product_name=scan["product_name"],
        image_paths=image_paths,
        compliance_result=scan["compliance_json"],
        output_path=pdf_path
    )

    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)


@app.route("/dashboard")
def dashboard():
    """Saare past scans - search aur status filter ke saath."""
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all")

    scans = db.get_all_scans(search_query=search_query, status_filter=status_filter)
    stats = db.get_dashboard_stats()

    return render_template(
        "dashboard.html",
        scans=scans,
        stats=stats,
        search_query=search_query,
        status_filter=status_filter
    )


@app.route("/dashboard/export.csv")
def export_audit_trail():
    """
    Saare scans ki audit-trail CSV export - officers/supervisors ke liye
    ek downloadable record jo unke reporting/record-keeping mein use ho sake
    (existing artwork-compliance tools yeh "audit report" export dete hain,
    isliye yahan bhi add kiya gaya hai).
    """
    import csv
    import io

    scans = db.get_all_scans()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Report ID", "Product Name", "Compliance Score (%)", "Overall Status", "Scanned On"])
    for s in scans:
        writer.writerow([
            f"SCAN-{s['id']:05d}",
            s["product_name"],
            s["compliance_score"],
            s["overall_status"],
            s["created_at"]
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=compliance_audit_trail.csv"}
    )


@app.route("/rules")
def view_rules():
    """
    Bonus page - saare active compliance rules dikhata hai.
    Demo mein yeh dikhana achha lagta hai: 'humara rule engine config-driven hai'.
    """
    from rules_engine.engine import load_rules
    rules = load_rules()
    return render_template("rules.html", rules=rules)


# Uploaded aur annotated images ko serve karne ke liye
@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_file(os.path.join(UPLOAD_FOLDER, filename))


if __name__ == "__main__":
    print("=" * 60)
    print("Legal Metrology Compliance Checker - Prototype")
    print("Browser mein kholo: http://localhost:5000")
    print("[TIMING]/[REQUEST] lines yahan dikhengi - agar kuch slow lage,")
    print("in lines ko copy karke share karo, exact wajah pata chal jaayegi.")
    print("=" * 60)
    # Local development ke liye. Production mein (Render/Railway/Docker)
    # gunicorn is file ko import karke seedha "app" object use karta hai
    # (Dockerfile mein CMD dekho), yeh block tab nahi chalta.
    # use_reloader=False: Flask ka default auto-reloader background mein
    # files watch karta hai aur kabhi kabhi (khaaskar Windows pe, ya jab
    # uploads/ folder mein bahut saari files ho jaayein) extra overhead
    # ya unexpected restarts create kar sakta hai. Development mein code
    # change karne ke baad bas Ctrl+C karke `python3 app.py` dobara chalao.
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port, threaded=True, use_reloader=False)
