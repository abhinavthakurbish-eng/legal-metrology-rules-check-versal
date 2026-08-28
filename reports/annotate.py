"""
reports/annotate.py
---------------------
Original label image par colored boxes draw karta hai jahan-jahan
declarations mili (green) - taaki inspector ko visually pata chale
system ne kya detect kiya. Yeh report ko "trust karne layak" banata hai,
sirf ek text list se zyada convincing hota hai.

Ab product ke multiple side-photos ho sakte hain, isliye har image ko
alag se annotate karte hain - is function ko "image_index" ke saath call
karo taaki sirf usi image ke bounding boxes uspe draw hon (doosri side
ki photo ke boxes yahan mix na ho jaayen).

IMPORTANT: Modern phone camera photos aksar 3000-6000px wide hote hain
(kai MB ki file). Report page mein browser ko yeh FULL-resolution images
seedha bhejna page ko bahut slow (kabhi kabhi minutes tak!) load karwa
sakta hai - annotation ke liye itni resolution ki zaroorat bhi nahi hai.
Isliye annotate karne ke baad image ko ek "display-friendly" size (max
1400px) tak resize karke save karte hain - box positions annotation ke
time original resolution pe calculate hoti hain, phir poori image
(boxes samet) resize hoti hai, isliye boxes sahi jagah pe hi rehte hain.
"""

from PIL import Image, ImageDraw, ImageFont
import os

# Report page / PDF mein dikhane ke liye itni resolution kaafi hai -
# isse zyada sirf page ko slow karega, koi extra clarity nahi degi
DISPLAY_MAX_DIMENSION = 1400
JPEG_QUALITY = 82


def _resize_for_display(img):
    """Image ko display ke liye reasonable size tak resize karta hai (agar zaroorat ho)."""
    w, h = img.size
    longest_side = max(w, h)
    if longest_side <= DISPLAY_MAX_DIMENSION:
        return img
    scale = DISPLAY_MAX_DIMENSION / longest_side
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.LANCZOS)


def create_annotated_image(original_image_path, compliance_results, output_path, image_index=0):
    """
    compliance_results: rule engine ka 'results' list (har rule ka dict, jisme
                         optional 'bbox' hota hai agar match mila; bbox mein
                         'image_index' bhi hota hai - yeh batata hai match
                         product ki kaun si side-photo mein mila tha).
    image_index: is particular image ka index (jaise front=0, back=1, ...) -
                 sirf usi image se related boxes yahan draw honge.

    Boxes ORIGINAL resolution pe draw hote hain (taaki position accurate rahe),
    phir POORI image (boxes samet) display-size tak resize hoti hai - isliye
    boxes hamesha sahi jagah pe rehte hain, chahe final image chhoti ho.
    """
    img = Image.open(original_image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    for r in compliance_results:
        bbox = r.get("bbox")
        if not bbox:
            continue
        # Yeh box kis image ka hai check karo - sirf apni image ke boxes draw karo
        if bbox.get("image_index", 0) != image_index:
            continue
        color = (26, 127, 55) if r["status"] == "PASS" else (193, 18, 30)  # green / red
        draw.rectangle(
            [bbox["left"], bbox["top"], bbox["right"], bbox["bottom"]],
            outline=color, width=3
        )
        # Chhota label rule-id ke saath box ke upar
        label_text = r["rule_id"]
        text_y = max(0, bbox["top"] - 14)
        draw.rectangle([bbox["left"], text_y, bbox["left"] + 34, text_y + 14], fill=color)
        draw.text((bbox["left"] + 3, text_y + 1), label_text, fill=(255, 255, 255))

    img = _resize_for_display(img)
    img.save(output_path, quality=JPEG_QUALITY, optimize=True)
    return output_path


def create_annotated_images(image_paths, compliance_results, output_paths):
    """
    Convenience wrapper - product ki saari side-photos ko ek saath annotate
    karta hai. image_paths aur output_paths same length aur same order mein
    hone chahiye (index se match karte hain).
    """
    for idx, (in_path, out_path) in enumerate(zip(image_paths, output_paths)):
        create_annotated_image(in_path, compliance_results, out_path, image_index=idx)
    return output_paths
