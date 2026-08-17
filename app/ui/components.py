import math
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone

from nicegui import ui

from app.config import SCORE_CATEGORIES
from app.scoring import letter_grade, recompute_score_breakdown

COLOR_TOKENS = {
    "bg_canvas": "#0f1115",
    "bg_surface": "#171a21",
    "bg_surface_raised": "#1e222b",
    "border_subtle": "#2a2e38",
    "text_primary": "#e4e7eb",
    "text_muted": "#8b909c",
    "good": "#3fb950",
    "warn": "#d29922",
    "bad": "#f85149",
    "neutral": "#6e7681",
    "primary": "#3d4552",
}

FONT_FAMILY_BASE = '-apple-system, "Segoe UI", system-ui, sans-serif'
FONT_FAMILY_MONO = 'ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace'

STATUS_ICONS = {
    "good": "check_circle",
    "warn": "warning",
    "bad": "error",
    "neutral": "remove_circle",
}

ECHARTS_DARK_THEME = {
    "backgroundColor": "transparent",
    "textStyle": {"color": COLOR_TOKENS["text_muted"], "fontFamily": FONT_FAMILY_BASE},
    "color": [COLOR_TOKENS["primary"], COLOR_TOKENS["good"], COLOR_TOKENS["warn"], COLOR_TOKENS["bad"], COLOR_TOKENS["neutral"]],
}

TOOLTIP_STYLE = {
    "backgroundColor": COLOR_TOKENS["bg_surface_raised"],
    "borderColor": COLOR_TOKENS["border_subtle"],
    "borderWidth": 1,
    "textStyle": {"color": COLOR_TOKENS["text_primary"]},
}

CHART_ANIMATION_OPTIONS = {
    "animation": True,
    "animationDuration": 500,
    "animationDurationUpdate": 300,
    "animationEasingUpdate": "cubicOut",
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _interpolate_hex(color_a: str, color_b: str, t: float) -> str:
    color_a, color_b = color_a.lstrip("#"), color_b.lstrip("#")
    ra, ga, ba = (int(color_a[i : i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(color_b[i : i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(a + (b - a) * t) for a, b in ((ra, rb), (ga, gb), (ba, bb)))
    return f"#{r:02x}{g:02x}{b:02x}"


GRADE_GRADIENT_COLORS = {
    "F": COLOR_TOKENS["bad"],
    "D": _interpolate_hex(COLOR_TOKENS["bad"], COLOR_TOKENS["warn"], 0.6),
    "C": COLOR_TOKENS["warn"],
    "B": _interpolate_hex(COLOR_TOKENS["warn"], COLOR_TOKENS["good"], 0.5),
    "A": COLOR_TOKENS["good"],
}


TOKEN_CSS = f"""
<style>
:root {{
    --ar-bg-canvas: {COLOR_TOKENS["bg_canvas"]};
    --ar-bg-surface: {COLOR_TOKENS["bg_surface"]};
    --ar-bg-surface-raised: {COLOR_TOKENS["bg_surface_raised"]};
    --ar-border-subtle: {COLOR_TOKENS["border_subtle"]};
    --ar-text-primary: {COLOR_TOKENS["text_primary"]};
    --ar-text-muted: {COLOR_TOKENS["text_muted"]};
    --ar-good: {COLOR_TOKENS["good"]};
    --ar-warn: {COLOR_TOKENS["warn"]};
    --ar-bad: {COLOR_TOKENS["bad"]};
    --ar-neutral: {COLOR_TOKENS["neutral"]};
    --ar-primary: {COLOR_TOKENS["primary"]};
    --ar-font-base: {FONT_FAMILY_BASE};
    --ar-font-mono: {FONT_FAMILY_MONO};
}}
body {{
    font-family: var(--ar-font-base);
}}
.ar-mono {{
    font-family: var(--ar-font-mono);
    font-variant-numeric: tabular-nums;
}}
.ar-panel {{
    background: var(--ar-bg-surface);
    border: 1px solid {_hex_to_rgba(COLOR_TOKENS["text_muted"], 0.35)};
    border-radius: 8px;
    padding: 12px 16px;
}}
.ar-panel-eyebrow {{
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    color: var(--ar-text-muted);
    padding-bottom: 8px;
    margin-bottom: 4px;
    border-bottom: 1px solid var(--ar-border-subtle);
}}
.ar-status-stripe {{
    border-left: 3px solid var(--ar-neutral);
}}
.ar-status-stripe-good {{ border-left-color: var(--ar-good); }}
.ar-status-stripe-warn {{ border-left-color: var(--ar-warn); }}
.ar-status-stripe-bad {{ border-left-color: var(--ar-bad); }}
.ar-row-divider {{
    border-bottom: 1px solid var(--ar-border-subtle);
}}
.ar-link-plain {{
    color: var(--ar-text-primary) !important;
    text-decoration: none !important;
    cursor: pointer;
    border-radius: 4px;
    padding: 2px 4px;
    margin: -2px -4px;
    transition: background-color 0.15s ease;
}}
.ar-link-plain:hover {{
    background-color: var(--ar-bg-surface-raised);
}}
.ar-card-hover {{
    border-radius: 8px !important;
    transition: background-color 0.15s ease;
}}
.ar-card-hover:hover {{
    background-color: var(--ar-bg-surface-raised) !important;
}}
.ar-console {{
    background: var(--ar-bg-canvas);
    border: 1px solid var(--ar-border-subtle);
    border-radius: 6px;
    padding: 4px 8px;
}}
.ar-console-row {{
    border-radius: 3px;
    padding: 3px 6px;
    transition: background-color 0.15s ease;
}}
.ar-console-row:hover {{
    background-color: var(--ar-bg-surface-raised);
}}
.ar-console-live-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--ar-good);
    animation: ar-live-pulse 1.4s ease-in-out infinite;
}}
@keyframes ar-live-pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.35; }}
}}
</style>
"""

VALUE_TRUNCATE_LENGTH = 120

SECURITY_HEADER_LABELS = {
    "Strict-Transport-Security": "Strict-Transport-Security",
    "Content-Security-Policy": "Content-Security-Policy",
    "X-Content-Type-Options": "X-Content-Type-Options",
    "X-Frame-Options": "X-Frame-Options",
    "Referrer-Policy": "Referrer-Policy",
    "Permissions-Policy": "Permissions-Policy",
}


def grade_to_status(letter_grade: str | None) -> str:
    if letter_grade in ("A", "B"):
        return "good"
    if letter_grade == "C":
        return "warn"
    if letter_grade in ("D", "F"):
        return "bad"
    return "neutral"


def uptime_pct_to_status(pct: float | None) -> str:
    if pct is None:
        return "neutral"
    if pct >= 99.9:
        return "good"
    if pct >= 99.0:
        return "warn"
    return "bad"


def cert_days_to_status(days_remaining: int) -> str:
    if days_remaining < 7:
        return "bad"
    if days_remaining < 30:
        return "warn"
    return "good"


def severity_to_status(severity: str) -> str:
    return {"high": "bad", "medium": "warn", "low": "neutral"}.get(severity, "neutral")


def event_type_to_status(event_type: str) -> str:
    return {"target_added": "neutral", "alert_opened": "bad", "alert_resolved": "good"}.get(event_type, "neutral")


def render_status_chip(kind: str, label: str) -> None:
    color = COLOR_TOKENS.get(kind, COLOR_TOKENS["neutral"])
    icon = STATUS_ICONS.get(kind, STATUS_ICONS["neutral"])
    with ui.row().classes("items-center gap-1 q-px-sm q-py-xs").style(
        f"background-color: {color}26; border: 1px solid {color}; border-radius: 4px; width: fit-content"
    ):
        ui.icon(icon).style(f"color: {color}; font-size: 1rem")
        ui.label(label).style(f"color: {color}").classes("text-body2")


@contextmanager
def render_panel(title: str, status: str | None = None):
    stripe = f"ar-status-stripe ar-status-stripe-{status}" if status else ""
    with ui.column().classes(f"ar-panel w-full gap-2 {stripe}".strip()):
        ui.label(title).classes("ar-panel-eyebrow")
        yield


def render_empty_state(message: str) -> None:
    ui.label(message).classes("text-caption").style(f"color: {COLOR_TOKENS['text_muted']}")


def format_last_update() -> str:
    return f"son güncelleme: {datetime.now().strftime('%H:%M:%S')}"


def _stat_card(value: str, label: str, status: str = "neutral") -> None:
    color = COLOR_TOKENS["text_primary"] if status == "neutral" else COLOR_TOKENS.get(status, COLOR_TOKENS["text_primary"])
    with ui.column().classes("items-start gap-0 q-px-md q-py-sm").style(
        f"background: {COLOR_TOKENS['bg_surface']}; border: 1px solid {_hex_to_rgba(COLOR_TOKENS['text_muted'], 0.35)}; "
        "border-radius: 8px; min-width: 128px"
    ):
        ui.label(value).classes("ar-mono").style(f"font-size: 1.4rem; font-weight: 600; color: {color}; line-height: 1.3")
        ui.label(label).style(
            f"font-size: 0.7rem; color: {COLOR_TOKENS['text_muted']}; text-transform: uppercase; letter-spacing: 0.04em"
        )


@contextmanager
def render_page_shell(on_logout: Callable[[], None], back_link: tuple[str, str] | None = None):
    with ui.column().classes("sticky top-0 z-10 w-full gap-2 q-pb-sm").style(
        f"background-color: {COLOR_TOKENS['bg_canvas']}"
    ):
        with ui.row().classes("w-full items-center justify-between q-pt-sm"):
            with ui.row().classes("items-center gap-3"):
                ui.link("ARObserver", "/").classes("text-h4 ar-link-plain")
                if back_link:
                    href, label = back_link
                    ui.button(label, icon="arrow_back", on_click=lambda: ui.navigate.to(href)).props("flat dense")
            ui.button("Çıkış", icon="logout", on_click=on_logout).props("flat")
        yield


def _grade_badge(letter_grade: str | None) -> None:
    render_status_chip(grade_to_status(letter_grade), letter_grade or "-")


def render_target_card(
    card: dict,
    on_tag_click: Callable[[str], None],
    on_edit: Callable[[int], None],
) -> None:
    stripe_status = grade_to_status(card["letter_grade"])
    with ui.card().classes(f"w-full ar-card-hover ar-status-stripe ar-status-stripe-{stripe_status}").style(
        f"background: {COLOR_TOKENS['bg_surface']}"
    ):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-1"):
                ui.link(card["name"], f"/targets/{card['id']}").classes("text-h6 ar-link-plain")
                if card["has_open_alerts"]:
                    ui.icon(STATUS_ICONS["bad"]).style(f"color: {COLOR_TOKENS['bad']}").classes("text-xl").tooltip(
                        "Açık uyarı var"
                    )
            with ui.row().classes("items-center gap-1"):
                ui.button(icon="edit", on_click=lambda: on_edit(card["id"])).props("flat dense round")
                _grade_badge(card["letter_grade"])
        if not card["active"]:
            render_status_chip("neutral", "Pasif")
        elif card["status_code"]:
            render_status_chip("good", f"HTTP {card['status_code']}")
        else:
            render_status_chip("bad", "Erişilemiyor")
        ui.label(card["url"]).classes("text-caption text-grey")
        if card["tags"]:
            with ui.row().classes("gap-1"):
                for tag in card["tags"]:
                    ui.chip(tag, on_click=lambda t=tag: on_tag_click(t)).props("dense outline")
        if card["checked_at"]:
            ui.label(f"Son kontrol: {card['checked_at']}").classes("text-caption ar-mono")
        if card["cert_days_remaining"] is not None:
            ui.label(f"Sertifikaya kalan gün: {card['cert_days_remaining']}").classes("text-caption ar-mono")


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


_UPTIME_DAY_STATUS = {"up": "good", "partial": "warn", "down": "bad", "no_data": "neutral"}


def _big_metric(label: str, value: str, unit: str = "", status: str = "neutral") -> None:
    color = COLOR_TOKENS["text_primary"] if status == "neutral" else COLOR_TOKENS.get(status, COLOR_TOKENS["text_primary"])
    with ui.column().classes("items-start gap-0"):
        ui.label(label).style(
            f"font-size: 0.7rem; color: {COLOR_TOKENS['text_muted']}; text-transform: uppercase; letter-spacing: 0.04em"
        )
        with ui.row().classes("items-baseline gap-1"):
            ui.label(value).classes("ar-mono").style(f"font-size: 1.5rem; font-weight: 600; color: {color}")
            if unit:
                ui.label(unit).style(f"font-size: 0.75rem; color: {color}; opacity: 0.6")


def render_uptime_summary(stats: dict) -> None:
    with ui.row().classes("items-end gap-6"):
        for label, key in (("7 gün çalışma süresi", "uptime_7d"), ("30 gün çalışma süresi", "uptime_30d")):
            pct = stats.get(key)
            status = uptime_pct_to_status(pct)
            value = f"{pct}" if pct is not None else "-"
            _big_metric(label, value, "%" if pct is not None else "", status)


def render_uptime_timeline(timeline: list[dict]) -> None:
    with ui.row().classes("gap-0.5 items-end"):
        for day in timeline:
            color = COLOR_TOKENS[_UPTIME_DAY_STATUS.get(day["status"], "neutral")]
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
    with ui.row().classes("items-stretch gap-3"):
        _stat_card(f"{summary['healthy_count']}/{summary['total_targets']}", "Erişilebilir")
        _stat_card(f"{summary['safe_count']}/{summary['total_targets']}", "Güvenli")
        alert_status = "bad" if summary["open_alerts_count"] else "neutral"
        _stat_card(str(summary["open_alerts_count"]), "Açık Uyarı", alert_status)
        if summary["average_score"] is None:
            _stat_card("-", "Ortalama Not")
        else:
            _stat_card(
                f"{summary['average_score']} ({summary['average_grade']})",
                "Ortalama Not",
                grade_to_status(summary["average_grade"]),
            )


def render_grade_distribution(distribution: dict) -> None:
    data = [
        {"name": grade, "value": count, "itemStyle": {"color": GRADE_GRADIENT_COLORS.get(grade, COLOR_TOKENS["neutral"])}}
        for grade, count in distribution.items()
        if count > 0
    ]
    if not data:
        render_empty_state("Harf notu verisi yok.")
        return
    options = {
        **ECHARTS_DARK_THEME,
        "tooltip": {**TOOLTIP_STYLE, "trigger": "item"},
        "legend": {"bottom": 0, "textStyle": {"color": COLOR_TOKENS["text_muted"]}},
        "series": [
            {
                "type": "pie",
                "radius": ["40%", "70%"],
                "avoidLabelOverlap": True,
                "data": data,
            }
        ],
    }
    ui.echart(options).classes("w-full h-64")


def render_rankings(rankings: dict) -> None:
    with ui.row().classes("w-full gap-8"):
        with ui.column().classes("gap-1"):
            ui.label("En Düşük Notlu 5").classes("text-subtitle1")
            if not rankings["lowest_grade"]:
                ui.label("Yeterli veri yok.").classes("text-caption text-grey")
            for entry in rankings["lowest_grade"]:
                with ui.row().classes("items-center gap-2"):
                    _grade_badge(entry["letter_grade"])
                    ui.link(entry["name"], f"/targets/{entry['id']}").classes("ar-link-plain")
                    ui.label(f"({entry['score']})").classes("text-caption text-grey ar-mono")
        with ui.column().classes("gap-1"):
            ui.label("En Yavaş 5").classes("text-subtitle1")
            if not rankings["slowest"]:
                ui.label("Yeterli veri yok.").classes("text-caption text-grey")
            for entry in rankings["slowest"]:
                with ui.row().classes("items-center gap-2"):
                    ui.link(entry["name"], f"/targets/{entry['id']}").classes("ar-link-plain")
                    ui.label(f"{entry['response_time_ms']:.0f} ms").classes("text-caption text-grey ar-mono")


def render_header_matrix(matrix: dict) -> None:
    headers = matrix["headers"]
    if not matrix["rows"]:
        render_empty_state("Hedef verisi yok.")
        return
    columns_template = "minmax(120px, 1fr) " + " ".join(["minmax(0, 1fr)"] * len(headers))
    with ui.element("div").classes("w-full").style(
        f"display: grid; grid-template-columns: {columns_template}; row-gap: 2px; column-gap: 8px; align-items: center;"
    ):
        ui.label("Hedef").classes("ar-mono").style(
            f"color: {COLOR_TOKENS['text_muted']}; font-size: 0.7rem; text-transform: uppercase"
        )
        for header in headers:
            ui.label(SECURITY_HEADER_LABELS.get(header, header)).style(
                f"color: {COLOR_TOKENS['text_muted']}; font-size: 0.7rem; text-align: center"
            )
        for row in matrix["rows"]:
            ui.label(row["name"]).style(f"color: {COLOR_TOKENS['text_primary']}")
            for header in headers:
                value = row[header]
                with ui.row().classes("w-full justify-center"):
                    if value is None:
                        ui.icon(STATUS_ICONS["neutral"]).style(f"color: {COLOR_TOKENS['neutral']}")
                    elif value:
                        ui.icon("check_circle").style(f"color: {COLOR_TOKENS['good']}")
                    else:
                        ui.icon("cancel").style(f"color: {COLOR_TOKENS['bad']}")


def render_certificate_calendar(entries: list[dict]) -> None:
    if not entries:
        ui.label("Sertifika verisi olan hedef yok.").classes("text-caption text-grey")
        return
    with ui.column().classes("w-full gap-1"):
        for entry in entries:
            status = cert_days_to_status(entry["days_remaining"])
            row_classes = f"w-full justify-between items-center ar-row-divider ar-status-stripe ar-status-stripe-{status} q-pl-sm"
            with ui.row().classes(row_classes):
                ui.link(entry["name"], f"/targets/{entry['id']}").classes("ar-link-plain")
                ui.label(f"{entry['expiry_date']} — kalan gün: {entry['days_remaining']}").classes("text-caption ar-mono")


def render_response_time_percentiles(stats: dict) -> None:
    if not stats["sample_size"]:
        render_empty_state("Yanıt süresi verisi yok.")
        return
    with ui.row().classes("items-end gap-6"):
        for label, key in (("p50", "p50"), ("p95", "p95"), ("p99", "p99")):
            _big_metric(label, f"{stats[key]:.0f}", "ms")
        ui.label(f"({stats['sample_size']} örnek)").classes("text-caption text-grey")


def render_score_heatmap(heatmap: dict) -> None:
    if not heatmap["targets"] or not heatmap["days"]:
        render_empty_state("Isı haritası için henüz yeterli veri yok.")
        return
    grid_top = 20
    grid_bottom = 90
    height = max(260, 36 * len(heatmap["targets"]) + grid_top + grid_bottom)
    options = {
        **ECHARTS_DARK_THEME,
        "tooltip": {**TOOLTIP_STYLE, "position": "top"},
        "grid": {"top": grid_top, "bottom": grid_bottom, "left": 120, "right": 20},
        "xAxis": {"type": "category", "data": heatmap["days"], "splitArea": {"show": True}},
        "yAxis": {"type": "category", "data": heatmap["targets"], "splitArea": {"show": True}},
        "visualMap": {
            "type": "continuous",
            "min": 0,
            "max": 100,
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": 8,
            "textStyle": {"color": COLOR_TOKENS["text_muted"]},
            "inRange": {"color": [COLOR_TOKENS["bad"], COLOR_TOKENS["warn"], COLOR_TOKENS["good"]]},
        },
        "series": [{"type": "heatmap", "data": heatmap["data"], "label": {"show": False}}],
    }
    ui.echart(options).classes("w-full").style(f"height: {height}px")


EVENT_TYPE_LABELS = {
    "target_added": "EKLENDİ",
    "alert_opened": "AÇILDI",
    "alert_resolved": "KAPANDI",
}


def render_event_feed(events: list[dict]) -> None:
    with ui.row().classes("items-center gap-2 q-mb-sm"):
        ui.element("div").classes("ar-console-live-dot")
        ui.label("CANLI").classes("ar-mono").style(
            f"font-size: 0.7rem; letter-spacing: 0.05em; color: {COLOR_TOKENS['good']}"
        )
    if not events:
        render_empty_state("Henüz olay yok.")
        return
    with ui.column().classes("w-full gap-0 ar-console"):
        for event in events:
            color = COLOR_TOKENS[event_type_to_status(event["type"])]
            type_label = EVENT_TYPE_LABELS.get(event["type"], event["type"].upper())
            with ui.element("div").classes("ar-event-row ar-console-row w-full").style(
                "display: grid; grid-template-columns: 16px 148px 84px 1fr; align-items: baseline; column-gap: 12px"
            ):
                ui.label(">").classes("ar-mono").style(f"color: {COLOR_TOKENS['text_muted']}; opacity: 0.5")
                ui.label(event["timestamp"]).classes("ar-mono").style(
                    f"color: {COLOR_TOKENS['text_muted']}; font-size: 0.8rem"
                )
                ui.label(f"[{type_label}]").classes("ar-mono").style(f"color: {color}; font-size: 0.8rem")
                ui.label(event["text"]).classes("ar-mono").style(
                    f"color: {COLOR_TOKENS['text_primary']}; font-size: 0.8rem; word-break: break-word"
                )


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
                with ui.row().classes("items-start gap-2"):
                    render_status_chip(severity_to_status(finding["severity"]), finding["severity"].upper())
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
        with ui.card().classes("w-full").style(
            f"background-color: {COLOR_TOKENS['bad']}22; border: 1px solid {COLOR_TOKENS['bad']}"
        ):
            ui.label(f"{alert['alert_type']} — {alert['message']}")
            ui.label(f"({alert['created_at']})").classes("text-caption text-grey")


def _copy_to_clipboard(value: str) -> None:
    ui.clipboard.write(value)
    ui.notify("Kopyalandı.", type="info")


def _render_value_cell(value: str, mono: bool = False, color: str | None = None) -> None:
    mono_class = "ar-mono" if mono else ""
    color_style = f"color: {color};" if color else ""
    if len(value) <= VALUE_TRUNCATE_LENGTH:
        ui.label(value).classes(mono_class).style(color_style)
        return
    truncated = value[:VALUE_TRUNCATE_LENGTH] + "…"
    with ui.expansion(truncated).classes("w-full"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.label(value).classes(f"text-caption {mono_class}").style(f"word-break: break-all; {color_style}")
            ui.button(icon="content_copy", on_click=lambda: _copy_to_clipboard(value)).props("flat dense round size=sm")


def _status_row(label: str, value: str, status: str = "neutral", mono: bool = False) -> None:
    color = COLOR_TOKENS["text_primary"] if status == "neutral" else COLOR_TOKENS.get(status, COLOR_TOKENS["text_primary"])
    icon = STATUS_ICONS.get(status) if status in ("good", "warn", "bad") else None
    stripe = f"ar-status-stripe ar-status-stripe-{status}" if status in ("good", "warn", "bad") else ""
    with ui.row().classes(f"w-full items-center justify-between q-py-xs q-pl-sm {stripe}".strip()):
        with ui.row().classes("items-center gap-2"):
            if icon:
                ui.icon(icon).style(f"color: {color}; font-size: 1rem")
            ui.label(label).style(f"color: {COLOR_TOKENS['text_muted']}")
        _render_value_cell(value, mono=mono, color=color)


def _trend_indicator(current_earned: int, previous_earned: int | None) -> None:
    if previous_earned is None:
        return
    if current_earned > previous_earned:
        ui.icon("arrow_upward").classes("text-sm").style(f"color: {COLOR_TOKENS['good']}")
    elif current_earned < previous_earned:
        ui.icon("arrow_downward").classes("text-sm").style(f"color: {COLOR_TOKENS['bad']}")
    else:
        ui.icon("remove").classes("text-sm").style(f"color: {COLOR_TOKENS['neutral']}")


def render_score_breakdown(last_check: dict | None, previous_check: dict | None = None) -> None:
    result = recompute_score_breakdown(last_check)
    if result is None:
        ui.label("Henüz kontrol verisi yok.")
        return

    previous_result = recompute_score_breakdown(previous_check) if previous_check else None
    previous_breakdown = previous_result["breakdown"] if previous_result and previous_result["breakdown"] else {}

    with ui.row().classes("items-center gap-2"):
        ui.label(f"Toplam: {result['score']} ({result['letter_grade']})").classes("text-weight-medium ar-mono")
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
            with ui.row().classes("w-full items-center gap-2 justify-between ar-row-divider"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{SCORE_CATEGORIES[category]['label']}: {info['earned']}/{info['max']}").classes(
                        "text-weight-medium"
                    )
                    _trend_indicator(info["earned"], previous_info["earned"] if previous_info else None)
            for deduction in info["deductions"]:
                with ui.row().classes("w-full items-center gap-2 q-ml-md"):
                    render_status_chip("bad", "kaldı")
                    ui.label(deduction["message"]).classes("text-caption")
                    ui.label(f"-{deduction['points']} puan").classes("text-caption text-grey ar-mono")


def render_status_table(last_check: dict | None) -> None:
    if last_check is None:
        render_empty_state("Henüz kontrol verisi yok.")
        return

    rows = [
        (
            "Erişilebilirlik",
            f"HTTP {last_check['status_code']}" if last_check["status_code"] else "Erişilemiyor",
            "good" if last_check["status_code"] else "bad",
            False,
        ),
        (
            "Yanıt Süresi",
            f"{last_check['response_time_ms']} ms" if last_check["response_time_ms"] else "-",
            "neutral",
            True,
        ),
        (
            "DNS",
            "Çözümlendi" if (last_check["dns_result"] or {}).get("resolved") else "Çözümlenemedi",
            "good" if (last_check["dns_result"] or {}).get("resolved") else "bad",
            False,
        ),
        (
            "HTTP→HTTPS Yönlendirme",
            "Var" if (last_check["redirect_result"] or {}).get("redirects_to_https") else "Yok",
            "good" if (last_check["redirect_result"] or {}).get("redirects_to_https") else "bad",
            False,
        ),
    ]

    dns_result = last_check["dns_result"] or {}

    def _hygiene_row(label: str, value: bool | None) -> tuple[str, str, str, bool]:
        if value is None:
            return (label, "Test edilemedi", "neutral", False)
        return (label, "Var" if value else "Yok", "good" if value else "bad", False)

    rows.append(_hygiene_row("SPF Kaydı", dns_result.get("spf_present")))
    rows.append(_hygiene_row("DMARC Kaydı", dns_result.get("dmarc_present")))
    rows.append(_hygiene_row("CAA Kaydı", dns_result.get("caa_present")))

    headers_result = last_check["headers_result"] or {}
    for name in SECURITY_HEADER_LABELS:
        info = (headers_result.get("security_headers") or {}).get(name, {})
        present = bool(info.get("present"))
        rows.append((name, f"Var — {info.get('value')}" if present else "Yok", "good" if present else "bad", False))
    for name, info in (headers_result.get("info_leak") or {}).items():
        reveals = bool(info.get("reveals_version"))
        text = f"Sürüm sızdırıyor: {info.get('value')}" if reveals else "Sorun yok"
        rows.append((f"{name} (sızıntı)", text, "bad" if reveals else "good", False))

    cookies = headers_result.get("cookies") or []
    if not cookies:
        rows.append(("Çerezler", "Çerez kurulmadı.", "neutral", False))
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
            rows.append((f"Çerez: {cookie['name']}", flags_text, "neutral" if not flags else "bad", False))

    with ui.column().classes("w-full gap-0"):
        for label, value, status, mono in rows:
            _status_row(label, str(value), status, mono)


def render_tls_status(last_check: dict | None) -> None:
    if last_check is None:
        render_empty_state("Henüz kontrol verisi yok.")
        return

    tls_result = last_check["tls_result"] or {}
    rows = []
    if tls_result.get("applicable"):
        tls_text = ("Geçerli" if tls_result.get("chain_valid") else "Geçersiz") + f", kalan gün: {tls_result.get('days_remaining')}"
        rows.append(("TLS", tls_text, "good" if tls_result.get("chain_valid") else "bad", False))

        old_supported = tls_result.get("old_protocols_supported")
        if old_supported is None:
            rows.append(("TLS 1.0 / 1.1", "Test edilemedi", "neutral", False))
        else:
            rows.append(
                ("TLS 1.0 / 1.1", "Kabul ediliyor" if old_supported else "Reddediliyor", "bad" if old_supported else "good", False)
            )

        tls13 = tls_result.get("tls_1_3_supported")
        if tls13 is None:
            rows.append(("TLS 1.3", "Test edilemedi", "neutral", False))
        else:
            rows.append(("TLS 1.3", "Destekleniyor" if tls13 else "Desteklenmiyor", "good" if tls13 else "warn", False))

        cipher_name = tls_result.get("cipher_name")
        if cipher_name:
            cipher_text = f"{cipher_name} ({tls_result.get('negotiated_protocol')})"
            weak_cipher = bool(tls_result.get("weak_cipher"))
            if weak_cipher:
                cipher_text += " — zayıf"
            rows.append(("Şifre Takımı", cipher_text, "bad" if weak_cipher else "neutral", False))
    else:
        rows.append(("TLS", "Uygulanamıyor", "neutral", False))

    with ui.column().classes("w-full gap-0"):
        for label, value, status, mono in rows:
            _status_row(label, str(value), status, mono)


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
                    with ui.row().classes("w-full justify-between items-center ar-row-divider"):
                        ui.label(label).classes("text-weight-medium")
                        _render_value_cell(str(value))
                if cert.get("san"):
                    with ui.row().classes("w-full justify-between items-center ar-row-divider"):
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


def _line_color_for(value_key: str, points: list[dict]) -> str:
    if value_key != "score" or not points:
        return COLOR_TOKENS["text_primary"]
    last_score = points[-1].get("score")
    if last_score is None:
        return COLOR_TOKENS["text_primary"]
    return COLOR_TOKENS[grade_to_status(letter_grade(int(last_score)))]


def _to_epoch_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _emphasize_last_point(pairs: list, color: str) -> list:
    if not pairs or pairs[-1][1] is None:
        return pairs
    data = list(pairs)
    data[-1] = {
        "value": data[-1],
        "symbolSize": 8,
        "itemStyle": {"color": color, "borderColor": color},
    }
    return data


SCORE_THRESHOLD_MARKLINE = {
    "silent": True,
    "symbol": "none",
    "lineStyle": {"type": "dashed", "color": COLOR_TOKENS["border_subtle"], "width": 1},
    "label": {"color": COLOR_TOKENS["text_muted"], "fontSize": 10, "position": "insideEndTop"},
    "data": [
        {"yAxis": 60, "label": {"formatter": "D"}},
        {"yAxis": 70, "label": {"formatter": "C"}},
        {"yAxis": 80, "label": {"formatter": "B"}},
        {"yAxis": 90, "label": {"formatter": "A"}},
    ],
}


def _nice_round_bounds(lo: float, hi: float) -> tuple[float, float, float]:
    span = hi - lo
    if span <= 0:
        return lo, hi, max(abs(hi), 1)
    magnitude = 10 ** math.floor(math.log10(span))
    ratio = span / magnitude
    step = magnitude / 5 if ratio < 2 else magnitude / 2 if ratio < 5 else magnitude
    lo_rounded = math.floor(lo / step) * step
    hi_rounded = math.ceil(hi / step) * step
    if lo_rounded == hi_rounded:
        hi_rounded += step
    return lo_rounded, hi_rounded, step


def _y_axis_bounds(value_key: str, values: list) -> tuple[float, float, float | None]:
    if value_key == "score":
        return (0, 100, None)
    clean = [v for v in values if v is not None]
    if not clean:
        return (0, 1, None)
    lo, hi = min(clean), max(clean)
    if lo == hi:
        pad = max(abs(lo) * 0.1, 1)
        lo, hi = lo - pad, hi + pad
    else:
        pad = (hi - lo) * 0.1
        lo, hi = lo - pad, hi + pad
    lo, hi, step = _nice_round_bounds(lo, hi)
    if min(clean) >= 0:
        lo = max(lo, 0)
    return lo, hi, step


def _y_axis_options(value_key: str, values: list) -> dict:
    lo, hi, step = _y_axis_bounds(value_key, values)
    options = {
        "type": "value",
        "min": lo,
        "max": hi,
        "axisLine": {"lineStyle": {"color": COLOR_TOKENS["border_subtle"]}},
        "axisLabel": {"color": COLOR_TOKENS["text_muted"], "fontSize": 11},
        "splitLine": {"lineStyle": {"color": COLOR_TOKENS["border_subtle"]}},
    }
    if step is not None:
        options["interval"] = step
    return options


def _time_axis_options(now_ms: int, window_minutes: int) -> dict:
    return {
        "type": "time",
        "min": now_ms - window_minutes * 60_000,
        "max": now_ms,
        "axisLine": {"lineStyle": {"color": COLOR_TOKENS["border_subtle"]}},
        "axisLabel": {"color": COLOR_TOKENS["text_muted"], "fontSize": 11, "formatter": "{HH}:{mm}:{ss}"},
        "splitLine": {"show": False},
    }


def build_line_chart(points: list[dict], value_key: str, window_minutes: int) -> ui.echart:
    pairs = [[_to_epoch_ms(point["checked_at"]), point[value_key]] for point in points]
    values = [point[value_key] for point in points]
    line_color = _line_color_for(value_key, points)
    series = {
        "type": "line",
        "data": _emphasize_last_point(pairs, line_color),
        "showSymbol": True,
        "symbolSize": 4,
        "lineStyle": {"color": line_color, "width": 2},
        "itemStyle": {"color": line_color},
        "areaStyle": {"color": _hex_to_rgba(line_color, 0.12)},
    }
    if value_key == "score":
        series["markLine"] = SCORE_THRESHOLD_MARKLINE
    now_ms = _to_epoch_ms(datetime.utcnow())
    options = {
        **ECHARTS_DARK_THEME,
        "tooltip": {**TOOLTIP_STYLE, "trigger": "axis"},
        "grid": {"top": 24, "bottom": 32, "left": 48, "right": 16, "containLabel": True},
        "xAxis": _time_axis_options(now_ms, window_minutes),
        "yAxis": _y_axis_options(value_key, values),
        "series": [series],
        **CHART_ANIMATION_OPTIONS,
    }
    return ui.echart(options).classes("w-full h-64")


def update_line_chart(chart: ui.echart, points: list[dict], value_key: str) -> None:
    pairs = [[_to_epoch_ms(point["checked_at"]), point[value_key]] for point in points]
    values = [point[value_key] for point in points]
    line_color = _line_color_for(value_key, points)
    series = chart.options["series"][0]
    series["data"] = _emphasize_last_point(pairs, line_color)
    series["lineStyle"]["color"] = line_color
    series["itemStyle"]["color"] = line_color
    series["areaStyle"]["color"] = _hex_to_rgba(line_color, 0.12)
    lo, hi, step = _y_axis_bounds(value_key, values)
    chart.options["yAxis"]["min"] = lo
    chart.options["yAxis"]["max"] = hi
    if step is not None:
        chart.options["yAxis"]["interval"] = step
    elif "interval" in chart.options["yAxis"]:
        del chart.options["yAxis"]["interval"]
    chart.update()


def shift_time_axis(chart: ui.echart, window_minutes: int) -> None:
    now_ms = _to_epoch_ms(datetime.utcnow())
    chart.options["xAxis"]["max"] = now_ms
    chart.options["xAxis"]["min"] = now_ms - window_minutes * 60_000
    chart.update()


def flash_last_point(chart: ui.echart, value_key: str, points: list[dict]) -> None:
    color = _line_color_for(value_key, points)
    data = chart.options["series"][0]["data"]
    if not data or not isinstance(data[-1], dict):
        return
    data[-1]["itemStyle"] = {"color": color, "borderColor": color, "shadowBlur": 20, "shadowColor": color}
    data[-1]["symbolSize"] = 14
    chart.update()

    def _revert() -> None:
        current_data = chart.options["series"][0]["data"]
        if current_data and isinstance(current_data[-1], dict):
            current_data[-1]["itemStyle"] = {"color": color, "borderColor": color}
            current_data[-1]["symbolSize"] = 8
            chart.update()

    ui.timer(0.8, _revert, once=True)


TIMING_SERIES = [
    ("dns_ms", "DNS"),
    ("tcp_ms", "TCP"),
    ("tls_ms", "TLS"),
    ("ttfb_ms", "TTFB"),
    ("download_ms", "İndirme"),
]

TIMING_COLOR_RAMP = ["#a371f7", "#539bf5", "#39c5cf", "#b3d334", "#e878c9"]


def build_stacked_bar_chart(points: list[dict], window_minutes: int) -> ui.echart:
    now_ms = _to_epoch_ms(datetime.utcnow())
    options = {
        **ECHARTS_DARK_THEME,
        "tooltip": {**TOOLTIP_STYLE, "trigger": "axis"},
        "legend": {"textStyle": {"color": COLOR_TOKENS["text_muted"]}},
        "xAxis": _time_axis_options(now_ms, window_minutes),
        "yAxis": {
            "type": "value",
            "name": "ms",
            "axisLine": {"lineStyle": {"color": COLOR_TOKENS["border_subtle"]}},
            "axisLabel": {"color": COLOR_TOKENS["text_muted"], "fontSize": 11},
            "splitLine": {"lineStyle": {"color": COLOR_TOKENS["border_subtle"]}},
        },
        "series": [
            {
                "name": name,
                "type": "bar",
                "stack": "total",
                "barWidth": 8,
                "data": [[_to_epoch_ms(point["checked_at"]), point[key]] for point in points],
                "itemStyle": {"color": TIMING_COLOR_RAMP[index]},
            }
            for index, (key, name) in enumerate(TIMING_SERIES)
        ],
        **CHART_ANIMATION_OPTIONS,
    }
    return ui.echart(options).classes("w-full h-64")


def update_stacked_bar_chart(chart: ui.echart, points: list[dict]) -> None:
    for index, (key, _name) in enumerate(TIMING_SERIES):
        chart.options["series"][index]["data"] = [[_to_epoch_ms(point["checked_at"]), point[key]] for point in points]
    chart.update()
