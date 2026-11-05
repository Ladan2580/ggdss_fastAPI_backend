import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

from ..database import db
from ..dependencies import require_roles
from ..helpers import oid

router = APIRouter(prefix="/exports", tags=["exports"])
ADMIN_ROLES = ("super_admin", "school_admin")

# ── Column definition shared by CSV / XLSX / PDF ─────────────────
COLUMNS = [
    "S/N",
    "Admission No",
    "Full Name",
    "Assignment",
    "1st CA",
    "2nd CA",
    "Exam",
]


async def _get_rows(session_id: str, class_id: str, arm_id: str | None):
    session = await db.sessions.find_one({"_id": oid(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cls = await db.classes.find_one({"_id": oid(class_id)})
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")

    arm = await db.arms.find_one({"_id": oid(arm_id)}) if arm_id else None

    flt = {"status": "active", "class_id": oid(class_id)}
    if arm_id:
        flt["arm_id"] = oid(arm_id)
    students = await db.students.find(flt).sort("full_name", 1).to_list(5000)

    rows = [
        {
            "sno": i,
            "admission_no": s.get("admission_no", ""),
            "full_name": s.get("full_name", ""),
            "assignment": "",
            "first_ca": "",
            "second_ca": "",
            "exam": "",
        }
        for i, s in enumerate(students, start=1)
    ]
    return rows, session, cls, arm


def _filename_base(cls, arm, session) -> str:
    def clean(x):
        return (x or "").replace("/", "-").replace(" ", "_").strip("_")

    base = (
        f"GDSS_Tudun_Wada_{clean(cls['name'])}"
        f"_Student_List_{clean(session['name'])}"
    )
    if arm:
        base += f"_{clean(arm['name'])}"
    return base


def _row_values(r) -> list:
    return [
        r["sno"],
        r["admission_no"],
        r["full_name"],
        r["assignment"],
        r["first_ca"],
        r["second_ca"],
        r["exam"],
    ]


# ════════════════════════════════════════════════════════════════
# CSV
# ════════════════════════════════════════════════════════════════
def _to_csv(rows) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for r in rows:
        writer.writerow(_row_values(r))
    return buf.getvalue().encode("utf-8-sig")  # BOM → Excel-friendly


# ════════════════════════════════════════════════════════════════
# XLSX
# ════════════════════════════════════════════════════════════════
def _to_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Students"

    header_fill = PatternFill("solid", fgColor="E4EEE7")
    header_font = Font(bold=True, color="5E8570")
    thin = Side(style="thin", color="DCE5DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for r in rows:
        ws.append(_row_values(r))
        for cell in ws[ws.max_row]:
            cell.border = border

    widths = {"A": 6, "B": 18, "C": 28, "D": 12, "E": 10, "F": 10, "G": 10}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws.column_dimensions["B"].number_format = "@"  # keep admission no as text

    stream = io.BytesIO()
    wb.save(stream)
    return stream.getvalue()


# ════════════════════════════════════════════════════════════════
# PDF  (report-card-grade soft design)
# ════════════════════════════════════════════════════════════════
INK        = colors.HexColor("#2E3A34")
MUTED      = colors.HexColor("#7A8C82")
SAGE       = colors.HexColor("#A8C3B0")
SAGE_DEEP  = colors.HexColor("#5E8570")
SAGE_TINT  = colors.HexColor("#F2F7F3")
SAGE_PALE  = colors.HexColor("#E4EEE7")
GOLD       = colors.HexColor("#D9C48A")
GOLD_PALE  = colors.HexColor("#FBF6EA")
LINE       = colors.HexColor("#DCE5DE")
WHITE      = colors.white


def _pdf_style(name, **kw):
    base = dict(
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=INK, alignment=0,
    )
    base.update(kw)
    return ParagraphStyle(name, **base)


def _find_logo():
    p = Path(__file__).resolve().parent.parent / "assets" / "school_logo.jpeg"
    return RLImage(str(p), width=2.0 * cm, height=2.0 * cm,
                   kind="proportional") if p.exists() else ""


def _to_pdf(rows, cls, arm, session) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.2 * cm,
        title="Student List",
        author="Government Girls Day Secondary School",
    )

    # ── Styles ─────────────────────────────────────────────
    school_title = _pdf_style(
        "SchoolTitle", fontName="Helvetica-Bold",
        fontSize=14, leading=17, textColor=SAGE_DEEP,
        alignment=TA_CENTER, charSpace=1,
    )
    school_sub = _pdf_style(
        "SchoolSub", fontSize=8, leading=11,
        textColor=MUTED, alignment=TA_CENTER,
    )
    class_line = _pdf_style(
        "ClassLine", fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=SAGE_DEEP,
        alignment=TA_CENTER, charSpace=0.5,
    )
    gen_line = _pdf_style(
        "GenLine", fontSize=8, textColor=MUTED, alignment=TA_CENTER,
    )
    tbl_header = _pdf_style(
        "TblHeader", fontName="Helvetica-Bold",
        fontSize=8, leading=10, textColor=SAGE_DEEP,
        alignment=TA_CENTER,
    )
    tbl_body = _pdf_style("TblBody", fontSize=8.5, leading=12)
    tbl_center = _pdf_style(
        "TblCenter", fontSize=8.5, leading=12, alignment=TA_CENTER,
    )

    def safe(v):
        return escape(str(v)) if v not in (None, "") else ""

    # ── Header block ───────────────────────────────────────
    logo = _find_logo()
    school_details = [
        Paragraph("GOVERNMENT GIRLS DAY SECONDARY SCHOOL", school_title),
        Paragraph("Tudun Wada, Birnin Kebbi, Kebbi State, Nigeria", school_sub),
        Paragraph(
            "Educating the Girl Child for a Brighter Future",
            _pdf_style("Motto", fontName="Helvetica-Oblique",
                       fontSize=8.5, textColor=SAGE_DEEP,
                       alignment=TA_CENTER),
        ),
    ]

    header = Table([[logo, school_details]], colWidths=[2.6 * cm, 24 * cm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (0, 0), (0, 0),  "CENTER"),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LINEABOVE",  (0, 0), (-1, 0),  0.8, SAGE),
        ("LINEBELOW",  (0, 0), (-1, -1), 0.8, GOLD),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 9),
    ]))

    arm_label = f" ({safe(arm['name'])})" if arm else ""
    sub_title = Table(
        [[Paragraph(
            f"{safe(cls['name'])}{arm_label} — {safe(session['name'])}",
            class_line,
        )]],
        colWidths=[26.6 * cm],
    )
    sub_title.setStyle(TableStyle([
        ("BOX",         (0, 0), (-1, -1), 0.6, GOLD),
        ("BACKGROUND",  (0, 0), (-1, -1), GOLD_PALE),
        ("TOPPADDING",  (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 9),
    ]))

    story = [
        header,
        Spacer(1, 0.4 * cm),
        sub_title,
        Spacer(1, 6),
        Paragraph(
            f"Generated: {datetime.now().strftime('%d %b %Y')}",
            gen_line,
        ),
        Spacer(1, 0.4 * cm),
    ]

    # ── Students table ─────────────────────────────────────
    tdata = [[Paragraph(c, tbl_header) for c in COLUMNS]]
    for r in rows:
        tdata.append([
            Paragraph(str(r["sno"]), tbl_center),
            Paragraph(safe(r["admission_no"]), tbl_body),
            Paragraph(safe(r["full_name"]), tbl_body),
            Paragraph("", tbl_center),   # Assignment  (blank)
            Paragraph("", tbl_center),   # 1st CA      (blank)
            Paragraph("", tbl_center),   # 2nd CA      (blank)
            Paragraph("", tbl_center),   # Exam        (blank)
        ])

    table = Table(
        tdata,
        colWidths=[1.4 * cm, 4.0 * cm, 8.6 * cm,
                   3.0 * cm, 3.0 * cm, 3.0 * cm, 3.0 * cm],
        repeatRows=1,
        hAlign="CENTER",
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SAGE_PALE),
        ("TEXTCOLOR",  (0, 0), (-1, 0), SAGE_DEEP),

        # header underline
        ("LINEBELOW",  (0, 0), (-1, 0), 1.0, SAGE),
        # row separators
        ("LINEBELOW",  (0, 1), (-1, -1), 0.35, LINE),
        # ── vertical column separators ────────────────────
        ("LINEBEFORE", (1, 0), (-1, -1), 0.35, LINE),

        ("BOX",        (0, 0), (-1, -1), 0.6, SAGE),

        # cream tint on the three blank score columns
        ("BACKGROUND", (3, 1), (6, -1), GOLD_PALE),

        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (0, 0), (0, -1), "CENTER"),
        ("ALIGN",      (3, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
    ]))

    story.append(table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Footer ─────────────────────────────────────────────
    footer = Table(
        [[Paragraph(
            "DISCIPLINE   ·   HARD WORK   ·   EXCELLENCE",
            _pdf_style("Footer", fontName="Helvetica-Bold",
                       fontSize=8.5, textColor=MUTED,
                       alignment=TA_CENTER, charSpace=2.5),
        )]],
        colWidths=[26.6 * cm],
    )
    footer.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, GOLD),
        ("TOPPADDING",   (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 9),
    ]))
    story.append(footer)

    doc.build(story)
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════
# ROUTE
# ════════════════════════════════════════════════════════════════
@router.get("/students")
async def export_students(
    session_id: str,
    class_id: str,
    arm_id: str | None = None,
    format: str = "csv",
    _=Depends(require_roles(*ADMIN_ROLES)),
):
    rows, session, cls, arm = await _get_rows(session_id, class_id, arm_id)
    base = _filename_base(cls, arm, session)
    format = format.lower()

    if format == "csv":
        content, media, ext = _to_csv(rows), "text/csv", "csv"
    elif format == "xlsx":
        content = _to_xlsx(rows)
        media = (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
        ext = "xlsx"
    elif format == "pdf":
        content = _to_pdf(rows, cls, arm, session)
        media = "application/pdf"
        ext = "pdf"
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")

    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{base}.{ext}"'},
    )