from collections.abc import Callable

from nicegui import ui

from app.config import SCORE_CATEGORIES
from app.scoring import recompute_score_breakdown

GRADE_COLORS = {
    "A": "green",
    "B": "light-green",
    "C": "orange",
    "D": "deep-orange",
    "F": "red",
}
GRADE_COLOR_NONE = "grey"

GRADE_HEX_COLORS = {
    "A": "#4caf50",
    "B": "#8bc34a",
    "C": "#ff9800",
    "D": "#ff5722",
    "F": "#f44336",
}

VALUE_TRUNCATE_LENGTH = 120

SECURITY_HEADER_LABELS = {
    "Strict-Transport-Security": "Strict-Transport-Security",
    "Content-Security-Policy": "Content-Security-Policy",
    "X-Content-Type-Options": "X-Content-Type-Options",
    "X-Frame-Options": "X-Frame-Options",
    "Referrer-Policy": "Referrer-Policy",
    "Permissions-Policy": "Permissions-Policy",
}


def _grade_badge(letter_grade: str | None) -> None:
    color = GRADE_COLORS.get(letter_grade, GRADE_COLOR_NONE)
    ui.badge(letter_grade or "-", color=color).classes("text-body1 q-pa-sm")


def render_check_now_button(target_id: int, running: bool, on_click: Callable[[], None]):
    with ui.row().classes("items-center gap-2"):
        button = ui.button("Şimdi Kontrol Et", on_click=on_click)
        spinner = ui.spinner(size="1.5em")
        spinner.set_visibility(running)
        button.set_enabled(not running)
    return button, spinner


def render_target_card(
    card: dict,
    running: bool,
    on_check_now: Callable[[int], None],
    on_tag_click: Callable[[str], None],
    on_edit: Callable[[int], None],
) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-1"):
                ui.link(card["name"], f"/targets/{card['id']}").classes("text-h6")
                if card["has_open_alerts"]:
                    ui.icon("error", color="red").classes("text-xl").tooltip("Açık uyarı var")
            with ui.row().classes("items-center gap-1"):
                ui.button(icon="edit", on_click=lambda: on_edit(card["id"])).props("flat dense round")
                _grade_badge(card["letter_grade"])
        if not card["active"]:
            ui.badge("Pasif", color="grey")
        elif card["status_code"]:
            ui.badge(f"HTTP {card['status_code']}", color="green")
        else:
            ui.badge("Erişilemiyor", color="red")
        ui.label(card["url"]).classes("text-caption text-grey")
        if card["tags"]:
            with ui.row().classes("gap-1"):
                for tag in card["tags"]:
                    ui.chip(tag, on_click=lambda t=tag: on_tag_click(t)).props("dense outline")
        if card["checked_at"]:
            ui.label(f"Son kontrol: {card['checked_at']}").classes("text-caption")
        if card["cert_days_remaining"] is not None:
            ui.label(f"Sertifikaya kalan gün: {card['cert_days_remaining']}").classes("text-caption")
        render_check_now_button(card["id"], running, lambda: on_check_now(card["id"]))


def render_active_filters(
    state: dict,
    on_remove_grade: Callable[[str], None],
    on_remove_group: Callable[[str], None],
    on_clear_query: Callable[[], None],
    on_clear_all: Callable[[], None],
) -> None:
    if not (state["grades"] or state["groups"] or state["query"]):
        return
    with ui.row().classes("items-center gap-2 q-mb-sm"):
        for grade in state["grades"]:
            ui.chip(f"Not: {grade}", removable=True, on_value_change=lambda e, g=grade: on_remove_grade(g))
        for group in state["groups"]:
            ui.chip(f"Grup: {group}", removable=True, on_value_change=lambda e, g=group: on_remove_group(g))
        if state["query"]:
            ui.chip(f"Ara: {state['query']}", removable=True, on_value_change=lambda e: on_clear_query())
        ui.button("Filtreleri Temizle", on_click=on_clear_all).props("flat dense")


UPTIME_STATUS_COLORS = {
    "up": "#4caf50",
    "partial": "#ff9800",
    "down": "#f44336",
    "no_data": "#bdbdbd",
}


def _uptime_badge_color(pct: float | None) -> str:
    if pct is None:
        return GRADE_COLOR_NONE
    if pct >= 99.9:
        return "green"
    if pct >= 99.0:
        return "orange"
    return "red"


def render_uptime_summary(stats: dict) -> None:
    with ui.row().classes("items-center gap-4"):
        for label, key in (("7 gün", "uptime_7d"), ("30 gün", "uptime_30d")):
            pct = stats.get(key)
            with ui.row().classes("items-center gap-2"):
                ui.label(f"{label} çalışma süresi:").classes("text-caption text-grey")
                text = f"{pct}%" if pct is not None else "Veri yok"
                ui.badge(text, color=_uptime_badge_color(pct)).classes("text-body2 q-pa-sm")


def render_uptime_timeline(timeline: list[dict]) -> None:
    with ui.row().classes("gap-0.5 items-end"):
        for day in timeline:
            color = UPTIME_STATUS_COLORS[day["status"]]
            tooltip_text = f"{day['date']}: {day['uptime_pct']}%" if day["uptime_pct"] is not None else f"{day['date']}: veri yok"
            with ui.element("div").classes("w-3 h-8 rounded").style(f"background-color: {color}"):
                ui.tooltip(tooltip_text)


def render_downtime_incidents(incidents: list[dict]) -> None:
    if not incidents:
        ui.label("Son 30 günde kesinti kaydı yok.").classes("text-caption text-grey")
        return
    with ui.column().classes("w-full gap-1"):
        for incident in incidents:
            if incident["ongoing"]:
                text = f"{incident['start']} → devam ediyor ({incident['duration_minutes']} dk)"
            else:
                text = f"{incident['start']} → {incident['end']} ({incident['duration_minutes']} dk)"
            ui.label(text).classes("text-caption")


def render_overview_summary(summary: dict) -> None:
    with ui.row().classes("items-center gap-6"):
        with ui.row().classes("items-center gap-1"):
            ui.label("Erişilebilir:").classes("text-caption text-grey")
            ui.label(f"{summary['healthy_count']}/{summary['total_targets']}").classes("text-weight-medium")
        with ui.row().classes("items-center gap-1"):
            ui.label("Güvenli:").classes("text-caption text-grey")
            ui.label(f"{summary['safe_count']}/{summary['total_targets']}").classes("text-weight-medium")
        with ui.row().classes("items-center gap-1"):
            ui.label("Açık Uyarı:").classes("text-caption text-grey")
            color = "red" if summary["open_alerts_count"] else GRADE_COLOR_NONE
            ui.badge(str(summary["open_alerts_count"]), color=color).classes("q-pa-xs")
        with ui.row().classes("items-center gap-1"):
            ui.label("Ortalama Not:").classes("text-caption text-grey")
            if summary["average_score"] is None:
                ui.label("Veri yok").classes("text-weight-medium")
            else:
                ui.label(f"{summary['average_score']} ({summary['average_grade']})").classes("text-weight-medium")


def render_grade_distribution(distribution: dict) -> ui.echart:
    data = [
        {"name": grade, "value": count, "itemStyle": {"color": GRADE_HEX_COLORS[grade]}}
        for grade, count in distribution.items()
        if count > 0
    ]
    options = {
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 0},
        "series": [
            {
                "type": "pie",
                "radius": ["40%", "70%"],
                "avoidLabelOverlap": True,
                "data": data,
            }
        ],
    }
    return ui.echart(options).classes("w-full h-64")


def render_rankings(rankings: dict) -> None:
    with ui.row().classes("w-full gap-8"):
        with ui.column().classes("gap-1"):
            ui.label("En Düşük Notlu 5").classes("text-subtitle1")
            if not rankings["lowest_grade"]:
                ui.label("Yeterli veri yok.").classes("text-caption text-grey")
            for entry in rankings["lowest_grade"]:
                with ui.row().classes("items-center gap-2"):
                    _grade_badge(entry["letter_grade"])
                    ui.link(entry["name"], f"/targets/{entry['id']}")
                    ui.label(f"({entry['score']})").classes("text-caption text-grey")
        with ui.column().classes("gap-1"):
            ui.label("En Yavaş 5").classes("text-subtitle1")
            if not rankings["slowest"]:
                ui.label("Yeterli veri yok.").classes("text-caption text-grey")
            for entry in rankings["slowest"]:
                with ui.row().classes("items-center gap-2"):
                    ui.link(entry["name"], f"/targets/{entry['id']}")
                    ui.label(f"{entry['response_time_ms']:.0f} ms").classes("text-caption text-grey")


def render_header_matrix(matrix: dict) -> None:
    columns = [{"name": "target", "label": "Hedef", "field": "target", "align": "left"}] + [
        {"name": header, "label": SECURITY_HEADER_LABELS.get(header, header), "field": header, "align": "center"}
        for header in matrix["headers"]
    ]
    rows = []
    for row in matrix["rows"]:
        table_row = {"target": row["name"]}
        for header in matrix["headers"]:
            value = row[header]
            table_row[header] = "Var" if value else ("Yok" if value is False else "-")
        rows.append(table_row)
    ui.table(columns=columns, rows=rows, row_key="target").classes("w-full")


def render_certificate_calendar(entries: list[dict]) -> None:
    if not entries:
        ui.label("Sertifika verisi olan hedef yok.").classes("text-caption text-grey")
        return
    with ui.column().classes("w-full gap-1"):
        for entry in entries:
            if entry["days_remaining"] < 7:
                row_classes = "w-full justify-between items-center border-b bg-red-1"
            elif entry["days_remaining"] < 30:
                row_classes = "w-full justify-between items-center border-b bg-orange-1"
            else:
                row_classes = "w-full justify-between items-center border-b"
            with ui.row().classes(row_classes):
                ui.link(entry["name"], f"/targets/{entry['id']}")
                ui.label(f"{entry['expiry_date']} — kalan gün: {entry['days_remaining']}").classes("text-caption")


def render_response_time_percentiles(stats: dict) -> None:
    if not stats["sample_size"]:
        ui.label("Yanıt süresi verisi yok.").classes("text-caption text-grey")
        return
    with ui.row().classes("items-center gap-4"):
        for label, key in (("p50", "p50"), ("p95", "p95"), ("p99", "p99")):
            with ui.row().classes("items-center gap-2"):
                ui.label(f"{label}:").classes("text-caption text-grey")
                ui.label(f"{stats[key]:.0f} ms").classes("text-h6")
        ui.label(f"({stats['sample_size']} örnek)").classes("text-caption text-grey")


def render_score_heatmap(heatmap: dict) -> ui.echart:
    grid_top = 20
    grid_bottom = 90
    height = max(260, 36 * len(heatmap["targets"]) + grid_top + grid_bottom)
    options = {
        "tooltip": {"position": "top"},
        "grid": {"top": grid_top, "bottom": grid_bottom, "left": 120, "right": 20},
        "xAxis": {"type": "category", "data": heatmap["days"], "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": heatmap["targets"], "splitArea": {"show": True}},
        "visualMap": {
            "min": 0,
            "max": 100,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": 8,
            "inRange": {"color": ["#f44336", "#ff9800", "#4caf50"]},
        },
        "series": [{"type": "heatmap", "data": heatmap["data"], "label": {"show": False}}],
    }
    return ui.echart(options).classes("w-full").style(f"height: {height}px")


EVENT_TYPE_COLORS = {
    "target_added": "#2196f3",
    "alert_opened": "#f44336",
    "alert_resolved": "#4caf50",
}


def render_event_feed(events: list[dict]) -> None:
    if not events:
        ui.label("Henüz olay yok.").classes("text-caption text-grey")
        return
    with ui.column().classes("w-full gap-2"):
        for event in events:
            color = EVENT_TYPE_COLORS.get(event["type"], GRADE_COLOR_NONE)
            with ui.row().classes("ar-event-row items-start gap-2 w-full"):
                ui.element("div").classes("w-2 h-2 rounded-full q-mt-sm").style(f"background-color: {color}; flex-shrink: 0")
                with ui.column().classes("gap-0"):
                    ui.label(event["text"]).classes("text-body2")
                    ui.label(event["timestamp"]).classes("text-caption text-grey")


DEEP_CHECK_SEVERITY_COLORS = {"high": "red", "medium": "orange", "low": "grey"}


def render_deep_check_result(data: dict | None) -> None:
    if data is None:
        ui.label("En son çalıştırma: hiç çalıştırılmadı").classes("text-caption text-grey")
        return

    ui.label(f"En son çalıştırma: {data['checked_at']}").classes("text-caption text-grey")
    result = data["result"]

    if result.get("error"):
        ui.label(f"Hata: {result['error']}").classes("text-caption text-red")
        return

    findings = result.get("findings") or []
    if not findings:
        ui.label("Belirgin bir bulgu yok.").classes("text-caption text-grey")
    else:
        with ui.column().classes("w-full gap-1 q-mt-sm"):
            for finding in findings:
                color = DEEP_CHECK_SEVERITY_COLORS.get(finding["severity"], GRADE_COLOR_NONE)
                with ui.row().classes("items-start gap-2"):
                    ui.badge(finding["severity"].upper(), color=color).classes("q-mt-xs")
                    ui.label(finding["message"])

    metrics = result.get("metrics") or {}
    with ui.row().classes("gap-6 q-mt-sm"):
        ui.label(f"Toplam istek: {metrics.get('requests_total', '-')}").classes("text-caption text-grey")
        bytes_total = metrics.get("bytes_total")
        size_text = f"{round(bytes_total / 1024, 1)} KB" if bytes_total is not None else "-"
        ui.label(f"Toplam boyut: {size_text}").classes("text-caption text-grey")
        dcl_ms = metrics.get("dom_content_loaded_ms")
        dcl_text = f"{dcl_ms:.0f} ms" if dcl_ms is not None else "-"
        ui.label(f"DOMContentLoaded: {dcl_text}").classes("text-caption text-grey")
        load_ms = metrics.get("load_ms")
        load_text = f"{load_ms:.0f} ms" if load_ms is not None else "-"
        ui.label(f"Load: {load_text}").classes("text-caption text-grey")

    third_party = result.get("third_party_domains") or []
    with ui.expansion(f"Üçüncü Taraf Alan Adları ({len(third_party)})").classes("w-full q-mt-sm"):
        if not third_party:
            ui.label("Dış alan adından kaynak yüklenmedi.").classes("text-caption text-grey")
        for entry in sorted(third_party, key=lambda e: e["bytes"], reverse=True):
            tag = " — izleyici/analitik" if entry.get("is_tracker") else ""
            size_kb = round(entry["bytes"] / 1024, 1)
            ui.label(f"{entry['domain']}: {entry['request_count']} istek, {size_kb} KB{tag}").classes("text-caption")

    console = result.get("console") or {}
    own_console = console.get("own_domain") or []
    third_console = console.get("third_party") or []
    with ui.expansion(f"Konsol Mesajları (kendi: {len(own_console)}, dış: {len(third_console)})").classes("w-full q-mt-sm"):
        if not own_console and not third_console:
            ui.label("Konsol mesajı yok.").classes("text-caption text-grey")
        for group_label, messages in (("Kendi alan adı", own_console), ("Dış alan adları", third_console)):
            if not messages:
                continue
            ui.label(group_label).classes("text-caption text-weight-medium")
            for msg in messages:
                count_text = f" (x{msg['count']})" if msg.get("count", 1) > 1 else ""
                source = msg.get("source") or "-"
                ui.label(f"[{msg['level']}] {msg['message']}{count_text} — {source}").classes("text-caption")

    cookies = result.get("cookies") or []
    with ui.expansion(f"Çerezler ({len(cookies)})").classes("w-full q-mt-sm"):
        if not cookies:
            ui.label("Çerez kurulmadı.").classes("text-caption text-grey")
        for cookie in cookies:
            flags = []
            if not cookie.get("secure"):
                flags.append("Secure yok")
            if not cookie.get("http_only"):
                flags.append("HttpOnly yok")
            if cookie.get("same_site") in (None, "None"):
                flags.append("SameSite=None")
            flags_text = ", ".join(flags) if flags else "Tüm bayraklar mevcut"
            ui.label(f"{cookie['name']} ({cookie['domain']}): {flags_text}").classes("text-caption")


def render_alerts(open_alerts: list[dict]) -> None:
    if not open_alerts:
        return
    ui.label("Açık Uyarılar").classes("text-h6")
    for alert in open_alerts:
        with ui.card().classes("w-full bg-red-1"):
            ui.label(f"{alert['alert_type']} — {alert['message']}")
            ui.label(f"({alert['created_at']})").classes("text-caption text-grey")


def _copy_to_clipboard(value: str) -> None:
    ui.clipboard.write(value)
    ui.notify("Kopyalandı.", type="info")


def _render_value_cell(value: str) -> None:
    if len(value) <= VALUE_TRUNCATE_LENGTH:
        ui.label(value)
        return
    truncated = value[:VALUE_TRUNCATE_LENGTH] + "…"
    with ui.expansion(truncated).classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label(value).classes("text-caption").style("word-break: break-all")
            ui.button(icon="content_copy", on_click=lambda: _copy_to_clipboard(value)).props("flat dense round size=sm")


def _trend_indicator(current_earned: int, previous_earned: int | None) -> None:
    if previous_earned is None:
        return
    if current_earned > previous_earned:
        ui.icon("arrow_upward", color="green").classes("text-sm")
    elif current_earned < previous_earned:
        ui.icon("arrow_downward", color="red").classes("text-sm")
    else:
        ui.icon("remove", color="grey").classes("text-sm")


def render_score_breakdown(last_check: dict | None, previous_check: dict | None = None) -> None:
    result = recompute_score_breakdown(last_check)
    if result is None:
        ui.label("Henüz kontrol verisi yok.")
        return

    previous_result = recompute_score_breakdown(previous_check) if previous_check else None
    previous_breakdown = previous_result["breakdown"] if previous_result and previous_result["breakdown"] else {}

    with ui.row().classes("items-center gap-2"):
        ui.label(f"Toplam: {result['score']} ({result['letter_grade']})").classes("text-weight-medium")
        if previous_result is not None:
            _trend_indicator(result["score"], previous_result["score"])

    if result["breakdown"] is None:
        if result["reasons"]:
            ui.label(result["reasons"][0]).classes("text-caption text-grey")
        return

    with ui.column().classes("w-full gap-1"):
        for category, info in result["breakdown"].items():
            if info is None:
                continue
            previous_info = previous_breakdown.get(category)
            with ui.row().classes("w-full items-center gap-2 justify-between border-b"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{SCORE_CATEGORIES[category]['label']}: {info['earned']}/{info['max']}").classes(
                        "text-weight-medium"
                    )
                    _trend_indicator(info["earned"], previous_info["earned"] if previous_info else None)
            for deduction in info["deductions"]:
                with ui.row().classes("w-full items-center gap-2 q-ml-md"):
                    ui.badge("kaldı", color="red").classes("q-pa-sm")
                    ui.label(deduction["message"]).classes("text-caption")
                    ui.label(f"-{deduction['points']} puan").classes("text-caption text-grey")


def render_status_table(last_check: dict | None) -> None:
    if last_check is None:
        ui.label("Henüz kontrol verisi yok.")
        return

    rows = [
        ("Erişilebilirlik", f"HTTP {last_check['status_code']}" if last_check["status_code"] else "Erişilemiyor"),
        (
            "Yanıt Süresi",
            f"{last_check['response_time_ms']} ms" if last_check["response_time_ms"] else "-",
        ),
        (
            "DNS",
            "Çözümlendi" if (last_check["dns_result"] or {}).get("resolved") else "Çözümlenemedi",
        ),
        (
            "HTTP→HTTPS Yönlendirme",
            "Var" if (last_check["redirect_result"] or {}).get("redirects_to_https") else "Yok",
        ),
    ]

    dns_result = last_check["dns_result"] or {}

    def _hygiene_text(value: bool | None) -> str:
        if value is None:
            return "Test edilemedi"
        return "Var" if value else "Yok"

    rows.append(("SPF Kaydı", _hygiene_text(dns_result.get("spf_present"))))
    rows.append(("DMARC Kaydı", _hygiene_text(dns_result.get("dmarc_present"))))
    rows.append(("CAA Kaydı", _hygiene_text(dns_result.get("caa_present"))))

    tls_result = last_check["tls_result"] or {}
    if tls_result.get("applicable"):
        tls_text = ("Geçerli" if tls_result.get("chain_valid") else "Geçersiz") + f", kalan gün: {tls_result.get('days_remaining')}"
        rows.append(("TLS", tls_text))

        old_supported = tls_result.get("old_protocols_supported")
        if old_supported is None:
            rows.append(("TLS 1.0 / 1.1", "Test edilemedi"))
        else:
            rows.append(("TLS 1.0 / 1.1", "Kabul ediliyor" if old_supported else "Reddediliyor"))

        tls13 = tls_result.get("tls_1_3_supported")
        if tls13 is None:
            rows.append(("TLS 1.3", "Test edilemedi"))
        else:
            rows.append(("TLS 1.3", "Destekleniyor" if tls13 else "Desteklenmiyor"))

        cipher_name = tls_result.get("cipher_name")
        if cipher_name:
            cipher_text = f"{cipher_name} ({tls_result.get('negotiated_protocol')})"
            if tls_result.get("weak_cipher"):
                cipher_text += " — zayıf"
            rows.append(("Şifre Takımı", cipher_text))
    else:
        rows.append(("TLS", "Uygulanamıyor"))

    headers_result = last_check["headers_result"] or {}
    for name in SECURITY_HEADER_LABELS:
        info = (headers_result.get("security_headers") or {}).get(name, {})
        rows.append((name, f"Var — {info.get('value')}" if info.get("present") else "Yok"))
    for name, info in (headers_result.get("info_leak") or {}).items():
        text = f"Sürüm sızdırıyor: {info.get('value')}" if info.get("reveals_version") else "Sorun yok"
        rows.append((f"{name} (sızıntı)", text))

    cookies = headers_result.get("cookies") or []
    if not cookies:
        rows.append(("Çerezler", "Çerez kurulmadı."))
    else:
        for cookie in cookies:
            flags = []
            if not cookie.get("secure"):
                flags.append("Secure yok")
            if not cookie.get("http_only"):
                flags.append("HttpOnly yok")
            if cookie.get("same_site") in (None, "None"):
                flags.append("SameSite=None")
            flags_text = ", ".join(flags) if flags else "Tüm bayraklar mevcut"
            rows.append((f"Çerez: {cookie['name']}", flags_text))

    with ui.column().classes("w-full gap-1"):
        for label, value in rows:
            with ui.row().classes("w-full justify-between items-center border-b"):
                ui.label(label).classes("text-weight-medium")
                _render_value_cell(str(value))


def render_certificate_chain(chain: list[dict]) -> None:
    if not chain:
        ui.label("Sertifika zinciri verisi yok.").classes("text-caption text-grey")
        return

    layers = list(reversed(chain))
    total = len(layers)
    for index, cert in enumerate(layers):
        if index == 0:
            role = "Kök"
        elif index == total - 1:
            role = "Yaprak"
        else:
            role = "Ara"
        title = f"{role}: {cert.get('subject_cn') or '(CN yok)'}"
        with ui.expansion(title).classes("w-full"):
            with ui.column().classes("w-full gap-1"):
                for label, value in (
                    ("Veren", cert.get("issuer_cn")),
                    ("Geçerlilik Başlangıcı", cert.get("valid_from")),
                    ("Geçerlilik Bitişi", cert.get("valid_to")),
                    ("Seri No", cert.get("serial_number")),
                    ("İmza Algoritması", cert.get("signature_algorithm")),
                    ("Anahtar", f"{cert.get('key_type')} {cert.get('key_bits')} bit" if cert.get("key_bits") else cert.get("key_type")),
                    ("SHA-256 Fingerprint", cert.get("sha256_fingerprint")),
                ):
                    with ui.row().classes("w-full justify-between items-center border-b"):
                        ui.label(label).classes("text-weight-medium")
                        _render_value_cell(str(value))
                if cert.get("san"):
                    with ui.row().classes("w-full justify-between items-center border-b"):
                        ui.label("SAN").classes("text-weight-medium")
                        _render_value_cell(", ".join(cert["san"]))


def render_ct_log_result(result: dict | None, checked_at: str | None) -> None:
    if result is None:
        ui.label("Henüz Certificate Transparency verisi yok.").classes("text-caption text-grey")
        return
    if result.get("error"):
        ui.label(f"Sorgu başarısız: {result['error']}").classes("text-caption text-orange")
        return
    discovered = result.get("discovered_names") or []
    if checked_at:
        ui.label(f"Son sorgu: {checked_at}").classes("text-caption text-grey")
    if not discovered:
        ui.label("Bilinmeyen alt alan adı bulunamadı.").classes("text-caption text-grey")
        return
    ui.label(f"{len(discovered)} bilinmeyen alt alan adı keşfedildi:").classes("text-caption")
    for name in discovered:
        ui.label(f"- {name}").classes("text-caption")


def render_content_section(content_result: dict | None, on_reset: Callable[[], None]) -> None:
    ui.label("İçerik Bütünlüğü").classes("text-h6 q-mt-md")

    if content_result is None:
        ui.label("Henüz kontrol verisi yok.")
        return

    keyword_found = content_result.get("keyword_found")
    if keyword_found is None:
        ui.label("Anahtar kelime: Tanımlanmadı").classes("text-caption text-grey")
    else:
        ui.label(f"Anahtar kelime: {'Bulundu' if keyword_found else 'Bulunamadı'}")

    ui.label(
        f"İçerik özeti (bilgi amaçlı): {'Değişti' if content_result.get('hash_changed') else 'Değişmedi'}"
    ).classes("text-caption text-grey")

    if content_result.get("baseline_established"):
        ui.label("Yapısal temel çizgi bu kontrolde oluşturuldu.").classes("text-caption text-grey")
    else:
        changes = content_result.get("changes") or []
        if changes:
            for change in changes:
                ui.label(f"- {change}")
        else:
            ui.label("Yapısal değişiklik yok.").classes("text-caption text-grey")

    ui.button("Yeni Durumu Temel Al", on_click=on_reset).props("outline")


def build_line_chart(points: list[dict], value_key: str) -> ui.echart:
    labels = [point["label"] for point in points]
    values = [point[value_key] for point in points]
    options = {
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": values, "showSymbol": False}],
        "animation": True,
        "animationDuration": 400,
    }
    return ui.echart(options).classes("w-full h-64")


def update_line_chart(chart: ui.echart, points: list[dict], value_key: str) -> None:
    chart.options["xAxis"]["data"] = [point["label"] for point in points]
    chart.options["series"][0]["data"] = [point[value_key] for point in points]
    chart.update()


TIMING_SERIES = [
    ("dns_ms", "DNS"),
    ("tcp_ms", "TCP"),
    ("tls_ms", "TLS"),
    ("ttfb_ms", "TTFB"),
    ("download_ms", "İndirme"),
]


def build_stacked_bar_chart(points: list[dict]) -> ui.echart:
    labels = [point["label"] for point in points]
    options = {
        "legend": {},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": "ms"},
        "series": [
            {"name": name, "type": "bar", "stack": "total", "data": [point[key] for point in points]}
            for key, name in TIMING_SERIES
        ],
        "animation": True,
        "animationDuration": 400,
    }
    return ui.echart(options).classes("w-full h-64")


def update_stacked_bar_chart(chart: ui.echart, points: list[dict]) -> None:
    chart.options["xAxis"]["data"] = [point["label"] for point in points]
    for index, (key, _name) in enumerate(TIMING_SERIES):
        chart.options["series"][index]["data"] = [point[key] for point in points]
    chart.update()
