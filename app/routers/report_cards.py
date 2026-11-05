from fastapi import APIRouter, Depends, HTTPException, Response
from datetime import datetime, timezone
from io import BytesIO
import os
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
)

from ..database import db
from ..dependencies import require_roles
from ..helpers import oid, grade_for
from .results import get_grading, _build_class_results

router = APIRouter(prefix="/report-cards", tags=["report-cards"])
ALLOWED = ("super_admin", "school_admin", "teacher")


# ============================================================
# HELPERS
# ============================================================
def _coerce_objectid(value):
    """Return a bson.ObjectId from various shapes, else None."""
    if value is None:
        return None
    try:
        from bson import ObjectId
    except ImportError:
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, dict):
        if "$oid" in value:
            try:
                return ObjectId(str(value["$oid"]))
            except Exception:
                return None
        if "_id" in value:
            return _coerce_objectid(value["_id"])
        return None
    if isinstance(value, str):
        s = value.strip()
        if len(s) == 24:
            try:
                return ObjectId(s)
            except Exception:
                return None
    return None


def _extract_arm_ref(doc: dict):
    """Return the first plausible arm reference found in a document."""
    if not isinstance(doc, dict):
        return None
    for key in ("arm_id", "arm", "arms", "arm_object_id", "armId"):
        if doc.get(key) is not None:
            return doc.get(key)
    return None


# ============================================================
# DATA BUILDING
# ============================================================
async def _build_card(
    session_id: str,
    class_id: str,
    student_id: str,
    arm_id: str | None = None,
):
    student = await db.students.find_one({"_id": oid(student_id)})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    session = await db.sessions.find_one({"_id": oid(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cls = await db.classes.find_one({"_id": oid(class_id)})

    # ---- Resolve arm: query param wins, else pull from student doc ----
    effective_arm_ref = arm_id or _extract_arm_ref(student)
    effective_arm_oid = _coerce_objectid(effective_arm_ref)
    arm = await db.arms.find_one({"_id": effective_arm_oid}) if effective_arm_oid else None

    if os.environ.get("REPORT_CARD_DEBUG"):
        print(
            f"[_build_card] student_arm_ref={effective_arm_ref!r} "
            f"arm_oid={effective_arm_oid!r} arm_doc={arm!r}",
            file=sys.stderr,
        )

    rules = await get_grading()
    flt = {
        "session_id": oid(session_id),
        "class_id": oid(class_id),
        "student_id": oid(student_id),
        "status": "published",
    }
    subject_results = await db.subject_results.find(flt).to_list(200)
    subject_map = {
        str(s["_id"]): s["name"]
        for s in await db.subjects.find({}).to_list(500)
    }

    subjects_out = []
    total = 0
    passed = 0
    failed = 0
    for r in subject_results:
        complete = None not in (
            r.get("assignment"),
            r.get("first_ca"),
            r.get("second_ca"),
            r.get("exam"),
        )
        t = (
            r["assignment"] + r["first_ca"] + r["second_ca"] + r["exam"]
            if complete
            else None
        )
        grade, remark = grade_for(t, rules) if t is not None else (None, None)
        if t is not None:
            total += t
            if t >= 40:
                passed += 1
            else:
                failed += 1
        subjects_out.append({
            "subject_id": str(r["subject_id"]),
            "subject_name": subject_map.get(str(r["subject_id"]), ""),
            "assignment": r.get("assignment"),
            "first_ca": r.get("first_ca"),
            "second_ca": r.get("second_ca"),
            "exam": r.get("exam"),
            "total": t,
            "grade": grade,
            "remark": remark,
        })

    offered = passed + failed
    average = round(total / offered, 2) if offered else 0

    try:
        class_rows = await _build_class_results(
            session_id, class_id, arm_id, include_unapproved=False
        )
        pos = next(
            (r["position"] for r in class_rows if r["student_id"] == student_id),
            None,
        )
    except Exception:
        pos = None

    # Build arm payload — never lose it, even if lookup failed
    arm_out = {
        "arm_id": str(effective_arm_oid) if effective_arm_oid else None,
        "arm_name": (arm["name"] if arm and arm.get("name") else None),
    }

    return {
        "student": {
            "id": str(student["_id"]),
            "full_name": student.get("full_name"),
            "admission_no": student.get("admission_no"),
            "gender": student.get("gender"),
            "arm_id": arm_out["arm_id"],
            "arm_name": arm_out["arm_name"],
            # keep raw ref too, in case the renderer wants to re-resolve
            "arm_ref": str(effective_arm_oid) if effective_arm_oid else None,
        },
        "session_name": session["name"],
        "term": session["term"],
        "class_name": cls["name"] if cls else "",
        "arm_id": arm_out["arm_id"],
        "arm_name": arm_out["arm_name"],
        "subjects": subjects_out,
        "summary": {
            "total_score": total,
            "average": average,
            "position": pos,
            "passed": passed,
            "failed": failed,
        },
        "comments": {"class_teacher": "", "principal": ""},
        "attendance": None,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================
# ROUTES
# ============================================================
@router.get("")
async def get_report_card(
    session_id: str,
    class_id: str,
    student_id: str,
    arm_id: str | None = None,
    _=Depends(require_roles(*ALLOWED)),
):
    return await _build_card(session_id, class_id, student_id, arm_id)


@router.get("/pdf")
async def get_report_card_pdf(
    session_id: str,
    class_id: str,
    student_id: str,
    arm_id: str | None = None,
    _=Depends(require_roles(*ALLOWED)),
):
    data = await _build_card(session_id, class_id, student_id, arm_id)
    return _render_card_pdf(data)


# ============================================================
# PDF RENDERER
# ============================================================
def _render_card_pdf(data: dict):
    """Render a student report card as a PDF; class label includes arm (JSS1A)."""

    # ---------------- palette ----------------
    INK       = colors.HexColor("#2E3A34")
    MUTED     = colors.HexColor("#7A8C82")
    SAGE      = colors.HexColor("#A8C3B0")
    SAGE_DEEP = colors.HexColor("#5E8570")
    SAGE_TINT = colors.HexColor("#F2F7F3")
    SAGE_PALE = colors.HexColor("#E4EEE7")
    GOLD      = colors.HexColor("#D9C48A")
    GOLD_PALE = colors.HexColor("#FBF6EA")
    LINE      = colors.HexColor("#DCE5DE")
    WHITE     = colors.white

    # ---------------- auto-remark ----------------
    _REMARK_BANDS = [
        (90, 100,
         "An outstanding performance. Keep up the excellent work.",
         "Excellent result. You are a credit to the school — sustain this standard."),
        (80, 89.99,
         "A very good result. Aim even higher next term.",
         "Very good performance. With a little more effort you can reach the top."),
        (70, 79.99,
         "A good result. There is clear room for improvement.",
         "Good performance. Stay focused and your grades will rise further."),
        (60, 69.99,
         "A fair result. More consistency at home and in class is needed.",
         "Fair performance. Greater discipline and study habits will yield better results."),
        (50, 59.99,
         "A pass, but effort must improve significantly next term.",
         "You have passed, but much more commitment is expected. Work harder."),
        (40, 49.99,
         "Below average. Serious improvement is required.",
         "Unsatisfactory. You must take your studies far more seriously."),
        (0, 39.99,
         "A weak result. Immediate and sustained effort is essential.",
         "Poor performance. This is unacceptable — a complete change of attitude is required."),
    ]

    def _auto_remark(average, role: str = "teacher") -> str:
        try:
            avg = float(average)
        except (TypeError, ValueError):
            return ""
        for lo, hi, teacher_r, principal_r in _REMARK_BANDS:
            if lo <= avg <= hi:
                return teacher_r if role == "teacher" else principal_r
        return ""

    # ---------------- arm resolution ----------------
    def _resolve_arm_name() -> str:
        """Get the arm name ('A', 'B', ...) from data, student, or db."""
        student = data.get("student") or {}

        # 1) Explicit names
        for v in (
            data.get("arm_name"),
            student.get("arm_name") if isinstance(student, dict) else None,
        ):
            if isinstance(v, str) and v.strip():
                return v.strip().upper()

        # 2) Any ObjectId-shaped reference
        candidates = [
            data.get("arm_id"),
            data.get("arm_ref"),
            student.get("arm_id") if isinstance(student, dict) else None,
            student.get("arm_ref") if isinstance(student, dict) else None,
        ]
        for c in candidates:
            arm_oid = _coerce_objectid(c)
            if arm_oid is not None:
                try:
                    doc = db["arms"].find_one({"_id": arm_oid})
                    if doc and doc.get("name"):
                        return str(doc["name"]).strip().upper()
                except Exception as exc:
                    if os.environ.get("REPORT_CARD_DEBUG"):
                        print(f"[report_card] arms query error: {exc}", file=sys.stderr)

        # 3) Re-fetch student directly from Mongo (last resort)
        if isinstance(student, dict) and student.get("id"):
            try:
                from bson import ObjectId
                fresh = db["students"].find_one({"_id": ObjectId(student["id"])})
                if fresh:
                    ref = _extract_arm_ref(fresh)
                    arm_oid = _coerce_objectid(ref)
                    if arm_oid is not None:
                        doc = db["arms"].find_one({"_id": arm_oid})
                        if doc and doc.get("name"):
                            return str(doc["name"]).strip().upper()
                    if fresh.get("arm_name"):
                        return str(fresh["arm_name"]).strip().upper()
            except Exception as exc:
                if os.environ.get("REPORT_CARD_DEBUG"):
                    print(f"[report_card] student re-fetch error: {exc}", file=sys.stderr)

        return ""

    def _class_with_arm() -> str:
        """'JSS1' + 'A' → 'JSS1A'."""
        cls = str(data.get("class_name", "")).replace(" ", "").upper()
        arm = _resolve_arm_name()

        if os.environ.get("REPORT_CARD_DEBUG"):
            print(f"[report_card] class_name={cls!r} arm_name={arm!r}", file=sys.stderr)

        if not arm:
            return cls or "—"
        if len(arm) <= 2 and arm.isalpha():
            return f"{cls}{arm}" if cls else arm
        return arm if not cls else f"{cls} {arm}"

    def _resolve_date() -> str:
        supplied = data.get("date")
        if supplied not in (None, "", "—"):
            return str(supplied)
        return datetime.now().strftime("%d %B %Y")

    # ---------------- document ----------------
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.0 * cm,
        leftMargin=1.0 * cm,
        topMargin=0.6 * cm,
        bottomMargin=0.8 * cm,
        title="Student Report Card",
        author="Government Girls Day Secondary School",
    )
    story = []

    # ---------------- styles ----------------
    def style(name, **kw):
        base = dict(
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=INK,
            alignment=0,
        )
        base.update(kw)
        return ParagraphStyle(name, **base)

    school_title   = style("SchoolTitle", fontName="Helvetica-Bold",
                           fontSize=15, leading=18, textColor=SAGE_DEEP,
                           alignment=TA_CENTER, charSpace=1)
    school_address = style("SchoolAddress", fontSize=9, leading=11,
                           textColor=MUTED, alignment=TA_CENTER)
    motto_style    = style("Motto", fontName="Helvetica-Oblique",
                           fontSize=9.5, leading=12, textColor=SAGE_DEEP,
                           alignment=TA_CENTER)
    card_title     = style("CardTitle", fontName="Helvetica-Bold",
                           fontSize=14, leading=17, textColor=SAGE_DEEP,
                           alignment=TA_CENTER, charSpace=2.5)
    section_style  = style("Section", fontName="Helvetica-Bold",
                           fontSize=9, leading=12, textColor=SAGE_DEEP,
                           charSpace=1)
    info_value     = style("InfoValue", fontSize=10, leading=13)
    table_header   = style("TableHeader", fontName="Helvetica-Bold",
                           fontSize=8, leading=10, textColor=SAGE_DEEP,
                           alignment=TA_CENTER)
    table_body     = style("TableBody", fontSize=9, leading=11)
    table_center   = style("TableCenter", fontSize=9, leading=11,
                           alignment=TA_CENTER)
    remark_text    = style("RemarkText", fontName="Helvetica-Oblique",
                           fontSize=9.5, leading=12)
    signature      = style("Signature", fontName="Helvetica-Bold",
                           fontSize=9, leading=11, textColor=MUTED,
                           alignment=TA_CENTER, charSpace=1)
    footer_style   = style("Footer", fontName="Helvetica-Bold",
                           fontSize=9, leading=11, textColor=MUTED,
                           alignment=TA_CENTER, charSpace=2.5)

    def safe(value):
        return escape(str(value)) if value not in (None, "") else "—"

    def panel(flowables, width=18, bg=WHITE, border=SAGE,
              pad_top=7, pad_bottom=7, pad_lr=10, spine=None):
        t = Table([[flowables]], colWidths=[width * cm])
        rules = [
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX",        (0, 0), (-1, -1), 0.6, border),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), pad_lr),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad_lr),
            ("TOPPADDING",   (0, 0), (-1, -1), pad_top),
            ("BOTTOMPADDING",(0, 0), (-1, -1), pad_bottom),
        ]
        if spine:
            rules.append(("LINEBEFORE", (0, 0), (0, 0), 3, spine))
        t.setStyle(TableStyle(rules))
        return t

    # ---------------- header ----------------
    logo_path = (
        Path(__file__).resolve().parent.parent / "assets" / "school_logo.jpeg"
    )
    logo = ""
    if logo_path.exists():
        logo = RLImage(str(logo_path), width=2.6 * cm, height=2.6 * cm,
                       kind="proportional")

    school_details = [
        Paragraph("GOVERNMENT GIRLS DAY SECONDARY SCHOOL", school_title),
        Paragraph("Tudun Wada, Birnin Kebbi, Kebbi State, Nigeria",
                  school_address),
        Spacer(1, 3),
        Paragraph("Educating the Girl Child for a Brighter Future",
                  motto_style),
    ]
    header = Table([[logo, school_details]], colWidths=[3.2 * cm, 14.8 * cm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (0, 0), (0, 0),  "CENTER"),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LINEABOVE",  (0, 0), (-1, 0),  0.8, SAGE),
        ("LINEBELOW",  (0, 0), (-1, -1), 0.8, GOLD),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story += [header, Spacer(1, 0.35 * cm)]

    # ---------------- title ----------------
    story.append(panel(
        Paragraph("STUDENTS REPORT CARD", card_title),
        pad_top=10, pad_bottom=10, border=GOLD,
    ))
    story.append(Spacer(1, 0.35 * cm))

    # ---------------- student info ----------------
    student = data["student"]
    date_label = safe(_resolve_date())
    class_label = safe(_class_with_arm())      # e.g. JSS1A

    def info_cell(label, value):
        return Paragraph(
            f'<font color="#7A8C82" size="7"><b>{label}</b></font><br/>'
            f'<font color="#2E3A34" size="9.5">{value}</font>',
            info_value,
        )

    info_rows = [
        [
            info_cell("STUDENT NAME", f"<b>{safe(student.get('full_name'))}</b>"),
            info_cell("ACADEMIC SESSION",
                      f"<b>{safe(data.get('session_name'))}</b>"),
        ],
        [
            info_cell("ADMISSION NUMBER", safe(student.get("admission_no"))),
            info_cell("TERM", safe(data.get("term"))),
        ],
        [
            info_cell("CLASS", f"<b>{class_label}</b>"),
            info_cell("DATE ISSUED", f"<b>{date_label}</b>"),
        ],
    ]

    info_table = Table(info_rows, colWidths=[9 * cm, 9 * cm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SAGE_TINT),
        ("BOX",       (0, 0), (-1, -1), 0.6, SAGE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story += [info_table, Spacer(1, 0.4 * cm)]

    # ---------------- marks table ----------------
    headers = ["SUBJECT", "ASSIGN. (10)", "1ST CA (10)", "2ND CA (10)",
               "EXAM  (70)", "TOTAL (100)", "GRADE", "REMARK"]
    rows = [[Paragraph(h, table_header) for h in headers]]
    for s in data.get("subjects", []):
        rows.append([
            Paragraph(safe(s.get("subject_name")), table_body),
            Paragraph(safe(s.get("assignment")), table_center),
            Paragraph(safe(s.get("first_ca")), table_center),
            Paragraph(safe(s.get("second_ca")), table_center),
            Paragraph(safe(s.get("exam")), table_center),
            Paragraph(f"<b>{safe(s.get('total'))}</b>", table_center),
            Paragraph(f"<b>{safe(s.get('grade'))}</b>", table_center),
            Paragraph(safe(s.get("remark")), table_center),
        ])

    marks_table = Table(
        rows,
        colWidths=[4.2 * cm, 1.7 * cm, 1.6 * cm, 1.6 * cm,
                   1.7 * cm, 1.7 * cm, 1.6 * cm, 1.9 * cm],
        repeatRows=1,
        hAlign="CENTER",
    )
    marks_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SAGE_PALE),
        ("TEXTCOLOR",  (0, 0), (-1, 0), SAGE_DEEP),
        ("LINEBELOW",  (0, 0), (-1, 0), 1.0, SAGE),
        ("LINEBELOW",  (0, 1), (-1, -1), 0.35, LINE),
        ("BOX",        (0, 0), (-1, -1), 0.6, SAGE),
        ("BACKGROUND", (5, 1), (6, -1), GOLD_PALE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",  (1, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
    ]))
    story += [marks_table, Spacer(1, 0.4 * cm)]

    # ---------------- summary ----------------
    summary = data.get("summary", {})
    summary_items = [
        ("TOTAL SCORE", summary.get("total_score", "—")),
        ("AVERAGE",     summary.get("average", "—")),
        ("POSITION",    summary.get("position") or "—"),
        ("PASSED",      summary.get("passed", 0)),
        ("FAILED",      summary.get("failed", 0)),
    ]
    summary_cells = [
        Paragraph(
            f'<font color="#7A8C82" size="7"><b>{label}</b></font><br/>'
            f'<font color="#2E3A34" size="13"><b>{safe(value)}</b></font>',
            ParagraphStyle(
                f"Sum_{i}",
                fontName="Helvetica-Bold",
                leading=16,
                alignment=TA_CENTER,
            ),
        )
        for i, (label, value) in enumerate(summary_items)
    ]
    summary_table = Table([summary_cells], colWidths=[3.6 * cm] * 5)
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SAGE_TINT),
        ("INNERGRID",  (0, 0), (-1, -1), 0.4, LINE),
        ("BOX",        (0, 0), (-1, -1), 0.6, SAGE),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [summary_table, Spacer(1, 0.4 * cm)]

    # ---------------- remarks ----------------
    average_value = summary.get("average")
    teacher_remark = data.get(
        "teacher_remark",
        summary.get("teacher_remark")
        or _auto_remark(average_value, "teacher"),
    )
    principal_remark = data.get(
        "principal_remark",
        summary.get("principal_remark")
        or _auto_remark(average_value, "principal"),
    )

    def remark_panel(title, text, bg, border, spine):
        content = [
            Paragraph(title, section_style),
            Spacer(1, 5),
            Paragraph(
                safe(text) if text else "______________________________",
                remark_text,
            ),
        ]
        return panel(
            content,
            width=8.7, bg=bg, border=border, spine=spine,
            pad_top=10, pad_bottom=14, pad_lr=10,
        )

    teacher_panel = remark_panel(
        "CLASS TEACHER'S REMARKS", teacher_remark,
        bg=GOLD_PALE, border=GOLD, spine=GOLD,
    )
    principal_panel = remark_panel(
        "PRINCIPAL'S REMARKS", principal_remark,
        bg=SAGE_TINT, border=SAGE, spine=SAGE_DEEP,
    )
    remarks_row = Table(
        [[teacher_panel, "", principal_panel]],
        colWidths=[8.7 * cm, 0.6 * cm, 8.7 * cm],
    )
    remarks_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story += [remarks_row, Spacer(1, 0.5 * cm)]

    # ---------------- signatures ----------------
    signatures = Table(
        [[
            Paragraph(
                "____________________________<br/>"
                "CLASS TEACHER'S SIGNATURE", signature,
            ),
            Paragraph(
                "____________________________<br/>"
                "PRINCIPAL'S SIGNATURE / STAMP", signature,
            ),
        ]],
        colWidths=[9 * cm, 9 * cm],
    )
    signatures.setStyle(TableStyle([
        ("ALIGN",  (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING",   (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story += [signatures, Spacer(1, 0.35 * cm)]

    # ---------------- footer ----------------
    footer = Table(
        [[Paragraph("DISCIPLINE   ·   HARD WORK   ·   EXCELLENCE",
                    footer_style)]],
        colWidths=[18 * cm],
    )
    footer.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, GOLD),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(footer)

    # ---------------- build ----------------
    doc.build(story)
    return _stream_pdf(buf, "report_card.pdf")


def _stream_pdf(buf, filename):
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )