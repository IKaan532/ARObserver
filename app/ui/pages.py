from datetime import datetime, timedelta

from nicegui import ui

from app import services
from app.scheduler import is_target_running, trigger_manual_check
from app.ui.components import (
    build_line_chart,
    render_alerts,
    render_content_section,
    render_status_table,
    render_target_card,
    update_line_chart,
)

POLL_INTERVAL_SECONDS = 10.0
GRADE_OPTIONS = ["Tümü", "A", "B", "C", "D", "F"]


@ui.page("/")
def index_page() -> None:
    ui.page_title("ARObserver — Hedefler")
    ui.label("Hedefler").classes("text-h4")

    state = {"grade": "Tümü", "group": "Tümü"}

    @ui.refreshable
    def render_cards() -> None:
        cards = services.list_target_cards()
        filtered = [
            card
            for card in cards
            if (state["grade"] == "Tümü" or card["letter_grade"] == state["grade"])
            and (state["group"] == "Tümü" or state["group"] in card["tags"])
        ]
        if not filtered:
            ui.label("Gösterilecek hedef yok.")
            return
        with ui.grid(columns=3).classes("w-full gap-4"):
            for card in filtered:
                render_target_card(card, is_target_running(card["id"]), handle_check_now)

    def handle_check_now(target_id: int) -> None:
        result = trigger_manual_check(target_id)
        if result == "cooldown":
            ui.notify("Bu hedef için 30 saniye içinde tekrar tetiklenemez, bekleyin.", type="warning")
        elif result == "running":
            ui.notify("Kontrol zaten çalışıyor.", type="info")
        render_cards.refresh()

    def trigger_all() -> None:
        for card in services.list_target_cards():
            trigger_manual_check(card["id"])
        render_cards.refresh()

    def on_filter_change() -> None:
        state["grade"] = grade_select.value
        state["group"] = group_select.value
        render_cards.refresh()

    with ui.row().classes("items-center gap-4"):
        grade_select = ui.select(GRADE_OPTIONS, value="Tümü", label="Harf Notu", on_change=lambda e: on_filter_change())
        group_select = ui.select(
            ["Tümü"] + services.list_groups(), value="Tümü", label="Grup", on_change=lambda e: on_filter_change()
        )
        ui.button("Tümünü Şimdi Kontrol Et", on_click=trigger_all)

    last_update_label = ui.label("son güncelleme: --:--:--").classes("text-caption text-grey")

    render_cards()

    def tick() -> None:
        render_cards.refresh()
        last_update_label.set_text(f"son güncelleme: {datetime.now().strftime('%H:%M:%S')}")

    ui.timer(POLL_INTERVAL_SECONDS, tick)


@ui.page("/targets/{target_id}")
def detail_page(target_id: int) -> None:
    detail = services.get_target_detail(target_id)
    if detail is None:
        ui.label("Hedef bulunamadı").classes("text-h5")
        return

    ui.page_title(f"{detail['name']} — ARObserver")
    ui.link("← Hedefler", "/")
    ui.label(detail["name"]).classes("text-h4")
    ui.label(f"{detail['url']} — kontrol aralığı: {detail['interval_minutes']} dk").classes("text-caption text-grey")

    render_alerts(detail["open_alerts"])

    with ui.row().classes("items-center gap-2"):
        check_button = ui.button("Şimdi Kontrol Et")
        spinner = ui.spinner(size="1.5em")
        spinner.set_visibility(is_target_running(target_id))

    last_update_label = ui.label("son güncelleme: --:--:--").classes("text-caption text-grey")

    window_start = datetime.utcnow() - timedelta(minutes=services.CHART_WINDOW_MINUTES)
    points = services.get_chart_points(target_id)

    ui.label("Yanıt Süresi (ms)").classes("text-h6")
    response_chart = build_line_chart("Yanıt Süresi (ms)", points, "response_time_ms")
    ui.label("Skor").classes("text-h6")
    score_chart = build_line_chart("Skor", points, "score")

    ui.label("Son Kontrol Durumu").classes("text-h6")
    render_status_table(detail["last_check"])

    def handle_reset_baseline() -> None:
        services.reset_baseline(target_id)
        trigger_manual_check(target_id)
        ui.notify("Temel çizgi sıfırlandı, yeni kontrol tetiklendi.", type="info")

    render_content_section(
        detail["last_check"]["content_result"] if detail["last_check"] else None, handle_reset_baseline
    )

    def handle_check_now() -> None:
        result = trigger_manual_check(target_id)
        if result == "cooldown":
            ui.notify("30 saniye içinde tekrar tetiklenemez, bekleyin.", type="warning")
        elif result == "running":
            ui.notify("Kontrol zaten çalışıyor.", type="info")
        spinner.set_visibility(is_target_running(target_id))
        check_button.set_enabled(not is_target_running(target_id))

    check_button.on_click(handle_check_now)

    def tick() -> None:
        running = is_target_running(target_id)
        spinner.set_visibility(running)
        check_button.set_enabled(not running)

        since = points[-1]["checked_at"] if points else window_start
        new_points = services.get_chart_points(target_id, since=since)
        if not new_points:
            return

        points.extend(new_points)
        cutoff = datetime.utcnow() - timedelta(minutes=services.CHART_WINDOW_MINUTES)
        while points and points[0]["checked_at"] < cutoff:
            points.pop(0)
        if len(points) > services.MAX_CHART_POINTS:
            del points[: len(points) - services.MAX_CHART_POINTS]

        update_line_chart(response_chart, points, "response_time_ms")
        update_line_chart(score_chart, points, "score")
        last_update_label.set_text(f"son güncelleme: {datetime.now().strftime('%H:%M:%S')}")

    ui.timer(POLL_INTERVAL_SECONDS, tick)
