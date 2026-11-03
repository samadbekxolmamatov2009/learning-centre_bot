import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

WD_LABELS = {"1": "Du", "2": "Se", "3": "Ch", "4": "Pa", "5": "Ju", "6": "Sh", "7": "Ya"}

COL_HEADERS = ["T/r", "O'quvchining ism-sharifi", "Sinfi", "Kelgan sana", "Tel nomer",
              "Jami to'lov", "To'lagan summasi", "Sana"]
COL_WIDTHS = [Inches(0.5), Inches(2.1), Inches(0.6), Inches(1.1), Inches(1.3),
             Inches(1.1), Inches(1.3), Inches(1.0)]


def _set_col_widths(table):
    """python-docx'da ustun kengligi faqat har bir katakka alohida qo'yilganda ishlaydi,
    shuningdek jadval tartibini 'fixed' qilib qo'yish kerak (aks holda Word o'zi moslashtirib,
    kengliklarni e'tiborsiz qoldiradi)."""
    table.autofit = False
    table.allow_autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.makeelement(qn("w:tblLayout"), {qn("w:type"): "fixed"})
    tbl_pr.append(layout)
    for row in table.rows:
        for cell, w in zip(row.cells, COL_WIDTHS):
            cell.width = w
    for i, w in enumerate(COL_WIDTHS):
        table.columns[i].width = w


def group_roster_docx(group_name, teacher_name, lesson_days, lesson_time, students, extra_rows=6) -> bytes:
    """Guruh ro'yxati (to'lov yig'ish uchun qog'oz shakli): T/r, ism-sharif, sinf, kelgan sana,
    tel, jami to'lov, to'lagan summasi, sana. Oxirgi to'rt ustun bo'sh - qo'lda to'ldiriladi."""
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10)

    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    section.left_margin = section.right_margin = Inches(0.5)
    section.top_margin = section.bottom_margin = Inches(0.5)

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

    total_rows = 1 + len(students) + extra_rows
    table = doc.add_table(rows=total_rows, cols=len(COL_HEADERS))
    table.style = "Table Grid"
    _set_col_widths(table)

    for i, text in enumerate(COL_HEADERS):
        cell = table.cell(0, i)
        cell.text = text
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
    for i, s in enumerate(students, start=1):
        row = table.rows[i].cells
        row[0].text = str(i)
        row[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        row[1].text = f"{s['last_name']} {s['first_name']}"
        row[2].text = str(s.get("grade") or "")
        row[2].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        row[4].text = s.get("phone") or ""

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
