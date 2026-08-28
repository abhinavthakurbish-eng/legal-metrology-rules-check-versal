"""
api/index.py
-------------
Vercel-compatible version - stateless (koi SQLite, koi disk storage, koi
scan-history/dashboard). OCR cloud API (OCR.space) se hota hai, annotation
aur PDF dono memory mein bante hain, sab kuch EK HI request/response cycle
mein complete ho jaata hai:

  Upload photos -> OCR (cloud) -> Rule check -> HTML report (isi response
  mein) + PDF (base64 data-URI ke roop mein isi HTML mein embed, alag
  request/route ki zaroorat nahi - isliye statelessness koi problem nahi hai)

TRADE-OFFS (Render/Docker version se, jo poori Tesseract + SQLite wali thi):
  - Scan history / dashboard NAHI hai (Vercel mein persistent DB nahi ho sakta
    bina external service jaise Supabase ke)
  - OCR ab cloud API (OCR.space) se hota hai - free tier rate-limited hai
  - CSV audit-trail export nahi hai (history hi nahi hai)
  - Hindi OCR support nahi hai is version mein (OCR.space free tier ka default
    'eng' language use ho raha hai; Hindi chahiye toh OCR.space ka "language"
    parameter badal sakte ho, unki docs check karo)

Agar tumhe SAARI features (history, dashboard, Hindi OCR, audit trail) wapas
chahiye, Render/Docker wala poora version hi sahi rasta hai - yeh Vercel
version ek deliberately simplified fallback hai jab sirf Vercel hi available ho.
"""

import base64
import os
import sys

from flask import Flask, request, render_template_string

# Sab supporting files (engine.py, ocr_cloud.py, annotate_memory.py, pdf_builder.py,
# rules.json) is FILE ke SAME folder (api/) mein hain - isliye simple sibling
# imports use kar rahe hain, koi subdirectory-package import nahi. Vercel ke
# Python runtime mein cross-directory imports kabhi kabhi bundle/resolve nahi
# hote (undocumented edge cases) - sab kuch ek hi folder mein rakhna sabse
# reliable tareeka hai is problem se bachne ka.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ocr_cloud import extract_text_and_boxes_multi
from engine import run_compliance_check, load_rules
from annotate_memory import annotate_image_to_base64
from pdf_builder import build_pdf_report_bytes

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024 * 6  # 6 photos tak, 16MB har ek

MAX_SIDES = 6
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ============================================================
# Inline templates - Vercel par static-file serving ke liye extra
# routing-config chahiye hota hai; CSS/JS ko seedha HTML mein embed karke
# yeh zaroorat hi khatam kar di gayi hai (ek self-contained file).
# ============================================================

BASE_CSS = """
:root { --navy:#1a2b4a; --navy-light:#2d4470; --ink:#1c1f26; --muted:#6b7280;
--border:#e4e6eb; --bg:#fbfbfa; --card:#fff; --good:#1a7f37; --good-bg:#e9f7ef;
--bad:#c1121f; --bad-bg:#fdeceb; --warn:#b45309; --warn-bg:#fef6e7; --radius:10px; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
background:var(--bg); color:var(--ink); line-height:1.55; }
.navbar { background:var(--navy); padding:14px 24px; color:#fff; font-weight:700; font-size:16px; }
.page { max-width:960px; margin:0 auto; padding:32px 20px 60px; }
.eyebrow { text-transform:uppercase; letter-spacing:.06em; font-size:12px; font-weight:700; color:var(--navy-light); }
h1 { color:var(--navy); }
.upload-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:26px; max-width:560px; }
.field-label { display:block; font-size:13px; font-weight:600; color:var(--navy); margin:16px 0 6px; }
input[type=text] { width:100%; padding:11px 13px; border:1px solid var(--border); border-radius:8px; font-size:14.5px; }
.dropzone { border:2px dashed var(--border); border-radius:10px; padding:26px; text-align:center; }
.dropzone-hint { color:var(--muted); font-size:12.5px; }
.btn-primary { margin-top:18px; width:100%; background:var(--navy); color:#fff; border:none; padding:13px 18px;
border-radius:8px; font-size:15px; font-weight:600; cursor:pointer; }
.btn-primary:hover { background:var(--navy-light); }
.btn-secondary { display:inline-block; background:#fff; color:var(--navy); border:1px solid var(--border);
padding:10px 16px; border-radius:8px; font-size:14px; font-weight:600; text-decoration:none; }
.status-badge { padding:8px 16px; border-radius:999px; font-weight:700; font-size:13px; display:inline-block; }
.badge-good { background:var(--good-bg); color:var(--good); }
.badge-bad { background:var(--bad-bg); color:var(--bad); }
.verdict-banner { border-radius:var(--radius); padding:16px 20px; font-size:14.5px; margin:16px 0; }
.verdict-good { background:var(--good-bg); color:#14532d; border:1px solid #bbe8c9; }
.verdict-bad { background:var(--bad-bg); color:#7a1620; border:1px solid #f3c2c6; }
.warning-banner { background:var(--warn-bg); color:var(--warn); border:1px solid #f1d9a8; border-radius:var(--radius); padding:12px 16px; font-size:13px; margin-bottom:16px; }
.score-strip { display:flex; align-items:center; gap:24px; background:var(--card); border:1px solid var(--border);
border-radius:var(--radius); padding:18px 22px; margin:16px 0; flex-wrap:wrap; }
.score-circle { width:66px; height:66px; border-radius:50%; display:flex; align-items:center; justify-content:center;
font-weight:700; font-size:15px; border:4px solid; flex-shrink:0; }
.good { border-color:var(--good); color:var(--good); } .mid { border-color:var(--warn); color:var(--warn); } .bad { border-color:var(--bad); color:var(--bad); }
.report-body { display:grid; grid-template-columns:1fr 1.2fr; gap:18px; margin-top:10px; }
.panel { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:16px; }
.panel h3 { margin-top:0; font-size:14px; color:var(--navy); }
.label-image { width:100%; border-radius:8px; border:1px solid var(--border); margin-bottom:10px; }
.rule-row { border-left:3px solid var(--border); padding:10px 12px; margin-bottom:8px; border-radius:0 6px 6px 0; background:#fafafa; }
.rule-pass { border-left-color:var(--good); } .rule-fail { border-left-color:var(--bad); } .rule-warning { border-left-color:var(--warn); }
.rule-row-top { display:flex; align-items:center; gap:8px; }
.rule-status-icon { width:18px; height:18px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
font-size:11px; font-weight:800; color:#fff; flex-shrink:0; }
.rule-pass .rule-status-icon { background:var(--good); } .rule-fail .rule-status-icon { background:var(--bad); } .rule-warning .rule-status-icon { background:var(--warn); }
.rule-label { font-weight:600; font-size:14px; flex:1; }
.tag-fuzzy { font-size:10px; background:var(--warn); color:#fff; padding:2px 7px; border-radius:5px; }
.rule-reason { font-size:13px; color:var(--muted); margin:6px 0 0; }
.report-actions { display:flex; gap:10px; margin-top:20px; }
@media (max-width:700px) { .report-body { grid-template-columns:1fr; } }
"""

UPLOAD_PAGE = """
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Legal Metrology Checker</title><style>{{ css }}</style></head><body>
<div class="navbar">Legal Metrology Compliance Checker</div>
<div class="page">
  <span class="eyebrow">Legal Metrology (Packaged Commodities) Rules, 2011</span>
  <h1>Scan a label. Know instantly if it complies.</h1>
  <p style="color:var(--muted)">Upload one or more photos of the product (front, back, ingredients panel).</p>
  {% if error %}<div class="warning-banner">⚠️ {{ error }}</div>{% endif %}
  <div class="upload-card">
    <form action="/scan" method="POST" enctype="multipart/form-data">
      <label class="field-label">Product name</label>
      <input type="text" name="product_name" placeholder="e.g. Sunrise Basmati Rice 1kg" required>
      <label class="field-label">Label photos (up to 6)</label>
      <div class="dropzone">
        <input type="file" name="label_images" accept=".png,.jpg,.jpeg,.webp" multiple required>
        <p class="dropzone-hint">Front, back, ingredients panel, MRP sticker - upload as many sides as you have</p>
      </div>
      <button type="submit" class="btn-primary">Run Compliance Check</button>
    </form>
  </div>
  <p style="color:var(--muted); font-size:12.5px; margin-top:24px;">
    Note: this is the Vercel/cloud-OCR build - it does not keep scan history (each scan is a fresh, one-off check).
  </p>
</div>
</body></html>
"""

REPORT_PAGE = """
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Report — {{ product_name }}</title><style>{{ css }}</style></head><body>
<div class="navbar">Legal Metrology Compliance Checker</div>
<div class="page">
  <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
    <div><span class="eyebrow">Compliance Report</span><h1 style="margin:6px 0;">{{ product_name }}</h1></div>
    <div class="status-badge {{ 'badge-good' if compliance.overall_status == 'COMPLIANT' else 'badge-bad' }}">{{ compliance.overall_status }}</div>
  </div>

  <div class="verdict-banner {{ 'verdict-good' if compliance.overall_status == 'COMPLIANT' else 'verdict-bad' }}">
    {% if compliance.overall_status == 'COMPLIANT' %}
      ✅ <strong>Is product ki packaging saari mandatory declarations ke saath compliant dikh rahi hai.</strong>
      {{ compliance.passed }} / {{ compliance.total_rules }} checks pass hui hain.
    {% else %}
      ⚠️ <strong>{{ compliance.failed }} zaroori declaration{{ 's' if compliance.failed != 1 else '' }} missing ya galat format mein hai.</strong>
      Neeche "Failed" rows dekho.
    {% endif %}
  </div>

  {% if ocr_low_confidence %}
  <div class="warning-banner">⚠️ Kuch photos se text padhna mushkil raha (glare/blur/resolution). Neeche FAIL results is wajah se ho sakte hain - behtar photo se dobara try karo.</div>
  {% endif %}

  {% if compliance.fuzzy_matches %}
  <div class="warning-banner" style="background:#eef1f6; color:var(--navy); border-color:var(--border);">
    ℹ️ {{ compliance.fuzzy_matches }} declaration{{ 's' if compliance.fuzzy_matches != 1 else '' }} approximate (fuzzy) match se mili - <span class="tag-fuzzy">verify</span> tag wale rows ko photo se confirm kar lena.
  </div>
  {% endif %}

  <div class="score-strip">
    <div class="score-circle {{ 'good' if compliance.compliance_score >= 80 else ('mid' if compliance.compliance_score >= 50 else 'bad') }}"><span>{{ compliance.compliance_score }}%</span></div>
    <div>{{ compliance.passed }} Passed &nbsp; | &nbsp; {{ compliance.warnings }} Warnings &nbsp; | &nbsp; {{ compliance.failed }} Failed &nbsp; ({{ compliance.total_rules }} rules, {{ images|length }} photo{{ 's' if images|length != 1 else '' }})</div>
    <a href="data:application/pdf;base64,{{ pdf_b64 }}" download="compliance_report.pdf" class="btn-secondary">⬇ Download PDF Report</a>
  </div>

  <div class="report-body">
    <div class="panel">
      <h3>Scanned Label Photos</h3>
      {% for img_b64 in images %}
        <img src="data:image/jpeg;base64,{{ img_b64 }}" class="label-image" alt="Label photo">
      {% endfor %}
    </div>
    <div class="panel">
      <h3>Rule-by-Rule Results</h3>
      {% for r in compliance.results %}
      <div class="rule-row rule-{{ r.status|lower }}">
        <div class="rule-row-top">
          <span class="rule-status-icon">{% if r.status == 'PASS' %}✓{% elif r.status == 'FAIL' %}✕{% else %}!{% endif %}</span>
          <span class="rule-label">{{ r.label }}</span>
          {% if r.matched_via == 'fuzzy' %}<span class="tag-fuzzy">verify</span>{% endif %}
        </div>
        <p class="rule-reason">{{ r.reason }}</p>
        {% if r.extracted_value %}<p class="rule-reason">Extracted: <code>{{ r.extracted_value }}</code></p>{% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="report-actions">
    <a href="/" class="btn-secondary">Scan another product</a>
  </div>
</div>
</body></html>
"""


@app.route("/")
def home():
    return render_template_string(UPLOAD_PAGE, css=BASE_CSS, error=None)


@app.route("/scan", methods=["POST"])
def scan():
    files = [f for f in request.files.getlist("label_images") if f and f.filename]
    product_name = request.form.get("product_name", "").strip() or "Unnamed Product"

    if not files:
        return render_template_string(UPLOAD_PAGE, css=BASE_CSS, error="Kam se kam ek photo upload karo."), 400
    if len(files) > MAX_SIDES:
        return render_template_string(UPLOAD_PAGE, css=BASE_CSS, error=f"Max {MAX_SIDES} photos ek baar mein."), 400
    for f in files:
        if not allowed_file(f.filename):
            return render_template_string(UPLOAD_PAGE, css=BASE_CSS, error=f"Invalid file: {f.filename}"), 400

    # Files ko memory mein read karo (disk par kuch save nahi karna - stateless)
    image_bytes_list = [f.read() for f in files]

    # ---- OCR (cloud API, parallel) ----
    try:
        ocr_result = extract_text_and_boxes_multi(image_bytes_list)
    except Exception as e:
        return render_template_string(UPLOAD_PAGE, css=BASE_CSS, error=f"OCR mein error aayi: {e}"), 500

    # ---- Rule engine ----
    compliance_result = run_compliance_check(ocr_result)

    # ---- Annotated images (in-memory, base64) ----
    annotated_images_b64 = []
    for idx, img_bytes in enumerate(image_bytes_list):
        try:
            b64 = annotate_image_to_base64(img_bytes, compliance_result["results"], image_index=idx)
        except Exception:
            b64 = base64.b64encode(img_bytes).decode("ascii")  # fallback: original hi dikha do
        annotated_images_b64.append(b64)

    # ---- PDF (in-memory, base64 data-URI mein embed) ----
    try:
        pdf_bytes = build_pdf_report_bytes(product_name, annotated_images_b64, compliance_result)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    except Exception:
        pdf_b64 = ""

    return render_template_string(
        REPORT_PAGE, css=BASE_CSS,
        product_name=product_name,
        compliance=compliance_result,
        images=annotated_images_b64,
        pdf_b64=pdf_b64,
        ocr_low_confidence=ocr_result.get("any_low_confidence", False)
    )


@app.route("/rules")
def view_rules():
    rules = load_rules()
    rows = "".join(
        f"<div class='panel' style='margin-bottom:10px;'><b>{r['id']}</b> — {r['label']}<br>"
        f"<span style='color:var(--muted); font-size:13px;'>{r.get('description','')}</span></div>"
        for r in rules
    )
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{BASE_CSS}</style></head>
    <body><div class="navbar">Legal Metrology Compliance Checker</div>
    <div class="page"><h1>Active Compliance Rules</h1>{rows}
    <a href="/" class="btn-secondary">← Back</a></div></body></html>"""
    return html


if __name__ == "__main__":
    app.run(debug=True, port=5000)
