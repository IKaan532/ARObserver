from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import services
from app.config import SCORE_CATEGORIES

pdfmetrics.registerFont(TTFont("Vera", "Vera.ttf"))
pdfmetrics.registerFont(TTFont("Vera-Bold", "VeraBd.ttf"))

PAGE_MARGIN = 1.5 * cm
USABLE_WIDTH = A4[0] - 2 * PAGE_MARGIN

CELL_STYLE = ParagraphStyle("cell", fontName="Vera", fontSize=7, leading=9)
HEADER_CELL_STYLE = ParagraphStyle("cell-header", fontName="Vera-Bold", fontSize=7, leading=9, textColor=colors.white)

TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e222b")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
)


def _table(rows: list[list[str]], col_widths: list[float] | None = None) -> Table:
    wrapped_rows = [
        [Paragraph(str(cell), HEADER_CELL_STYLE if i == 0 else CELL_STYLE) for cell in row]
        for i, row in enumerate(rows)
    ]
    table = Table(wrapped_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TABLE_STYLE)
    return table


def generate_monthly_pdf_report() -> bytes:
    summary = services.get_overview_summary()
    cards = services.list_target_cards()
    header_matrix = services.get_header_matrix()
    certificate_calendar = services.get_certificate_calendar()
    fleet_uptime = services.get_fleet_uptime_stats()
    open_alerts = services.get_fleet_open_alerts()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    for style_name, font_name in (("Title", "Vera-Bold"), ("Heading2", "Vera-Bold"), ("Normal", "Vera")):
        styles[style_name].fontName = font_name
    story = []

    story.append(Paragraph("ARObserver Aylık Rapor", styles["Title"]))
    story.append(Paragraph(datetime.now().strftime("Oluşturulma: %d.%m.%Y %H:%M"), styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Özet", styles["Heading2"]))
    story.append(
        _table(
            [
                ["Toplam Hedef", "Erişilebilir", "Güvenli (A-C)", "Açık Uyarı", "Ortalama Not"],
                [
                    str(summary["total_targets"]),
                    f"{summary['healthy_count']}/{summary['total_targets']}",
                    f"{summary['safe_count']}/{summary['total_targets']}",
                    str(summary["open_alerts_count"]),
                    f"{summary['average_score']} ({summary['average_grade']})"
                    if summary["average_score"] is not None
                    else "Veri yok",
                ],
            ]
        )
    )
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Skor Tablosu", styles["Heading2"]))
    score_rows = [["Hedef", "URL", "Skor", "Harf Notu"]]
    for card in cards:
        score_rows.append(
            [card["name"], card["url"], str(card["score"]) if card["score"] is not None else "-", card["letter_grade"] or "-"]
        )
    story.append(_table(score_rows))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Skor Kırılımı", styles["Heading2"]))
    for entry in services.get_fleet_score_breakdowns():
        story.append(Paragraph(entry["name"], styles["Heading2"]))
        result = entry["result"]
        if result is None or result["breakdown"] is None:
            reason = result["reasons"][0] if result and result["reasons"] else "Henüz kontrol verisi yok."
            story.append(Paragraph(reason, styles["Normal"]))
            story.append(Spacer(1, 0.3 * cm))
            continue
        breakdown_rows = [["Kategori", "Puan", "Kayıp Nedenleri"]]
        for category, info in result["breakdown"].items():
            if info is None:
                continue
            reasons = "<br/>".join(f"-{d['points']} puan: {d['message']}" for d in info["deductions"]) or "-"
            breakdown_rows.append([SCORE_CATEGORIES[category]["label"], f"{info['earned']}/{info['max']}", reasons])
        story.append(_table(breakdown_rows, col_widths=[4 * cm, 2 * cm, USABLE_WIDTH - 6 * cm]))
        story.append(Spacer(1, 0.3 * cm))
    story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Güvenlik Başlığı Matrisi", styles["Heading2"]))
    matrix_rows = [["Hedef", *header_matrix["headers"]]]
    for row in header_matrix["rows"]:
        matrix_rows.append(
            [row["name"], *["Var" if row[h] else ("-" if row[h] is None else "Yok") for h in header_matrix["headers"]]]
        )
    header_col_width = (USABLE_WIDTH - 2.5 * cm) / len(header_matrix["headers"])
    story.append(_table(matrix_rows, col_widths=[2.5 * cm] + [header_col_width] * len(header_matrix["headers"])))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Sertifika Takvimi", styles["Heading2"]))
    if certificate_calendar:
        cert_rows = [["Hedef", "Bitiş Tarihi", "Kalan Gün"]]
        for entry in certificate_calendar:
            cert_rows.append([entry["name"], entry["expiry_date"], str(entry["days_remaining"])])
        story.append(_table(cert_rows))
    else:
        story.append(Paragraph("Sertifika verisi yok.", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Kullanılabilirlik (7 / 30 Gün)", styles["Heading2"]))
    uptime_rows = [["Hedef", "7 Gün", "30 Gün"]]
    for stats in fleet_uptime.values():
        uptime_rows.append(
            [
                stats["name"],
                f"{stats['uptime_7d']}%" if stats["uptime_7d"] is not None else "Veri yok",
                f"{stats['uptime_30d']}%" if stats["uptime_30d"] is not None else "Veri yok",
            ]
        )
    story.append(_table(uptime_rows))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Açık Bulgular", styles["Heading2"]))
    if open_alerts:
        alert_rows = [["Hedef", "Tür", "Mesaj", "Açıldı"]]
        for alert in open_alerts:
            alert_rows.append([alert["target_name"], alert["alert_type"], alert["message"], alert["created_at"]])
        story.append(_table(alert_rows, col_widths=[2.5 * cm, 3.5 * cm, 9.5 * cm, 2.5 * cm]))
    else:
        story.append(Paragraph("Açık bulgu yok.", styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
