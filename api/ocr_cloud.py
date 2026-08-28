"""
ocr_cloud.py
-------------
Vercel serverless par Tesseract install NAHI ho sakta (koi apt-get/system
binary install nahi chalta serverless functions mein). Isliye yahan OCR
ek FREE CLOUD API (OCR.space) se hota hai - sirf ek HTTP request, koi local
binary ki zaroorat nahi.

IMPORTANT SETUP: ek free API key chahiye -
  1. https://ocr.space/OCRAPI par jaake free signup karo (credit card nahi
     chahiye, key turant email pe mil jaati hai)
  2. Vercel project settings mein Environment Variable add karo:
     OCR_SPACE_API_KEY = <tumhari key>
Agar key set nahi ki, toh yeh "helloworld" demo key use karega - woh kaam
karti hai lekin bahut heavily rate-limited hai (sab demo-key users ke beech
shared hai), production/demo ke liye apni free key zaroor lena.

Is module ka output bilkul WAHI shape mein hai jo humara original
ocr/extractor.py (Tesseract-based) deta tha - isliye rules_engine/engine.py
mein KOI CHANGE nahi karna pada, woh dono OCR sources ke saath kaam karta hai.
"""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageOps

OCR_SPACE_API_URL = "https://api.ocr.space/parse/image"
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "helloworld")

# OCR.space free tier ~1MB file size limit - isse chota rakhna zaroori hai
MAX_UPLOAD_BYTES = 950_000
MAX_DIMENSION = 1800
REQUEST_TIMEOUT_SECONDS = 25


def _compress_image_for_api(pil_img):
    """
    Image ko resize + JPEG-compress karta hai taaki OCR.space ke free-tier
    size-limit (~1MB) ke andar fit ho jaaye. Quality step-by-step kam karte
    hain jab tak size limit ke andar na aa jaaye.
    Returns: (BytesIO buffer, (sent_width, sent_height))
    """
    img = ImageOps.exif_transpose(pil_img)  # phone photos mein EXIF rotation common hai
    img = img.convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_DIMENSION:
        scale = MAX_DIMENSION / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    quality = 88
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= MAX_UPLOAD_BYTES or quality <= 25:
            buf.seek(0)
            return buf, img.size
        quality -= 12


def _empty_result(w, h, error=None):
    return {
        "full_text": "",
        "words": [],
        "image_height": h,
        "image_width": w,
        "avg_confidence": 0.0,
        "preprocessing_used": None,
        "low_confidence_warning": True,
        "error": error
    }


def extract_text_and_boxes(image_source):
    """
    Ek image OCR.space API se process karta hai.
    image_source: file path (string) YA raw bytes YA file-like object - sab chalega.

    Returns dict (Tesseract-wale extractor.py jaisa hi shape):
    {
        "full_text": "...", "words": [{"text","left","top","width","height","conf","height_ratio"}, ...],
        "image_height":.., "image_width":.., "avg_confidence":.., "low_confidence_warning":..
    }
    """
    if isinstance(image_source, (bytes, bytearray)):
        pil_img = Image.open(io.BytesIO(image_source))
    else:
        pil_img = Image.open(image_source)
        pil_img.load()  # ensure fully read before any underlying file handle closes

    pil_img = ImageOps.exif_transpose(pil_img)
    orig_w, orig_h = pil_img.size

    buf, sent_size = _compress_image_for_api(pil_img)
    scale = sent_size[0] / orig_w if orig_w else 1.0

    try:
        resp = requests.post(
            OCR_SPACE_API_URL,
            files={"file": ("image.jpg", buf, "image/jpeg")},
            data={
                "apikey": OCR_SPACE_API_KEY,
                "language": "eng",
                "isOverlayRequired": "true",
                "scale": "true",
                "detectOrientation": "true",
                "OCREngine": "2",
            },
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        result = resp.json()
    except Exception as e:
        return _empty_result(orig_w, orig_h, error=f"OCR API call fail hui: {e}")

    if result.get("IsErroredOnProcessing"):
        err = result.get("ErrorMessage") or result.get("ErrorDetails") or "Unknown OCR API error"
        return _empty_result(orig_w, orig_h, error=str(err))

    parsed_results = result.get("ParsedResults") or []
    if not parsed_results:
        return _empty_result(orig_w, orig_h, error="OCR API se koi result nahi mila")

    parsed = parsed_results[0]
    full_text = parsed.get("ParsedText", "") or ""

    words = []
    overlay = parsed.get("TextOverlay") or {}
    for line in overlay.get("Lines", []) or []:
        for w in line.get("Words", []) or []:
            left = w.get("Left", 0) / scale
            top = w.get("Top", 0) / scale
            width = w.get("Width", 0) / scale
            height = w.get("Height", 0) / scale
            words.append({
                "text": w.get("WordText", ""),
                "left": left, "top": top, "width": width, "height": height,
                "conf": 75.0,  # OCR.space free tier per-word confidence nahi deta
                "height_ratio": (height / orig_h) if orig_h else 0
            })

    text_len = len(full_text.strip())
    avg_confidence = 75.0 if words else 0.0
    low_confidence = text_len < 15  # bahut kam text mila - photo shayad unclear thi

    return {
        "full_text": full_text,
        "words": words,
        "image_height": orig_h,
        "image_width": orig_w,
        "avg_confidence": avg_confidence,
        "preprocessing_used": "ocr_space_engine2",
        "low_confidence_warning": low_confidence
    }


def extract_text_and_boxes_multi(image_sources):
    """
    MAIN FUNCTION - app.py isko call karta hai. Saari uploaded side-photos ko
    PARALLEL mein OCR.space bhejta hai (network calls hain, thread se fayda
    hota hai chahe Python ka GIL ho, kyunki wait ke time GIL release hoti hai).
    """
    if not image_sources:
        raise ValueError("Kam se kam ek image chahiye OCR ke liye.")

    with ThreadPoolExecutor(max_workers=min(4, len(image_sources))) as executor:
        per_image_results = list(executor.map(extract_text_and_boxes, image_sources))

    combined_full_text = " \n ".join(r["full_text"] for r in per_image_results)
    all_confidences = [w["conf"] for r in per_image_results for w in r["words"]]
    avg_confidence = round(sum(all_confidences) / len(all_confidences), 2) if all_confidences else 0.0

    return {
        "images": per_image_results,
        "full_text": combined_full_text,
        "avg_confidence": avg_confidence,
        "any_low_confidence": any(r["low_confidence_warning"] for r in per_image_results)
    }
