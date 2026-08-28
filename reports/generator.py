"""
reports/generator.py
----------------------
Compliance check ke result ko ek PDF report mein convert karta hai, jo
Legal Metrology field inspection reports jaisa structure follow karta hai
(header block with report/officer/premises details, rule-reference checklist
table, recommended action, aur officer/trader signature blocks) - taaki
output officers ko unke existing paperwork jaisa/familiar lage, ek alag/naya
format seekhna na pade.

reportlab library use kar rahe hain - Python mein PDF banane ke liye
sabse standard library hai.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime
import os

# Har rule field ko Legal Metrology (Packaged Commodities) Rules, 2011 ke
# Rule 6 (mandatory declarations) se reference karte hain - officers isi
# rule number se in declarations ko jaante hain, isliye report mein bhi
# yehi reference dikhate hain (general reference, exact sub-clause nahi
# claim karte kyunki woh case-by-case vary kar sakta hai).
RULE_REFERENCE = "Rule 6 (Mandatory Declarations)"


def generate_pdf_report(scan_id, product_name, image_paths, compliance_result, output_path):
    """
    Main function - ek complete PDF report file bana kar output_path pe save karta hai.
    image_paths: list of file paths - product ke ek ya zyada side-photos.
    """
    if isinstance(image_paths, str):
        image_paths = [image_paths]

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm
    )

    styles = getSampleStyleSheet()
    dept_style = ParagraphStyle(
        "DeptStyle", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#555555"), alignment=TA_CENTER
    )
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Heading1"],
        fontSize=15, textColor=colors.HexColor("#1a2b4a"), alignment=TA_CENTER, spaceAfter=2
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceAfter=10
    )
    section_style = ParagraphStyle(
        "SectionStyle", parent=styles["Heading2"],
        fontSize=11.5, textColor=colors.HexColor("#1a2b4a"),
        spaceBefore=14, spaceAfter=6
    )
    caption_style = ParagraphStyle(
        "CaptionStyle", parent=styles["Normal"],
        fontSize=8.5, textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER, spaceAfter=10
    )
    field_label_style = ParagraphStyle(
        "FieldLabel", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#555555")
    )

    elements = []

    # ---------- Header (department-letterhead style) ----------
    elements.append(Paragraph("DEPARTMENT OF CONSUMER AFFAIRS &mdash; LEGAL METROLOGY DIVISION", dept_style))
    elements.append(Paragraph("FIELD INSPECTION REPORT", title_style))
    elements.append(Paragraph(
        "Issued under the Legal Metrology (Packaged Commodities) Rules, 2011",
        subtitle_style
    ))
    elements.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#1a2b4a"), spaceAfter=10))

    # ---------- Report / Officer / Premises details (fillable fields, jaise physical inspection memo mein hote hain) ----------
    report_no = f"SCAN-{scan_id:05d}"
    scan_date = datetime.now().strftime("%d-%m-%Y")
    scan_time = datetime.now().strftime("%H:%M")

    details_data = [
        [Paragraph("Report No.", field_label_style), Paragraph(report_no, field_label_style),
         Paragraph("Date of Inspection", field_label_style), Paragraph(scan_date, field_label_style)],
        [Paragraph("Inspecting Officer", field_label_style), Paragraph("_" * 28, field_label_style),
         Paragraph("Time", field_label_style), Paragraph(scan_time, field_label_style)],
        [Paragraph("Premises / Trader Name", field_label_style), Paragraph("_" * 28, field_label_style),
         Paragraph("Place of Inspection", field_label_style), Paragraph("_" * 20, field_label_style)],
        [Paragraph("Product Examined", field_label_style), Paragraph(product_name, field_label_style),
         Paragraph("Photos Submitted", field_label_style), Paragraph(str(len(image_paths)), field_label_style)],
    ]
    details_table = Table(details_data, colWidths=[95, 155, 95, 105])
    details_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#eeeeee")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 10))

    # ---------- Overall finding (bada, ek-nazar-mein-dikhne-wala verdict) ----------
    status_color = colors.HexColor("#1a7f37") if compliance_result["overall_status"] == "COMPLIANT" else colors.HexColor("#c1121f")
    verdict_style = ParagraphStyle(
        "VerdictStyle", parent=styles["Normal"], fontSize=12, textColor=status_color,
        fontName="Helvetica-Bold", alignment=TA_CENTER
    )
    action_text = (
        "No further action required based on automated check."
        if compliance_result["overall_status"] == "COMPLIANT"
        else "Recommended action: issue notice for missing/incorrect declarations; manual re-verification advised."
    )
    verdict_table = Table([[
        Paragraph(f"OVERALL FINDING: {compliance_result['overall_status']}  "
                  f"({compliance_result['compliance_score']}% of {compliance_result['total_rules']} declarations verified)", verdict_style)
    ]], colWidths=[450])
    verdict_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f7f1") if compliance_result["overall_status"] == "COMPLIANT" else colors.HexColor("#fdeceb")),
        ("BOX", (0, 0), (-1, -1), 0.75, status_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(verdict_table)
    elements.append(Paragraph(action_text, ParagraphStyle("action", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceBefore=4, spaceAfter=10)))

    # ---------- Product images (all uploaded sides) ----------
    valid_image_paths = [p for p in image_paths if p and os.path.exists(p)]
    if valid_image_paths:
        elements.append(Paragraph("Photographic Evidence", section_style))
        thumb_w = 78 * mm
        row_cells = []
        row_captions = []
        img_rows = []
        for idx, path in enumerate(valid_image_paths):
            try:
                img = Image(path, width=thumb_w, height=thumb_w, kind='proportional')
            except Exception:
                continue
            row_cells.append(img)
            row_captions.append(Paragraph(f"Side {idx + 1}", caption_style))
            if len(row_cells) == 2:
                img_rows.append(row_cells)
                img_rows.append(row_captions)
                row_cells, row_captions = [], []
        if row_cells:
            row_cells.append("")
            row_captions.append("")
            img_rows.append(row_cells)
            img_rows.append(row_captions)

        if img_rows:
            img_table = Table(img_rows, colWidths=[thumb_w, thumb_w])
            img_table.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(img_table)

    # ---------- Declaration checklist (rule-reference style, jaisa officers ka existing checklist hota hai) ----------
    elements.append(Paragraph("Mandatory Declaration Checklist", section_style))

    table_data = [["#", "Rule Ref.", "Declaration", "Status", "Remarks"]]
    rule_ref_style = ParagraphStyle("ruleref", fontSize=7.5, leading=9.5)
    declaration_style = ParagraphStyle("declaration", fontSize=7.5, leading=9.5, fontName="Helvetica-Bold")
    for i, r in enumerate(compliance_result["results"], start=1):
        remark_text = r["reason"]
        if r.get("matched_via") == "fuzzy":
            remark_text = "[Verify] " + remark_text
        table_data.append([
            str(i),
            Paragraph(RULE_REFERENCE, rule_ref_style),
            Paragraph(r["label"], declaration_style),
            r["status"],
            Paragraph(remark_text, ParagraphStyle("cell", fontSize=7.5, leading=9.5))
        ])

    detail_table = Table(table_data, colWidths=[16, 62, 105, 45, 222], repeatRows=1)
    style_commands = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2b4a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, r in enumerate(compliance_result["results"], start=1):
        if r["status"] == "PASS":
            style_commands.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#1a7f37")))
        elif r["status"] == "FAIL":
            style_commands.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#c1121f")))
        else:
            style_commands.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#b45309")))
        style_commands.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))

    detail_table.setStyle(TableStyle(style_commands))
    elements.append(detail_table)
    elements.append(Spacer(1, 22))

    # ---------- Signature blocks (jaisa physical inspection memos mein hota hai) ----------
    sig_style = ParagraphStyle("sig", parent=styles["Normal"], fontSize=8.5, textColor=colors.HexColor("#555555"))
    sig_table = Table([
        [Paragraph("_" * 32, sig_style), Paragraph("_" * 32, sig_style)],
        [Paragraph("Inspecting Officer &mdash; Signature &amp; Date", sig_style),
         Paragraph("Trader / Representative &mdash; Signature &amp; Date", sig_style)],
    ], colWidths=[225, 225])
    sig_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(sig_table)
    elements.append(Spacer(1, 14))

    # ---------- Footer note ----------
    footer_style = ParagraphStyle(
        "FooterStyle", parent=styles["Normal"], fontSize=7.5,
        textColor=colors.HexColor("#888888")
    )
    elements.append(Paragraph(
        "Disclaimer: This report is auto-generated by a prototype OCR-based compliance-checking system "
        "(built for Smart India Hackathon, PS 26034). Rows marked [Verify] were matched using approximate "
        "(fuzzy) text matching to tolerate minor OCR reading errors and should be visually confirmed against "
        "the photographs above. The font-size/readability check is a pixel-ratio heuristic, not a calibrated "
        "physical measurement. This report supplements, and does not replace, manual verification by an "
        "authorised Legal Metrology Officer.",
        footer_style
    ))

    doc.build(elements)
    return output_path
