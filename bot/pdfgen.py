import io
import os

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

FONT = "Helvetica"
for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
    if os.path.exists(p):
        pdfmetrics.registerFont(TTFont("DejaVu", p))
        FONT = "DejaVu"
        break


def attendance_pdf(group_name, teacher_name, day, rows) -> bytes:
    """rows: [(full_name, grade, phone, present_bool)]"""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    st = getSampleStyleSheet()["Normal"]
    st.fontName = FONT
    absent = sum(1 for r in rows if not r[3])
    data = [["#", "O'quvchi", "Sinf", "Telefon", "Davomat"]]
    for i, (name, grade, phone, present) in enumerate(rows, 1):
        data.append([str(i), name, grade, phone, "Keldi" if present else "Kelmadi"])
    tbl = Table(data, colWidths=[28, 190, 45, 100, 70])
    style = [("FONTNAME", (0, 0), (-1, -1), FONT),
             ("GRID", (0, 0), (-1, -1), .5, colors.grey),
             ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]
    for i, r in enumerate(rows, 1):
        if not r[3]:
            style.append(("TEXTCOLOR", (0, i), (-1, i), colors.red))
    tbl.setStyle(TableStyle(style))
    doc.build([
        Paragraph(f"Davomat: {group_name}", st), Paragraph(f"Sana: {day}", st),
        Paragraph(f"O'qituvchi: {teacher_name}", st),
        Paragraph(f"Jami: {len(rows)}, kelgan: {len(rows) - absent}, kelmagan: {absent}", st),
        Spacer(1, 12), tbl])
    return buf.getvalue()
