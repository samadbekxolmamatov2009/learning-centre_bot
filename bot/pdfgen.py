import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib import colors

FONT = "Helvetica"
for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
    if os.path.exists(p):
        pdfmetrics.registerFont(TTFont("DejaVu", p))
        FONT = "DejaVu"
        break


def attendance_pdf(group_name, teacher_name, day, rows) -> bytes:
    """rows: [(full_name, grade, phone, status)]  status: present|absent|late|excused"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    st = getSampleStyleSheet()["Normal"]
    st.fontName = FONT
    LABELS = {"present": "Keldi", "absent": "Kelmadi", "late": "Kechikdi", "excused": "Sababli"}
    absent = sum(1 for r in rows if r[3] in ("absent", "excused"))
    data = [["#", "O'quvchi", "Sinf", "Telefon", "Davomat"]]
    for i, (name, grade, phone, present) in enumerate(rows, 1):
        data.append([str(i), name, grade, phone, LABELS.get(present, "Keldi")])
    tbl = Table(data, colWidths=[28, 190, 45, 100, 70])
    style = [("FONTNAME", (0, 0), (-1, -1), FONT),
             ("GRID", (0, 0), (-1, -1), .5, colors.grey),
             ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]
    for i, r in enumerate(rows, 1):
        if r[3] in ("absent", "excused"):
            style.append(("TEXTCOLOR", (0, i), (-1, i), colors.red))
    tbl.setStyle(TableStyle(style))
    doc.build([
        Paragraph(f"Davomat: {group_name}", st), Paragraph(f"Sana: {day}", st),
        Paragraph(f"O'qituvchi: {teacher_name}", st),
        Paragraph(f"Jami: {len(rows)}, kelgan: {len(rows) - absent}, kelmagan: {absent}", st),
        Spacer(1, 12), tbl])
    return buf.getvalue()


def receipt_pdf(center_name, student_name, grade, group_name, amount, month, paid_at,
                 entered_by, receipt_no) -> bytes:
    """To'lov cheki (kvitansiya)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=30 * mm, bottomMargin=30 * mm)
    base = getSampleStyleSheet()["Normal"]
    base.fontName = FONT
    title = ParagraphStyle("title", parent=base, fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=base, fontSize=11, leading=14, alignment=TA_CENTER, textColor=colors.grey,
                         spaceAfter=18)
    big = ParagraphStyle("big", parent=base, fontSize=22, leading=26, alignment=TA_CENTER, spaceBefore=6, spaceAfter=6)
    foot = ParagraphStyle("foot", parent=base, fontSize=9, leading=12, alignment=TA_CENTER, textColor=colors.grey)

    def money(n):
        return f"{int(round(n)):,}".replace(",", " ") + " so'm"

    rows = [
        ["O'quvchi", student_name], ["Sinf", f"{grade}-sinf"], ["Guruh", group_name],
        ["To'lov oyi", month], ["Sana", paid_at], ["Qabul qildi", entered_by],
    ]
    tbl = Table([[r[0], r[1]] for r in rows], colWidths=[120, 300])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.whitesmoke),
    ]))
    doc.build([
        Paragraph(center_name, title),
        Paragraph(f"To'lov cheki №{receipt_no}", sub),
        Spacer(1, 6), tbl, Spacer(1, 10),
        Paragraph(money(amount), big),
        Spacer(1, 30),
        Paragraph("Ushbu chek avtomatik yaratilgan, imzo talab qilinmaydi.", foot),
    ])
    return buf.getvalue()
