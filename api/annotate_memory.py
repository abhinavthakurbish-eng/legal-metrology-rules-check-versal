"""
annotate_memory.py
--------------------
Original label image par pass/fail boxes draw karta hai - bilkul jaisa
reports/annotate.py karta tha, lekin yahan kuch bhi DISK par save nahi hota.
Vercel serverless mein persistent disk hai hi nahi (har request alag/temporary
container mein chal sakta hai), isliye annotated image seedha memory mein
banti hai aur base64-encoded string ke roop mein return hoti hai - jise
HTML mein `<img src="data:image/jpeg;base64,...">` se seedha embed kar dete
hain. Koi static file, koi upload folder, kuch nahi chahiye.
"""

import base64
import io
from PIL import Image, ImageDraw, ImageOps

DISPLAY_MAX_DIMENSION = 1400
JPEG_QUALITY = 82


def annotate_image_to_base64(image_source, compliance_results, image_index=0):
    """
    image_source: file path / bytes / file-like object
    compliance_results: rule engine ka 'results' list
    image_index: is image ka index (kaunsi side-photo hai)

    Returns: base64-encoded JPEG string (bina "data:image/jpeg;base64," prefix ke -
             template mein prefix khud add karte hain)
    """
    if isinstance(image_source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(image_source))
    else:
        img = Image.open(image_source)
        img.load()

    img = ImageOps.exif_transpose(img).convert("RGB")
    draw = ImageDraw.Draw(img)

    for r in compliance_results:
        bbox = r.get("bbox")
        if not bbox:
            continue
        if bbox.get("image_index", 0) != image_index:
            continue
        color = (26, 127, 55) if r["status"] == "PASS" else (193, 18, 30)
        draw.rectangle(
            [bbox["left"], bbox["top"], bbox["right"], bbox["bottom"]],
            outline=color, width=3
        )
        label_text = r["rule_id"]
        text_y = max(0, bbox["top"] - 14)
        draw.rectangle([bbox["left"], text_y, bbox["left"] + 34, text_y + 14], fill=color)
        draw.text((bbox["left"] + 3, text_y + 1), label_text, fill=(255, 255, 255))

    # Display ke liye resize (page fast load ho, poori camera-resolution nahi bhejni)
    w, h = img.size
    longest = max(w, h)
    if longest > DISPLAY_MAX_DIMENSION:
        scale = DISPLAY_MAX_DIMENSION / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")
