"""
ocr/extractor.py
-----------------
Yeh module label ki image (ya ek product ki multiple side-photos) leta hai
aur extracted text + bounding boxes deta hai.

Design decisions (aur kyun):

1. SPEED: Multiple side-photos ka OCR ThreadPoolExecutor se PARALLEL chalta
   hai (sequential nahi). Tesseract ek external subprocess hai, isliye Python
   ka GIL isko block nahi karta - 3 photos upload karne pe woh teeno roughly
   ek hi time mein process hoti hain, 3x time nahi lagta.
   Image bhi zyada bada nahi banate (max 1600px width) kyunki bahut bada
   image OCR ko dhीma kar deta hai bina accuracy mein utna fayda diye.
   Heavy denoising (fastNlMeansDenoising) hata di hai - woh sabse slow step
   tha; uski jagah bilateralFilter use kiya hai jo kaafi tez hai aur edges
   (jo text ke liye zaroori hain) ko blur nahi karta.

2. ACCURACY:
   a) Orientation auto-correct - agar photo ulti ya 90 degree ghumi hui hai
      (mobile se photo lete waqt aksar hota hai), Tesseract ka OSD (Orientation
      and Script Detection) use karke usko seedha kar dete hain OCR se pehle.
   b) CLAHE (adaptive contrast enhancement) - glossy/colorful packaging pe
      text aur background ka contrast kam hota hai; CLAHE local contrast
      badhata hai bina poori image ko over-expose kiye.
   c) 2 preprocessing variants try karte hain (CLAHE+Otsu, aur plain
      contrast-stretched grayscale) aur jiska Tesseract confidence zyada ho
      wo use hota hai - isse simple plain-background label aur busy/glossy
      packaging dono handle ho jaate hain, bina bahut slow hue.

IMPORTANT REALITY CHECK: Agar photo bahut blurry hai, bahut choti hai, ya
bahut zyada glare/reflection hai, koi bhi preprocessing usse perfect text
nahi bana sakta - garbage in, garbage out. "low_confidence_warning" flag
isi liye hai: system khud bata deta hai jab usse bharosa na kiya jaaye.
Best result ke liye: seedha upar se photo lo (angle se nahi), achi lighting
(no direct flash glare), aur back panel (plain background, dense text) ka
photo front panel (graphics-heavy) se behtar OCR karta hai.
"""

import cv2
import pytesseract
import numpy as np
from concurrent.futures import ThreadPoolExecutor

MAX_DIMENSION = 2400          # bahut zyada bade phone-photos ko itne tak cap karte hain (speed)
TARGET_DIMENSION = 1800       # OCR ke liye ideal size - isse chote ko upscale karte hain
GOOD_ENOUGH_CONFIDENCE = 45    # itna confidence mil jaaye toh dusra variant try nahi karte
LOW_CONFIDENCE_THRESHOLD = 35  # iske neeche confidence ho toh warning dikhao

# IMPORTANT (speed): Har pytesseract call ek NAYA subprocess (tesseract.exe/
# tesseract binary) launch karta hai. Windows par (khaaskar antivirus scan ke
# saath), har naye process ka launch khud hi 1-3+ seconds le sakta hai -
# yeh OCR ka "kaam" nahi hai, sirf process-spawn overhead hai. Pehle is
# module mein har image ke liye up to 4 alag subprocess calls hote the
# (1 orientation-check + up to 3 OCR variants) - is wajah se result page
# "minutes" tak slow ho sakta tha, khaaskar kamzor/Windows machines pe.
# Ab: orientation-check by default OFF hai (niche ENABLE_ORIENTATION_CHECK
# dekho), aur OCR variants max 2 tak limited hain - subprocess count
# 4 se seedha 1-2 tak aa gaya hai.
OCR_LANGUAGES = "eng+hin"

# Orientation-check (OSD) apna ek poora subprocess call hai. Zyaadatar log
# apna phone seedha rakh ke hi photo khींchte hain, isliye yeh feature
# "nice to have" hai, zaroori nahi - aur iski cost (1 extra process launch
# har image ke liye) speed ke liye bahut mehenga hai. Isliye default OFF hai.
# Agar tumhare photos kabhi ulti/tirchi aati hain, isko True kar sakte ho -
# lekin phir wapas slow ho jaayega.
ENABLE_ORIENTATION_CHECK = False

# Bahut noisy/garbage images (bad quality photos, random textures) pe kabhi
# kabhi Tesseract ko bahut zyada "possible characters" dikhte hain aur woh
# process karne mein असामान्य रूप से bahut zyada time le leta hai (tested:
# ek pathological case mein 35+ seconds ek hi variant ke liye!). Yeh hard
# timeout isse bachata hai - agar ek variant itne mein khatam na ho, use
# chhod ke aage badh jaate hain, taaki ek kharab photo poore system ko
# atka na de. Chhota rakha hai (6s) taaki agar image genuinely bahut noisy
# hai (jismein bahar bhi timeout hoga), poora scan phir bhi jaldi khatam ho -
# is case mein hum baaki variants bhi skip kar dete hain (neeche dekho).
TESSERACT_TIMEOUT_SECONDS = 4

# OSD (orientation check) apne aap mein ek chhota kaam hai - agar yeh khud
# 5 second se zyada le raha hai, kuch gadbad hai (jaise pehle bug tha: is call
# pe koi timeout nahi tha, aur agar OSD kisi image pe atak jaata, poora scan
# minutes tak ruk jaata - "result page load hone mein minutes lagna" isi
# missing timeout ki wajah se ho sakta tha).
OSD_TIMEOUT_SECONDS = 5
OSD_MAX_DIMENSION = 1000      # orientation-check ke liye chhoti copy use karte hain (speed, jab enabled ho)


def _correct_orientation(img):
    """
    Tesseract ka OSD (Orientation and Script Detection) use karke check karta
    hai ki image ulti/tirchi toh nahi hai. DEFAULT OFF hai (ENABLE_ORIENTATION_CHECK
    dekho upar) kyunki yeh apna ek poora extra subprocess call hai - speed ke
    liye mehenga, aur zyaadatar photos already seedhi hoti hain.
    """
    if not ENABLE_ORIENTATION_CHECK:
        return img

    try:
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > OSD_MAX_DIMENSION:
            small_scale = OSD_MAX_DIMENSION / longest
            small_copy = cv2.resize(img, None, fx=small_scale, fy=small_scale, interpolation=cv2.INTER_AREA)
        else:
            small_copy = img

        osd = pytesseract.image_to_osd(small_copy, config="--psm 0", timeout=OSD_TIMEOUT_SECONDS)
        rotate_angle = 0
        for line in osd.split("\n"):
            if line.startswith("Rotate:"):
                rotate_angle = int(line.split(":")[1].strip())
                break
        if rotate_angle == 90:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif rotate_angle == 180:
            img = cv2.rotate(img, cv2.ROTATE_180)
        elif rotate_angle == 270:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception:
        # OSD kabhi kabhi bahut kam text wali image pe fail ho jaata hai -
        # tab bas original orientation ke saath aage badhte hain
        pass
    return img


def _resize_for_ocr(img):
    """
    Image ko OCR ke liye ideal size mein laata hai.
    Tesseract ka accuracy text ki actual pixel-height pe depend karta hai -
    bahut chote text (chahe image resolution kuch bhi ho) ko upscale karna
    padta hai taaki characters clearly bane. Isliye hum "longest side" ko
    ek target size (2200px) ke around laane ki koshish karte hain:
      - Agar image isse chhoti hai -> upscale karo (chhota text bhi padhne layak banega)
      - Agar image bahut badi hai (jaise modern phone camera ki 3000-4000px photo)
        -> ek reasonable cap (3200px) tak hi rakho, warna OCR bahut slow ho jaata hai
           bina accuracy mein khaas fayda diye
    """
    h, w = img.shape[:2]
    longest_side = max(h, w)

    if longest_side > MAX_DIMENSION:
        scale = MAX_DIMENSION / longest_side
    elif longest_side < TARGET_DIMENSION:
        scale = TARGET_DIMENSION / longest_side
    else:
        scale = 1.0

    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    return img, scale


def _run_tesseract(processed_img, scale):
    """
    Ek preprocessed image pe Tesseract chalata hai aur (words, full_text_parts,
    avg_confidence) return karta hai.
    Agar Tesseract TESSERACT_TIMEOUT_SECONDS mein khatam na ho (kabhi kabhi
    genuinely garbage/noisy images pe hota hai), toh exception nahi phenkte -
    bas empty result de dete hain taaki caller agla variant try kar sake ya
    gracefully "low confidence" report kar sake, poora request atke nahi.
    """
    custom_config = r'--oem 3 --psm 6'
    try:
        data = pytesseract.image_to_data(
            processed_img,
            lang=OCR_LANGUAGES,
            config=custom_config,
            output_type=pytesseract.Output.DICT,
            timeout=TESSERACT_TIMEOUT_SECONDS
        )
    except pytesseract.TesseractNotFoundError:
        # Tesseract BINARY hi system pe install nahi hai (jaise Vercel jaisi
        # serverless platforms pe, jahan apt-get se system packages install
        # nahi ho sakte). Isko saaf, samajh aane wala error banate hain -
        # bajaye silently kharab/confusing compliance score dikhane ke
        # (jaisa pehle ho raha tha - OCR fail hoke bhi ek "12%" jaisa
        # misleading number aa jaata tha).
        raise RuntimeError(
            "Tesseract OCR is server par install nahi hai. Yeh sirf Docker-based "
            "hosting (jaise Render, jisme humara Dockerfile tesseract-ocr install "
            "karta hai) par kaam karega - Vercel jaisi serverless platforms par "
            "system-level software install nahi ho sakta, isliye wahan yeh kabhi "
            "kaam nahi karega."
        )
    except RuntimeError:
        # pytesseract yeh error deta hai jab timeout ho jaaye
        return [], [], 0.0, True   # timed_out=True
    except pytesseract.TesseractError:
        # Agar Hindi language pack kisi wajah se available nahi hai (jaise
        # deployment environment mein install missing ho gaya), English-only
        # pe safely fallback karo bajaye poore scan ko crash karne ke.
        try:
            data = pytesseract.image_to_data(
                processed_img,
                lang="eng",
                config=custom_config,
                output_type=pytesseract.Output.DICT,
                timeout=TESSERACT_TIMEOUT_SECONDS
            )
        except RuntimeError:
            return [], [], 0.0, True

    words = []
    confidences = []
    full_text_parts = []

    n_boxes = len(data['text'])
    for i in range(n_boxes):
        word_text = data['text'][i].strip()
        conf = float(data['conf'][i])

        if word_text == "" or conf < 0:
            continue

        left = int(data['left'][i] / scale)
        top = int(data['top'][i] / scale)
        width = int(data['width'][i] / scale)
        height = int(data['height'][i] / scale)

        words.append({
            "text": word_text,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "conf": conf
        })
        confidences.append(conf)
        full_text_parts.append(word_text)

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return words, full_text_parts, avg_conf, False   # timed_out=False


def extract_text_and_boxes(image_path):
    """
    Ek single image process karta hai: load -> orientation fix -> resize ->
    preprocessing variants try karo, EK-EK karke, aur jaise hi confidence
    "achha" (GOOD_ENOUGH_CONFIDENCE) mil jaaye, wahin ruk jao.

    Yeh "lazy evaluation" approach hai - zyaadatar clean/decent photos ke liye
    sirf EK variant try hota hai (fast). Sirf genuinely mushkil photos
    (blurry/glossy/busy background) ke liye 2nd aur 3rd variant try hote hain.
    Isse average case mein 2-3x speedup milta hai, khaaskar kamzor/free-tier
    server CPU pe jahan har extra Tesseract call ka cost zyada mehsoos hota hai.

    Returns dict:
    {
        "full_text": "...", "words": [...],
        "image_height": <original height>, "image_width": <original width>,
        "avg_confidence": 82.5, "preprocessing_used": "otsu",
        "low_confidence_warning": False
    }
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Image load nahi ho payi: {image_path}. Check karo file corrupt toh nahi.")

    original_height, original_width = img.shape[:2]

    img = _correct_orientation(img)
    img, scale = _resize_for_ocr(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    best_result = None
    best_score = -1
    best_variant_name = None
    any_variant_timed_out = False

    def _try_variant(name, processed_img):
        nonlocal best_result, best_score, best_variant_name, any_variant_timed_out
        words, full_text_parts, avg_conf, timed_out = _run_tesseract(processed_img, scale)
        if timed_out:
            any_variant_timed_out = True
        score = avg_conf * (1 + min(len(words), 50) / 50)
        if score > best_score:
            best_score = score
            best_result = (words, full_text_parts, avg_conf)
            best_variant_name = name
        return avg_conf

    # Variant 1: Otsu threshold - sabse tez, aur zyaadatar plain-background
    # labels ke liye already best result de deta hai
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    conf1 = _try_variant("otsu", otsu)

    # Agar variant 1 hi timeout ho gaya (bahut noisy/pathological image),
    # baaki variants try karna waste hai - woh bhi isi wajah se slow honge.
    # Bas yahin ruk jao aur "low confidence" report kar do.
    if any_variant_timed_out:
        words, full_text_parts, avg_conf = best_result
        return {
            "full_text": " ".join(full_text_parts),
            "words": [
                {**w, "height_ratio": (w["height"] / original_height) if original_height else 0}
                for w in words
            ],
            "image_height": original_height,
            "image_width": original_width,
            "avg_confidence": round(avg_conf, 2),
            "preprocessing_used": best_variant_name,
            "low_confidence_warning": True
        }

    # Agar Otsu ka result pehle se hi achha hai, toh yahin ruk jao - koi
    # extra Tesseract call nahi (yeh most common, fast path hai - aur ab
    # sirf MAX 2 variants try hote hain, 3 nahi, taaki subprocess-launch
    # overhead kam se kam rahe)
    if conf1 < GOOD_ENOUGH_CONFIDENCE:
        # Variant 2 (last resort): Adaptive threshold - uneven lighting/shadow
        # wali photos ke liye Otsu se behtar hota hai
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 15
        )
        _try_variant("adaptive", adaptive)

    words, full_text_parts, avg_conf = best_result

    words_out = [
        {**w, "height_ratio": (w["height"] / original_height) if original_height else 0}
        for w in words
    ]

    return {
        "full_text": " ".join(full_text_parts),
        "words": words_out,
        "image_height": original_height,
        "image_width": original_width,
        "avg_confidence": round(avg_conf, 2),
        "preprocessing_used": best_variant_name,
        "low_confidence_warning": avg_conf < LOW_CONFIDENCE_THRESHOLD
    }


def extract_text_and_boxes_multi(image_paths):
    """
    MAIN FUNCTION - isko app.py se call karo jab product ke ek ya zyada
    side-photos upload hui hon (front, back, ingredients list, waghera).

    Saari images PARALLEL mein process hoti hain (ThreadPoolExecutor) taaki
    zyada photos upload karne pe wait time linearly na badhe.

    Returns:
    {
        "images": [ <extract_text_and_boxes() result har image ke liye>, ... ],
        "full_text": "saari images ka text jod kar",
        "avg_confidence": weighted average,
        "any_low_confidence": True agar koi bhi image OCR ke liye mushkil thi
    }
    """
    if not image_paths:
        raise ValueError("Kam se kam ek image chahiye OCR ke liye.")

    # Max 4 threads - itne se zyada parallel Tesseract processes Colab ke
    # limited CPU pe fayda nahi dete, ulta context-switching overhead badhata hai
    with ThreadPoolExecutor(max_workers=min(4, len(image_paths))) as executor:
        per_image_results = list(executor.map(extract_text_and_boxes, image_paths))

    combined_full_text = " \n ".join(r["full_text"] for r in per_image_results)

    all_confidences = [w["conf"] for r in per_image_results for w in r["words"]]
    avg_confidence = round(sum(all_confidences) / len(all_confidences), 2) if all_confidences else 0.0

    return {
        "images": per_image_results,
        "full_text": combined_full_text,
        "avg_confidence": avg_confidence,
        "any_low_confidence": any(r["low_confidence_warning"] for r in per_image_results)
    }
