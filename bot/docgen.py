import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

WD_LABELS = {"1": "Du", "2": "Se", "3": "Ch", "4": "Pa", "5": "Ju", "6": "Sh", "7": "Ya"}


def group_roster_docx(group_name, teacher_name, lesson_days, lesson_time, students, extra_rows=6) -> bytes:
    """Guruh ro'yxati (to'lov yig'ish uchun qog'oz shakli): T/r, ism-sharif, sinf, kelgan sana,
    tel, jami to'lov, to'lagan summasi, sana. Oxirgi to'rt ustun bo'sh - qo'lda to'ldiriladi."""
    doc = Document()
    days_label = ", ".join(WD_LABELS[d] for d in (lesson_days or "").split(",") if d in WD_LABELS)
    parts = [group_name]
    if teacher_name:
        parts.append(teacher_name)
    if days_label:
        parts.append(days_label)
    if lesson_time:
        parts.append(lesson_time)
    heading = doc.add_heading(" — ".join(parts), level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

    headers = ["T/r", "O'quvchining ism-sharifi", "Sinfi", "Kelgan sana", "Tel nomer",
              "Jami to'lov", "To'lagan summasi", "Sana"]
    total_rows = 1 + len(students) + extra_rows
    table = doc.add_table(rows=total_rows, cols=len(headers))
    table.style = "Table Grid"
    for i, text in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = text
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
    for i, s in enumerate(students, start=1):
        row = table.rows[i].cells
        row[0].text = str(i)
        row[1].text = f"{s['last_name']} {s['first_name']}"
        row[2].text = str(s.get("grade") or "")
        row[4].text = s.get("phone") or ""

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
