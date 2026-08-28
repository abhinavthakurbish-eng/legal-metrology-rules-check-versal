# Legal Metrology Label Compliance Checker — Vercel Edition

This is a **stateless, Vercel-compatible** version of the compliance checker.
It exists because Vercel's serverless Python runtime cannot install
system-level binaries (like Tesseract OCR) and has no persistent filesystem —
so this version replaces local Tesseract with a **free cloud OCR API**
(OCR.space) and removes anything that needed a database or saved files.

**If you can use Render/Railway/Fly.io/Cloud Run instead, use the full
Docker-based version** (in the other project folder) — it has scan history,
a dashboard, CSV audit export, and Hindi OCR support, none of which are
possible in a true serverless environment without a lot of extra
infrastructure (external DB, external file storage). This Vercel edition is
a deliberately trimmed-down fallback for when only Vercel is available.

## What's different here vs. the full version

| Feature | Full (Render/Docker) version | This Vercel version |
|---|---|---|
| OCR engine | Local Tesseract (unlimited, free) | Cloud API (OCR.space, free tier is rate-limited) |
| Scan history / dashboard | Yes (SQLite) | **No** — each scan is one-off |
| CSV audit export | Yes | **No** |
| Hindi OCR | Yes | Not enabled by default (English only) |
| PDF download | Separate route, reads from disk | Embedded directly as a data-URI in the same response |
| Annotated photos | Saved to disk | Embedded directly as base64 in the HTML |

The rule engine (`rules_engine/engine.py` + `rules.json`) — including the
exact-then-fuzzy OCR-noise-tolerant matching — is **the same code**, reused
unchanged, since it just operates on a plain Python dict and doesn't care
where the OCR text came from.

## Project structure (all in `api/`, deliberately flat)

```
api/index.py          Flask app + all routes (entry point)
api/engine.py          Rule matching (exact-then-fuzzy), same logic as the full version
api/rules.json          Declarative Legal Metrology rules
api/ocr_cloud.py        OCR.space API wrapper
api/annotate_memory.py  Draws pass/fail boxes on photos, in-memory (no disk)
api/pdf_builder.py      Builds the PDF report in-memory (no disk)
vercel.json             Deployment config
requirements.txt        Python dependencies
```

Everything lives inside `api/` on purpose (not split across top-level
folders) - Vercel's Python builder is most reliable when all the code a
function needs is co-located with it, so this avoids any cross-directory
import/bundling issues.

## Setup

### 1. Get a free OCR.space API key (2 minutes, no credit card)
Go to **https://ocr.space/OCRAPI**, sign up, and copy the API key emailed to
you. Without this, the app falls back to OCR.space's public `helloworld` demo
key, which is heavily rate-limited (shared across everyone using it) and will
likely fail or get throttled under real use.

### 2. Deploy to Vercel
```bash
npm install -g vercel     # if you don't have the Vercel CLI
cd legal-metrology-checker-vercel
vercel
```
Or connect this folder as a GitHub repo through the Vercel dashboard
(**New Project → Import**) — Vercel will auto-detect `vercel.json`.

### 3. Add your API key as an environment variable
In the Vercel project dashboard: **Settings → Environment Variables**
```
OCR_SPACE_API_KEY = <your key from step 1>
```
Redeploy after adding it (env var changes need a redeploy to take effect).

### 4. Run locally (optional, for testing before deploying)
```bash
pip install -r requirements.txt
export OCR_SPACE_API_KEY=your_key_here     # Windows: set OCR_SPACE_API_KEY=your_key_here
python3 api/index.py
```
Open **http://localhost:5000**

## Limits to know about

- **OCR.space free tier**: ~1MB per image (this app auto-compresses images to
  fit), and a request-rate limit — fine for demos/hackathon judging, not for
  heavy production traffic.
- **Vercel Hobby plan function duration**: configured for up to 60s in
  `vercel.json`, but your actual plan may cap this lower — if scans time out
  with 3+ large photos, try fewer/smaller photos per scan.
- **No persistence**: refreshing the report page re-submits nothing — there's
  no "past scans" list. If you need that, use the full Docker/Render version.

## Disclaimer

This is a hackathon prototype. Fuzzy-matched fields are approximate and
flagged as such (`[Verify]` tag). This tool supplements, and does not
replace, manual verification by an authorised Legal Metrology Officer.
