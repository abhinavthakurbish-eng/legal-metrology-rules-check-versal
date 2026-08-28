"""
rules_engine/engine.py
-----------------------
Yeh module rules.json padhta hai aur OCR se nikle hue combined text/words ko
har rule ke against check karta hai.

MATCHING STRATEGY (3 steps, "fail-soft" order - fast & strict pehle, phir
zyada lenient jab zaroorat pade):

  1. STRICT REGEX (fast path): agar OCR clean hai (jaisa ki simple/plain
     labels pe hota hai), rule ka poora "regex" seedha match ho jaata hai.

  2. FUZZY KEYWORD ANCHOR + VALUE WINDOW (fallback, jab OCR mein noise ho):
     Real-world OCR text mein chhoti spelling mistakes bahut common hain -
     jaise "MRP" ko "MRPs" ya "Net Wt" ko "Netwe" padh lena. Isi wajah se
     strict regex fail ho jaata hai jabki declaration asal mein maujood hai.
     Research mein isko "OCR post-processing via fuzzy/approximate string
     matching" kaha jaata hai (dekho: Hamdi et al. 2022 iOCR paper; Halford,
     "Fuzzy regex matching"; aur Silberpfennig et al. 2015 ICDAR "OCR
     word-spotting" - sab isi principle pe based hain: keyword ko EXACT
     match karne ki jagah usko "approximately kitna similar hai" (edit
     distance / SequenceMatcher ratio) se dhoondo, phir uske paas ki
     text mein asli VALUE (number/date/etc, jo strict rehta hai) dhoondo.
     Hum yahan Python ki built-in difflib.SequenceMatcher use karte hain
     (koi extra dependency install nahi karni padti - deployment simple
     rehta hai).

  3. Agar dono fail ho jaayein -> genuinely missing maan ke FAIL/WARNING.

Yeh matching hone ke baad har result mein "matched_via" field hota hai
("exact" ya "fuzzy") - report mein "fuzzy" wale results ko halka sa alag
dikhaya jaata hai ("verify manually" note) taaki officer ko pata rahe ki
yeh OCR approximation se mila hai, 100% certain match nahi.

Font-size rule (field == "font_size") alag se, height-based heuristic hai.

Isko "AI" mat samjho - yeh ek explainable checklist evaluator hai + ek
OCR-noise-tolerant fuzzy fallback. Judge poochhega "yeh fail kyun hua"
toh exact reason dikha sakte ho.
"""

import json
import re
import os
from difflib import SequenceMatcher

RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.json")

# Fuzzy keyword match ke liye similarity threshold (0-1 scale).
# 0.72 matlab keyword aur candidate text mein ~72% characters/sequence match
# hone chahiye - itna lenient ki chhoti OCR typos (1-2 letters galat) cover ho
# jaayein, lekin itna strict ki bilkul alag words match na ho jaayein.
FUZZY_MATCH_THRESHOLD = 0.72

# Fuzzy anchor milne ke baad, uske turant baad kitne characters mein value
# (number/date/etc) dhoondni hai
VALUE_SEARCH_WINDOW = 40

# Bahut chhote keywords (jaise "mfd", sirf 3 letters) fuzzy matching mein risky
# hote hain - itni chhoti string ke saath koi bhi random 3-letter window
# "accidentally" similar nikal sakta hai, jisse GALAT jagah match ho jaata hai.
# Isliye fuzzy step ke liye sirf thode lambe keywords use karte hain; chhote
# keywords sirf STRICT regex step mein use hote hain (jahan exact match hi chahiye).
MIN_KEYWORD_LENGTH_FOR_FUZZY = 5


def load_rules():
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["rules"]


def find_bounding_box_for_match(matched_text, words):
    """
    Regex se jo text match hua, uske corresponding OCR words dhundo
    taaki hum image pe box draw kar sakein (annotated report ke liye).

    Simple approach: matched_text ke pehle 2-3 words ko OCR words list
    mein dhundo (case-insensitive), aur unki bounding box union nikaalo.
    """
    matched_tokens = matched_text.lower().split()[:3]
    if not matched_tokens:
        return None

    found_boxes = []
    for word in words:
        if word["text"].lower().strip(".,:") in matched_tokens:
            found_boxes.append(word)

    if not found_boxes:
        return None

    left = min(w["left"] for w in found_boxes)
    top = min(w["top"] for w in found_boxes)
    right = max(w["left"] + w["width"] for w in found_boxes)
    bottom = max(w["top"] + w["height"] for w in found_boxes)

    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _fuzzy_find_keyword_anchor(text, keywords):
    """
    Text mein har keyword phrase ko FUZZY (approximate) match se dhoondta hai -
    exact spelling nahi maangta, OCR typos tolerate karta hai.

    WORD-LEVEL matching use karte hain (character-level sliding-window ki
    jagah): text ko words mein split karte hain (OCR generally word-boundaries
    /spaces sahi detect karta hai, chahe individual characters ke andar
    mistakes ho - jaise "MRPs" ya "netwe" mein bhi word boundary sahi hai),
    phir keyword jitne words ka hai utne-word ka OCR-word-window nikaal ke
    compare karte hain. Yeh character-sliding-window se zyada robust hai
    kyunki yeh natural word-alignment respect karta hai.

    Returns: (end_index_in_text, matched_score) ya (None, 0) agar kuch na mile
    """
    words = text.split()
    if not words:
        return None, 0

    # Har word ka text mein start/end character-offset precompute karo
    # (taaki match milne par hum value-search window ke liye sahi position
    # nikaal sakein - words " " (single space) se joined maan ke chalte hain,
    # jaisa extractor.py mein " ".join() se banaya jaata hai)
    offsets = []
    pos = 0
    for w in words:
        start = text.find(w, pos)
        if start == -1:
            start = pos
        end = start + len(w)
        offsets.append((start, end))
        pos = end

    best_end = None
    best_score = 0

    for keyword in keywords:
        if len(keyword) < MIN_KEYWORD_LENGTH_FOR_FUZZY:
            continue  # bahut chhota keyword - fuzzy ke liye skip (upar comment dekho)
        keyword_word_count = max(1, len(keyword.split()))

        for i in range(len(words) - keyword_word_count + 1):
            window_words = words[i:i + keyword_word_count]
            window_phrase = " ".join(window_words)
            score = SequenceMatcher(None, keyword, window_phrase).ratio()
            if score > best_score:
                best_score = score
                best_end = offsets[i + keyword_word_count - 1][1]

    if best_score >= FUZZY_MATCH_THRESHOLD:
        return best_end, best_score
    return None, 0


def check_font_size_rule(rule, ocr_result):
    """
    Font-size / readability heuristic check.
    Logic: har OCR word (chahe woh kisi bhi side-photo se aaya ho) ki
    height_ratio (uski apni image ke relative) dekho. MEDIAN use karte hain
    (average ki jagah) kyunki chhoti-chhoti "noise" detections (jaise barcode
    ke neeche ke digits, batch-code ke chhote characters) average ko neeche
    khींch sakte hain jabki asli label text theek size ka ho - median isse
    zyada robust hai.

    IMPORTANT LIMITATION (report mein bhi mention karna):
    Yeh sirf ek heuristic hai. Asli legal font-size (mm mein) nikalne
    ke liye photo mein ek known-size reference object (jaise ek scale/ruler)
    ya camera calibration chahiye hoti hai. Prototype ke liye hum sirf
    "relative to image size" check kar rahe hain.
    """
    all_words = [w for img in ocr_result["images"] for w in img["words"]]

    if not all_words:
        return {
            "rule_id": rule["id"],
            "label": rule["label"],
            "status": "FAIL",
            "reason": "Koi text detect nahi hua, font size check nahi ho paaya.",
            "severity": rule["severity"],
            "extracted_value": None,
            "bbox": None,
            "matched_via": None
        }

    ratios = sorted(w["height_ratio"] for w in all_words if w["height_ratio"] > 0)
    median_ratio = ratios[len(ratios) // 2] if ratios else 0
    small_text_count = sum(1 for w in all_words if w["height_ratio"] < rule["min_text_height_ratio"])
    small_text_pct = round((small_text_count / len(all_words)) * 100, 1) if all_words else 0

    if median_ratio < rule["min_text_height_ratio"]:
        return {
            "rule_id": rule["id"],
            "label": rule["label"],
            "status": "FAIL" if rule.get("required", True) else "WARNING",
            "reason": f"Median text height ratio ({round(median_ratio, 4)}) minimum threshold "
                      f"({rule['min_text_height_ratio']}) se kam hai. ~{small_text_pct}% words bahut chhote hain. "
                      f"NOTE: yeh photo ke distance/framing par bhi depend karta hai (poora product photo vs "
                      f"zoomed-in label) - heuristic hai, definitive nahi.",
            "severity": rule["severity"],
            "extracted_value": f"{small_text_pct}% text below minimum readable size",
            "bbox": None,
            "matched_via": None
        }
    else:
        return {
            "rule_id": rule["id"],
            "label": rule["label"],
            "status": "PASS",
            "reason": "Text ka size acceptable range mein hai.",
            "severity": rule["severity"],
            "extracted_value": f"median ratio: {round(median_ratio, 4)}",
            "bbox": None,
            "matched_via": None
        }


def _build_pass_result(rule, matched_text, bbox, matched_via):
    return {
        "rule_id": rule["id"],
        "label": rule["label"],
        "status": "PASS",
        "reason": "Declaration mil gayi aur format sahi hai." if matched_via == "exact"
                  else "Declaration mili, lekin OCR mein halki si noise thi - "
                       "approximate (fuzzy) match ke through detect hui hai. Photo se ek baar manually confirm kar lena.",
        "severity": rule["severity"],
        "extracted_value": matched_text.strip()[:100] if matched_text else None,
        "bbox": bbox,
        "matched_via": matched_via
    }


def check_regex_rule(rule, ocr_result):
    """
    Generic regex-based rule check (MRP, net qty, mfg date, waghera).

    Step 1 (exact): strict rule["regex"] try karo har image ke apne text mein,
                     phir combined text mein.
    Step 2 (fuzzy):  agar exact match nahi mila, keyword ko FUZZY dhoondo
                     (OCR typos tolerate karte hue) aur uske paas ki text
                     mein rule["value_regex"] se asli value nikaalo.
    """
    pattern = re.compile(rule["regex"], re.IGNORECASE)

    # ---- Step 1: EXACT match, har image mein ----
    for image_index, img in enumerate(ocr_result["images"]):
        match = pattern.search(img["full_text"].lower())
        if match:
            matched_text = match.group(0)
            bbox = find_bounding_box_for_match(matched_text, img["words"])
            if bbox:
                bbox["image_index"] = image_index
            return _build_pass_result(rule, matched_text, bbox, "exact")

    # ---- Step 1b: EXACT match, combined text mein (multi-photo split case) ----
    combined_text = ocr_result["full_text"].lower()
    combined_match = pattern.search(combined_text)
    if combined_match:
        return _build_pass_result(rule, combined_match.group(0), None, "exact")

    # ---- Step 2: FUZZY fallback - OCR noise tolerate karte hue ----
    value_pattern = re.compile(rule.get("value_regex", rule["regex"]), re.IGNORECASE)
    for image_index, img in enumerate(ocr_result["images"]):
        text = img["full_text"].lower()
        anchor_end, score = _fuzzy_find_keyword_anchor(text, rule["keywords"])
        if anchor_end is not None:
            window = text[anchor_end:anchor_end + VALUE_SEARCH_WINDOW]
            value_match = value_pattern.search(window)
            if value_match:
                display_value = value_match.group(0)
                # bbox dhoondne ke liye keyword + value dono ka context chahiye
                context_snippet = text[max(0, anchor_end - 20):anchor_end] + window[:value_match.end()]
                bbox = find_bounding_box_for_match(context_snippet, img["words"])
                if bbox:
                    bbox["image_index"] = image_index
                return _build_pass_result(rule, display_value, bbox, "fuzzy")

    # Combined text pe bhi fuzzy try karo (multi-photo split case)
    anchor_end, score = _fuzzy_find_keyword_anchor(combined_text, rule["keywords"])
    if anchor_end is not None:
        window = combined_text[anchor_end:anchor_end + VALUE_SEARCH_WINDOW]
        value_match = value_pattern.search(window)
        if value_match:
            return _build_pass_result(rule, value_match.group(0), None, "fuzzy")

    # ---- Genuinely nahi mila ----
    return {
        "rule_id": rule["id"],
        "label": rule["label"],
        "status": "FAIL" if rule["required"] else "WARNING",
        "reason": f"'{rule['label']}' kisi bhi upload ki hui photo mein nahi mili (exact ya approximate match dono try kiya). "
                  f"Expected keywords: {', '.join(rule['keywords'])}",
        "severity": rule["severity"],
        "extracted_value": None,
        "bbox": None,
        "matched_via": None
    }


def run_compliance_check(ocr_result):
    """
    MAIN FUNCTION - isko app.py se call karo.
    ocr_result yahan extract_text_and_boxes_multi() ka output hona chahiye
    (ek ya zyada side-photos ka combined result).
    Har rule ko check karta hai aur ek summary dict return karta hai.

    CATEGORY-AWARE RULES: Kuch declarations sab products ke liye mandatory
    nahi hote, sirf kuch category/condition mein (jaise Country of Origin
    sirf IMPORTED products ke liye mandatory hai). Isliye ek chhota post-pass
    hai jo dekhta hai ki kya koi "becomes_required_if_keywords_present"
    trigger-keyword text mein mila - agar haan, aur wo rule missing nikla,
    toh usko WARNING se FAIL mein upgrade karte hain (kyunki ab yeh
    genuinely mandatory ban gaya hai is specific product ke liye).
    """
    rules = load_rules()
    results = []
    combined_text_lower = ocr_result["full_text"].lower()

    for rule in rules:
        if rule["field"] == "font_size":
            result = check_font_size_rule(rule, ocr_result)
        else:
            result = check_regex_rule(rule, ocr_result)

        # Category-aware upgrade: agar yeh rule conditionally mandatory hai
        # aur trigger-keyword mil gaya, aur yeh field abhi tak missing hai
        trigger_keywords = rule.get("becomes_required_if_keywords_present")
        if trigger_keywords and result["status"] == "WARNING":
            if any(kw in combined_text_lower for kw in trigger_keywords):
                result["status"] = "FAIL"
                result["reason"] = (
                    f"Yeh product IMPORTED lag raha hai (label pe 'imported by' mila), "
                    f"is case mein '{rule['label']}' declare karna mandatory ho jaata hai - "
                    f"lekin yeh nahi mili. " + result["reason"]
                )

        results.append(result)

    total_rules = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warnings = sum(1 for r in results if r["status"] == "WARNING")
    fuzzy_matches = sum(1 for r in results if r.get("matched_via") == "fuzzy")

    compliance_score = round((passed / total_rules) * 100, 1) if total_rules else 0
    overall_status = "COMPLIANT" if failed == 0 else "NON-COMPLIANT"

    return {
        "results": results,
        "total_rules": total_rules,
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "fuzzy_matches": fuzzy_matches,
        "compliance_score": compliance_score,
        "overall_status": overall_status
    }
