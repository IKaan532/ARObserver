from collections.abc import Callable

from nicegui import ui

GRADE_COLORS = {
    "A": "green",
    "B": "light-green",
    "C": "orange",
    "D": "deep-orange",
    "F": "red",
}
GRADE_COLOR_NONE = "grey"

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


def render_target_card(card: dict, running: bool, on_check_now: Callable[[int], None]) -> None:
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.link(card["name"], f"/targets/{card['id']}").classes("text-h6")
            _grade_badge(card["letter_grade"])
        if card["status_code"]:
            ui.badge(f"HTTP {card['status_code']}", color="green")
        else:
            ui.badge("Erişilemiyor", color="red")
        ui.label(card["url"]).classes("text-caption text-grey")
        if card["checked_at"]:
            ui.label(f"Son kontrol: {card['checked_at']}").classes("text-caption")
        if card["cert_days_remaining"] is not None:
            ui.label(f"Sertifikaya kalan gün: {card['cert_days_remaining']}").classes("text-caption")
        render_check_now_button(card["id"], running, lambda: on_check_now(card["id"]))


def render_alerts(open_alerts: list[dict]) -> None:
    if not open_alerts:
        return
    ui.label("Açık Uyarılar").classes("text-h6")
    for alert in open_alerts:
        with ui.card().classes("w-full bg-red-1"):
            ui.label(f"{alert['alert_type']} — {alert['message']}")
            ui.label(f"({alert['created_at']})").classes("text-caption text-grey")


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

    tls_result = last_check["tls_result"] or {}
    if tls_result.get("applicable"):
        tls_text = ("Geçerli" if tls_result.get("chain_valid") else "Geçersiz") + f", kalan gün: {tls_result.get('days_remaining')}"
    else:
        tls_text = "Uygulanamıyor"
    rows.append(("TLS", tls_text))

    headers_result = last_check["headers_result"] or {}
    for name in SECURITY_HEADER_LABELS:
        info = (headers_result.get("security_headers") or {}).get(name, {})
        rows.append((name, f"Var — {info.get('value')}" if info.get("present") else "Yok"))
    for name, info in (headers_result.get("info_leak") or {}).items():
        text = f"Sürüm sızdırıyor: {info.get('value')}" if info.get("reveals_version") else "Sorun yok"
        rows.append((f"{name} (sızıntı)", text))

    rows.append(("Skor", f"{last_check['score']} ({last_check['letter_grade']})"))

    with ui.column().classes("w-full gap-1"):
        for label, value in rows:
            with ui.row().classes("w-full justify-between border-b"):
                ui.label(label).classes("text-weight-medium")
                ui.label(value)

    if last_check.get("score_reasons"):
        ui.label("Skor Gerekçeleri").classes("text-h6 q-mt-md")
        for reason in last_check["score_reasons"]:
            ui.label(f"- {reason}")


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


def build_line_chart(title: str, points: list[dict], value_key: str) -> ui.echart:
    labels = [point["label"] for point in points]
    values = [point[value_key] for point in points]
    options = {
        "title": {"text": title},
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
