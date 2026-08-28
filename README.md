# Legal Metrology Label Compliance Checker

Prototype system for **PS ID 26034 (Ministry of Consumer Affairs)** — automated
checking of packaged-commodity labels against the **Legal Metrology (Packaged
Commodities) Rules, 2011**, using OCR + a configurable, research-informed rule
engine.

Upload one or more photos of a product's different sides (front, back,
ingredients panel, MRP sticker) and the system:

1. Extracts text from every photo (OCR, with automatic orientation
   correction, adaptive preprocessing for glossy/busy packaging, and a hard
   timeout so a single bad photo can't stall the whole scan)
2. Combines the text across all photos and pulls out mandatory declarations
   (MRP, net quantity, mfg date, manufacturer address, etc.) — using an
   **exact match first, fuzzy match as fallback** strategy that tolerates
   minor OCR misreads (see "Research basis" below)
3. Checks each declaration against `rules_engine/rules.json`
4. Shows a plain-language compliance report with annotated photos, and a
   downloadable PDF formatted like a field inspection report

## Setup

```bash
# 1. System dependency: Tesseract OCR
sudo apt-get install tesseract-ocr        # Debian/Ubuntu
# brew install tesseract                  # macOS

# 2. Python dependencies
pip install -r requirements.txt

# 3. Run
python3 app.py
```

Then open **http://localhost:5000**.

## Deploying online (Render.com — recommended)

**Do not deploy this to Vercel.** Vercel's Python runtime is serverless and
stateless: it has no system-level Tesseract binary, and SQLite / uploaded
photos need a writable, persistent-during-runtime filesystem, which
serverless functions don't provide. No amount of code change fixes this —
it's a platform mismatch, not a bug.

**Render.com** runs this as a normal long-lived web service (not a
serverless function), so Tesseract and file storage both work as expected.
It has a free tier and a `render.yaml` (Docker-based) is already included.

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New +** → **Web Service** →
   connect your GitHub repo
3. Render auto-detects `render.yaml` / the `Dockerfile` — leave the defaults
   ("Docker" environment) and click **Create Web Service**. Do **not** switch
   it to a native "Python 3" environment — that skips the Dockerfile and
   `apt-get` won't be available to install Tesseract.
4. Wait for the build (~2-3 min the first time), then open the given
   `*.onrender.com` URL

**Notes on the free tier:**
- Disk is not persistent across redeploys/restarts — scan history, uploaded
  photos, and generated PDFs reset each time the service restarts. Fine for
  a hackathon demo; for real persistence, attach a Render Disk (paid) or move
  to Postgres + object storage.
- The service **sleeps after 15 minutes of inactivity**. The first request
  after sleeping can take 30-50 seconds just to wake up — that's Render's
  free-tier policy, not a bug in this app. Open the site a couple of minutes
  before a demo/judging session to "warm it up".

## How this differs from existing label-compliance tools

A competitive review of existing Indian packaged-commodity compliance tools
(PackCheck, Product Label Guru, ManageArtworks/ComplAi, Artwork Flow, and the
official LMPC registration portal) surfaced several recurring gaps that this
prototype specifically targets:

| Gap in existing tools | This prototype |
|---|---|
| Most are **artwork-first** — they expect a print-ready PDF, not a photo of a physical product on a shelf | **Product-first**: built around a field officer photographing an actual package, including multiple sides in one scan |
| No stated support for **Hindi/regional-language** labels | OCR runs in **English + Hindi combined** (`eng+hin`), since many Indian labels carry bilingual declarations |
| Rule coverage is generally uniform, without accounting for **category-specific conditions** (e.g. imported-product-only requirements) | The rule engine supports **conditional requirements** — e.g. Country of Origin is only mandatory when the label indicates the product is imported, and the engine detects that automatically |
| "Pass" results are often presented without distinguishing confident vs. uncertain reads, risking silent over-trust | Every OCR read tracks a confidence score, and every fuzzy-matched field is explicitly flagged **`[Verify]`** for manual confirmation rather than presented as certain |
| No mention of an exportable **audit trail** for enforcement record-keeping | Dashboard includes a **CSV audit-trail export** of all past scans |

This is still a prototype, not a finished product — it does not yet handle
curved-bottle perspective correction, barcode/product-database matching, or
offline mobile capture, which are genuine open problems even for the
commercial tools reviewed above.

## Research basis for key design decisions

This prototype's design was informed by reviewing recent literature on
OCR-based label/document extraction, and 3 concrete limitations were
identified and addressed:

| # | Limitation found in literature | How it's addressed here |
|---|---|---|
| 1 | Rule-based/regex OCR-text matching is brittle to real-world OCR noise (typos, merged words, misread characters) — noted as a core limitation of conventional OCR pipelines in *"Information Extraction from Product Labels: A Machine Vision Approach"* (IJAIA, 2024) | `rules_engine/engine.py` tries a strict regex first, then falls back to **fuzzy keyword-anchor matching** (`difflib.SequenceMatcher`, similar to the approach in Hamdi et al.'s OCR post-correction work and the "iOCR" ballot-recognition paper) before finally accepting a field as missing. Fuzzy matches are labelled `[Verify]` in the report/PDF rather than treated as identical to an exact match. |
| 2 | OCR accuracy degrades sharply on busy backgrounds, glossy packaging, and varying fonts, requiring adaptive/multi-strategy preprocessing (CRNN OCR paper, IEEE 2023; automotive-parts OCR study, Springer 2024/25) | `ocr/extractor.py` tries multiple thresholding strategies (Otsu, adaptive, CLAHE) per photo and keeps whichever gives the highest Tesseract confidence, escalating only when needed (for speed). |
| 3 | Systems that don't quantify OCR/match confidence risk silently trusting bad reads — addressed via confidence-threshold-based rejection in *"Product verification using OCR classification and Mondrian conformal prediction"* (2021) | Each photo's OCR confidence is tracked; a **low-confidence warning banner** appears on the report when a photo was hard to read, and every fuzzy-matched field is flagged for manual verification rather than presented as a certain result. |

## Project structure

```
app.py                     Flask entry point — wires OCR, rules, DB, reports together
ocr/extractor.py           Image → text + word bounding boxes (OpenCV + Tesseract),
                            multi-strategy preprocessing, timeout-protected
rules_engine/
  engine.py                 Exact-then-fuzzy rule matching against the OCR result
  rules.json                Declarative list of Legal Metrology rules
database/db.py             SQLite persistence for scan history
reports/
  annotate.py                Draws pass/fail boxes on the original photos
  generator.py                Builds the downloadable PDF (officer inspection-report format)
templates/                 Jinja2 HTML pages (upload, report, dashboard, rules)
static/                    CSS, JS, and generated annotated images
uploads/                   Uploaded photos are saved here (gitignored)
generated_reports/         Generated PDFs are saved here (gitignored)
```

## Language support

OCR runs with both English and Hindi (`eng+hin`) trained data simultaneously,
since Indian packaging is frequently bilingual. If the Hindi language pack is
ever missing from the deployment environment for any reason, the system
automatically falls back to English-only OCR rather than failing the scan —
see `_run_tesseract()` in `ocr/extractor.py`. The `Dockerfile` installs the
Hindi pack (`tesseract-ocr-hin`) by default.

## Notes on OCR accuracy

- Best results come from **clear, well-lit, straight-on photos** — especially
  of the **back panel**, where most mandatory declarations (MRP, mfg date,
  address, ingredients) actually live. Front panels are mostly branding/
  graphics and often don't carry these declarations at all.
- The system tries multiple preprocessing strategies per photo automatically
  and picks whichever gives the highest OCR confidence, and falls back to
  fuzzy keyword matching when the exact text doesn't line up (see table
  above) — but it cannot invent text that was never legible in the photo.
- If a photo is too blurry, at too sharp an angle, or has heavy glare, the
  report shows an **"OCR quality warning"** banner — treat FAIL results
  on that report with caution and consider re-scanning with a better photo.
- Fields matched via fuzzy matching are marked `[Verify]` / shown with a
  "verify" tag — these should be visually double-checked against the photo,
  since they were recovered from imperfect OCR text rather than an exact
  read.

## PDF report format

The downloadable PDF (`reports/generator.py`) is laid out like a field
inspection report rather than a generic printout: report number, inspecting
officer / premises fields (left blank for the officer to fill in by hand),
an overall finding banner, a rule-reference checklist table, and signature
blocks for the officer and the trader — matching the structure of the
paperwork officers already use during physical inspections, so this can
slot into existing workflows rather than requiring a new format.

## Disclaimer

This is a hackathon prototype. The font-size/readability check is a
pixel-ratio heuristic, not a calibrated physical measurement. Fuzzy-matched
fields are approximate and flagged as such. This tool supplements, and does
not replace, manual verification by an authorised Legal Metrology Officer.
