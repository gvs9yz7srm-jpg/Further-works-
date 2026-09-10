import streamlit as st
import sqlite3
import csv
import io
from datetime import date, datetime
from calendar import month_name
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

DB_FILE = "extra_charges.db"

st.set_page_config(page_title="Extra Charges", page_icon="🧾", layout="centered")

# ---------- Database ----------
def connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS charges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date TEXT NOT NULL,
                address TEXT NOT NULL,
                charge_type TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                month_key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'OPEN',
                sent_at TEXT
            )
        """)


def add_charge(work_date, address, charge_type, quantity, note):
    with connect() as conn:
        conn.execute(
            """INSERT INTO charges (work_date, address, charge_type, quantity, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (work_date.isoformat(), address.strip(), charge_type, quantity, note.strip(), datetime.now().isoformat(timespec="seconds")),
        )


def delete_charge(row_id):
    with connect() as conn:
        conn.execute("DELETE FROM charges WHERE id = ?", (row_id,))


def update_charge(row_id, work_date, address, charge_type, quantity, note):
    with connect() as conn:
        conn.execute(
            """UPDATE charges
               SET work_date=?, address=?, charge_type=?, quantity=?, note=?
               WHERE id=?""",
            (work_date.isoformat(), address.strip(), charge_type, quantity, note.strip(), row_id),
        )


def month_rows(year, month):
    prefix = f"{year:04d}-{month:02d}"
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM charges WHERE work_date LIKE ? ORDER BY work_date, id",
            (prefix + "%",),
        ).fetchall()


def get_status(year, month):
    key = f"{year:04d}-{month:02d}"
    with connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE month_key=?", (key,)).fetchone()
    return dict(row) if row else {"month_key": key, "status": "OPEN", "sent_at": None}


def set_status(year, month, status):
    key = f"{year:04d}-{month:02d}"
    sent_at = datetime.now().isoformat(timespec="seconds") if status == "SENT" else None
    with connect() as conn:
        conn.execute(
            """INSERT INTO reports(month_key, status, sent_at)
               VALUES (?, ?, ?)
               ON CONFLICT(month_key) DO UPDATE SET status=excluded.status, sent_at=excluded.sent_at""",
            (key, status, sent_at),
        )


def previous_month(today):
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


# ---------- Export ----------
def csv_bytes(rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Address", "Extra Charge", "Quantity", "Note"])
    for r in rows:
        writer.writerow([r["work_date"], r["address"], r["charge_type"], r["quantity"], r["note"]])
    return output.getvalue().encode("utf-8-sig")



def pdf_bytes(rows, year, month):
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=A4,
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], alignment=TA_CENTER,
        fontSize=16, leading=20, spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "ChargeHeading", parent=styles["Heading2"], fontSize=11,
        leading=14, spaceBefore=8, spaceAfter=5,
    )
    body_style = styles["BodyText"]
    story = [
        Paragraph(f"Extra Charges Report - {month_name[month]} {year}", title_style),
        Paragraph(f"Total extra charges: {sum(r['quantity'] for r in rows)}", body_style),
        Spacer(1, 6),
    ]

    preferred_order = ["Travel", "Interconnection", "RCD Replacement", "Other"]
    all_types = list(dict.fromkeys(preferred_order + [r["charge_type"] for r in rows]))
    for charge_type in all_types:
        grouped = [r for r in rows if r["charge_type"] == charge_type]
        if not grouped:
            continue
        total_qty = sum(r["quantity"] for r in grouped)
        story.append(Paragraph(f"{charge_type} - {total_qty}", heading_style))
        data = [["Date", "Address", "Qty", "Note"]]
        for r in grouped:
            d = datetime.strptime(r["work_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            data.append([
                d,
                Paragraph(str(r["address"]), body_style),
                str(r["quantity"]),
                Paragraph(str(r["note"] or ""), body_style),
            ])
        table = Table(data, colWidths=[27*mm, 82*mm, 14*mm, 47*mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8.5),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("GRID", (0,0), (-1,-1), 0.35, colors.grey),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        story.extend([table, Spacer(1, 8)])

    doc.build(story)
    return output.getvalue()


def simple_report_text(rows, year, month):
    title = f"EXTRA CHARGES REPORT - {month_name[month].upper()} {year}"
    lines = [title, "=" * len(title), ""]
    types = sorted(set(r["charge_type"] for r in rows))
    for charge_type in types:
        grouped = [r for r in rows if r["charge_type"] == charge_type]
        total_qty = sum(r["quantity"] for r in grouped)
        lines.append(f"{charge_type.upper()} - {total_qty}")
        lines.append("-" * 50)
        for r in grouped:
            d = datetime.strptime(r["work_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            qty = f" x{r['quantity']}" if r["quantity"] != 1 else ""
            note = f" | {r['note']}" if r["note"] else ""
            lines.append(f"{d} | {r['address']}{qty}{note}")
        lines.append("")
    lines.append(f"Total recorded items: {sum(r['quantity'] for r in rows)}")
    return "\n".join(lines)


init_db()

# ---------- UI ----------
st.title("Extra Charges")
st.caption("Record it now. Send last month's list when requested.")

entry_tab, report_tab = st.tabs(["Add Charge", "Monthly Report"])

with entry_tab:
    with st.form("add_charge", clear_on_submit=True):
        work_date = st.date_input("Date", value=date.today())
        address = st.text_input("Address", placeholder="e.g. 15 Smith St, Auburn")
        charge_type = st.selectbox("Extra charge", ["Travel", "Interconnection", "RCD Replacement", "Other"])
        quantity = st.number_input("Quantity", min_value=1, max_value=100, value=1, step=1)
        note = st.text_input("Note (optional)")
        submitted = st.form_submit_button("Save", use_container_width=True, type="primary")

    if submitted:
        if not address.strip():
            st.error("Enter an address.")
        else:
            add_charge(work_date, address, charge_type, int(quantity), note)
            st.success("Saved.")

    st.divider()
    st.subheader("Recent entries")
    with connect() as conn:
        recent = conn.execute("SELECT * FROM charges ORDER BY work_date DESC, id DESC LIMIT 8").fetchall()

    if not recent:
        st.caption("No extra charges recorded yet.")
    else:
        for r in recent:
            d = datetime.strptime(r["work_date"], "%Y-%m-%d").strftime("%d/%m/%y")
            qty = f" ×{r['quantity']}" if r["quantity"] != 1 else ""
            st.write(f"**{d} · {r['charge_type']}{qty}**  \n{r['address']}")

with report_tab:
    py, pm = previous_month(date.today())
    years = list(range(date.today().year - 3, date.today().year + 2))
    c1, c2 = st.columns(2)
    with c1:
        selected_month = st.selectbox("Month", range(1, 13), index=pm - 1, format_func=lambda x: month_name[x])
    with c2:
        selected_year = st.selectbox("Year", years, index=years.index(py) if py in years else 0)

    rows = month_rows(selected_year, selected_month)
    report = get_status(selected_year, selected_month)

    st.subheader(f"{month_name[selected_month]} {selected_year}")
    if report["status"] == "SENT":
        sent_display = datetime.fromisoformat(report["sent_at"]).strftime("%d/%m/%Y %I:%M %p") if report["sent_at"] else ""
        st.success(f"SENT · {sent_display}")
    elif report["status"] == "EXPORTED":
        st.info("EXPORTED")
    else:
        st.caption("OPEN")

    if not rows:
        st.info("No extra charges recorded for this month.")
    else:
        total_qty = sum(r["quantity"] for r in rows)
        st.metric("Extra charges", total_qty)

        for charge_type in ["Travel", "Interconnection", "RCD Replacement", "Other"]:
            grouped = [r for r in rows if r["charge_type"] == charge_type]
            if not grouped:
                continue
            st.markdown(f"### {charge_type} · {sum(r['quantity'] for r in grouped)}")
            for r in grouped:
                d = datetime.strptime(r["work_date"], "%Y-%m-%d").strftime("%d/%m")
                qty = f" ×{r['quantity']}" if r["quantity"] != 1 else ""
                note = f" — {r['note']}" if r["note"] else ""
                st.write(f"**{d}** · {r['address']}{qty}{note}")

                if report["status"] != "SENT":
                    with st.expander("Edit / Delete"):
                        with st.form(f"edit_{r['id']}"):
                            ed = st.date_input("Date", value=datetime.strptime(r["work_date"], "%Y-%m-%d").date(), key=f"d_{r['id']}")
                            ea = st.text_input("Address", value=r["address"], key=f"a_{r['id']}")
                            options = ["Travel", "Interconnection", "RCD Replacement", "Other"]
                            et = st.selectbox("Type", options, index=options.index(r["charge_type"]) if r["charge_type"] in options else 3, key=f"t_{r['id']}")
                            eq = st.number_input("Quantity", min_value=1, value=int(r["quantity"]), step=1, key=f"q_{r['id']}")
                            en = st.text_input("Note", value=r["note"], key=f"n_{r['id']}")
                            if st.form_submit_button("Save changes", use_container_width=True):
                                if ea.strip():
                                    update_charge(r["id"], ed, ea, et, int(eq), en)
                                    st.rerun()
                        if st.button("Delete", key=f"delete_{r['id']}", use_container_width=True):
                            delete_charge(r["id"])
                            st.rerun()

        st.divider()
        filename_base = f"extra_charges_{selected_year}_{selected_month:02d}"
        col1, col2 = st.columns(2)
        with col1:
            if st.download_button(
                "Download PDF",
                data=pdf_bytes(rows, selected_year, selected_month),
                file_name=filename_base + ".pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            ):
                set_status(selected_year, selected_month, "EXPORTED")
        with col2:
            if st.download_button(
                "Download CSV",
                data=csv_bytes(rows),
                file_name=filename_base + ".csv",
                mime="text/csv",
                use_container_width=True,
            ):
                set_status(selected_year, selected_month, "EXPORTED")

    st.divider()
    if report["status"] != "SENT":
        if st.button("Mark Month as Sent", use_container_width=True, type="primary", disabled=not rows):
            set_status(selected_year, selected_month, "SENT")
            st.rerun()
    else:
        if st.button("Reopen Month", use_container_width=True):
            set_status(selected_year, selected_month, "OPEN")
            st.rerun()
