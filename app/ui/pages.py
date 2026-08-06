import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

from nicegui import ui

from app import services
from app.scheduler import is_target_running, trigger_manual_check
from app.ui.components import (
    build_line_chart,
    build_stacked_bar_chart,
    render_active_filters,
    render_alerts,
    render_content_section,
    render_certificate_calendar,
    render_downtime_incidents,
    render_event_feed,
    render_grade_distribution,
    render_header_matrix,
    render_overview_summary,
    render_rankings,
    render_response_time_percentiles,
    render_score_heatmap,
    render_status_table,
    render_target_card,
    render_uptime_summary,
    render_uptime_timeline,
    update_line_chart,
    update_stacked_bar_chart,
)

POLL_INTERVAL_SECONDS = 10.0
GRADE_OPTIONS = ["A", "B", "C", "D", "F"]


@ui.page("/")
def index_page(grade: str = "", group: str = "", q: str = "") -> None:
    ui.page_title("ARObserver — Hedefler")
    ui.add_head_html(
        """
        <style>
        @keyframes ar-event-slide-in {
            from { transform: translateY(-12px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        .ar-event-row { animation: ar-event-slide-in 0.35s ease-out; }
        </style>
        """
    )
    ui.label("Hedefler").classes("text-h4")

    @ui.refreshable
    def render_overview() -> None:
        render_overview_summary(services.get_overview_summary())

    render_overview()

    with ui.row().classes("w-full gap-8 items-start"):
        with ui.column().classes("gap-1"):
            ui.label("Harf Notu Dağılımı").classes("text-subtitle1")

            @ui.refreshable
            def render_distribution() -> None:
                render_grade_distribution(services.get_overview_summary()["grade_distribution"])

            render_distribution()
        with ui.column().classes("gap-1 flex-grow"):
            ui.label("Sıralamalar").classes("text-subtitle1")

            @ui.refreshable
            def render_rankings_section() -> None:
                render_rankings(services.get_rankings())

            render_rankings_section()

    with ui.row().classes("w-full gap-8 items-start"):
        with ui.column().classes("gap-1 flex-grow"):
            ui.label("Güvenlik Başlığı Matrisi").classes("text-subtitle1")

            @ui.refreshable
            def render_header_matrix_section() -> None:
                render_header_matrix(services.get_header_matrix())

            render_header_matrix_section()
        with ui.column().classes("gap-1"):
            ui.label("Sertifika Takvimi").classes("text-subtitle1")

            @ui.refreshable
            def render_certificate_calendar_section() -> None:
                render_certificate_calendar(services.get_certificate_calendar())

            render_certificate_calendar_section()

    ui.label("Skor Isı Haritası (30 gün)").classes("text-subtitle1")

    @ui.refreshable
    def render_score_heatmap_section() -> None:
        render_score_heatmap(services.get_score_heatmap())

    render_score_heatmap_section()

    ui.label("Canlı Olay Akışı").classes("text-subtitle1")

    @ui.refreshable
    def render_event_feed_section() -> None:
        render_event_feed(services.get_event_feed())

    with ui.scroll_area().classes("w-full h-96 border rounded"):
        render_event_feed_section()

    state = {
        "grades": [value for value in grade.split(",") if value],
        "groups": [value for value in group.split(",") if value],
        "query": q,
    }

    def matches(card: dict) -> bool:
        if state["grades"] and card["letter_grade"] not in state["grades"]:
            return False
        if state["groups"] and not (set(card["tags"]) & set(state["groups"])):
            return False
        if state["query"]:
            needle = state["query"].lower()
            if needle not in card["name"].lower() and needle not in card["url"].lower():
                return False
        return True

    def sync_url() -> None:
        params = {}
        if state["grades"]:
            params["grade"] = ",".join(state["grades"])
        if state["groups"]:
            params["group"] = ",".join(state["groups"])
        if state["query"]:
            params["q"] = state["query"]
        query_string = urlencode(params)
        new_url = "/" + (f"?{query_string}" if query_string else "")
        ui.run_javascript(f"history.replaceState(null, '', {json.dumps(new_url)})")

    @ui.refreshable
    def render_cards() -> None:
        cards = services.list_target_cards()
        filtered = [card for card in cards if matches(card)]

        render_active_filters(state, remove_grade, remove_group, clear_query, clear_all)
        ui.label(f"{len(cards)} hedeften {len(filtered)}'ü gösteriliyor").classes("text-caption text-grey")

        if not cards:
            ui.label("Henüz izlenen hedef yok. targets.yaml dosyasını kontrol edin.")
            return
        if not filtered:
            ui.label("Eşleşen hedef yok.")
            return

        with ui.grid(columns=3).classes("w-full gap-4"):
            for card in filtered:
                render_target_card(
                    card, is_target_running(card["id"]), handle_check_now, add_group_filter, open_edit_dialog
                )

    def on_filter_change() -> None:
        state["grades"] = list(grade_select.value or [])
        state["groups"] = list(group_select.value or [])
        state["query"] = search_input.value or ""
        sync_url()
        render_cards.refresh()

    def remove_grade(value: str) -> None:
        grade_select.set_value([v for v in grade_select.value if v != value])
        on_filter_change()

    def remove_group(value: str) -> None:
        group_select.set_value([v for v in group_select.value if v != value])
        on_filter_change()

    def clear_query() -> None:
        search_input.set_value("")
        on_filter_change()

    def clear_all() -> None:
        grade_select.set_value([])
        group_select.set_value([])
        search_input.set_value("")
        on_filter_change()

    def add_group_filter(tag: str) -> None:
        current = list(group_select.value or [])
        if tag not in current:
            current.append(tag)
        group_select.set_value(current)
        on_filter_change()

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

    def open_target_dialog(target: dict | None) -> None:
        is_edit = target is not None

        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Hedefi Düzenle" if is_edit else "Yeni Hedef").classes("text-h6")
            name_input = ui.input(label="Ad", value=target["name"] if is_edit else "").classes("w-full")
            url_input = ui.input(label="URL", value=target["url"] if is_edit else "").classes("w-full")
            interval_input = ui.number(
                label="Kontrol Aralığı (dk)", value=target["interval_minutes"] if is_edit else 5, min=1, precision=0
            ).classes("w-full")
            tags_select = ui.select(
                services.list_groups(),
                value=list(target["tags"]) if is_edit else [],
                multiple=True,
                new_value_mode="add-unique",
                with_input=True,
                label="Grup/Etiket",
            ).classes("w-full")
            keyword_input = ui.input(
                label="Beklenen Anahtar Kelime (isteğe bağlı)",
                value=(target["expected_keyword"] or "") if is_edit else "",
            ).classes("w-full")
            status_input = ui.number(
                label="Beklenen Durum Kodu",
                value=target["expected_status"] if is_edit else 200,
                min=100,
                max=599,
                precision=0,
            ).classes("w-full")
            active_switch = ui.switch("Aktif", value=target["active"] if is_edit else True)

            def save() -> None:
                try:
                    if is_edit:
                        services.update_target(
                            target["id"],
                            name_input.value,
                            url_input.value,
                            int(interval_input.value),
                            list(tags_select.value or []),
                            keyword_input.value,
                            active_switch.value,
                            int(status_input.value),
                        )
                    else:
                        new_id = services.create_target(
                            name_input.value,
                            url_input.value,
                            int(interval_input.value),
                            list(tags_select.value or []),
                            keyword_input.value,
                            int(status_input.value),
                        )
                        ui.notify(f"Hedef eklendi, ilk kontrol tetiklendi (id {new_id}).", type="positive")
                except ValueError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                dialog.close()
                render_cards.refresh()
                if is_edit:
                    ui.notify("Kaydedildi.", type="positive")

            def confirm_delete() -> None:
                with ui.dialog() as confirm, ui.card():
                    ui.label(f"'{target['name']}' silinsin mi? Geçmiş kayıtları da silinecek.")
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Vazgeç", on_click=confirm.close).props("flat")

                        def do_delete() -> None:
                            services.delete_target(target["id"])
                            confirm.close()
                            dialog.close()
                            render_cards.refresh()
                            ui.notify("Hedef silindi.", type="info")

                        ui.button("Sil", on_click=do_delete, color="red")
                confirm.open()

            def handle_reset() -> None:
                services.reset_baseline(target["id"])
                trigger_manual_check(target["id"])
                ui.notify("Temel çizgi sıfırlandı, yeni kontrol tetiklendi.", type="info")

            with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
                if is_edit:
                    ui.button("Yeni Durumu Temel Al", on_click=handle_reset).props("flat")
                    ui.button("Sil", on_click=confirm_delete, color="red").props("flat")
                ui.button("Vazgeç", on_click=dialog.close).props("flat")
                ui.button("Kaydet", on_click=save)

        dialog.open()

    def open_edit_dialog(target_id: int) -> None:
        target = services.get_editable_target(target_id)
        if target is not None:
            open_target_dialog(target)

    def open_create_dialog() -> None:
        open_target_dialog(None)

    with ui.row().classes("items-center gap-4"):
        grade_select = ui.select(
            GRADE_OPTIONS, value=state["grades"], multiple=True, label="Harf Notu", on_change=lambda e: on_filter_change()
        )
        group_select = ui.select(
            services.list_groups(),
            value=state["groups"],
            multiple=True,
            label="Grup",
            on_change=lambda e: on_filter_change(),
        )
        search_input = ui.input(label="Ara (ad/url)", value=state["query"], on_change=lambda e: on_filter_change())
        ui.button("Tümünü Şimdi Kontrol Et", on_click=trigger_all)
        ui.button("+ Yeni Hedef", on_click=open_create_dialog)

    last_update_label = ui.label("").classes("text-caption text-grey")
    last_update_label.set_visibility(False)

    render_cards()

    def tick() -> None:
        render_cards.refresh()
        render_overview.refresh()
        render_distribution.refresh()
        render_rankings_section.refresh()
        render_header_matrix_section.refresh()
        render_certificate_calendar_section.refresh()
        render_score_heatmap_section.refresh()
        render_event_feed_section.refresh()
        last_update_label.set_text(f"son güncelleme: {datetime.now().strftime('%H:%M:%S')}")
        last_update_label.set_visibility(True)

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

    last_update_label = ui.label("").classes("text-caption text-grey")
    last_update_label.set_visibility(False)

    ui.label("Kullanılabilirlik").classes("text-h6")

    @ui.refreshable
    def render_uptime_section() -> None:
        render_uptime_summary(services.get_uptime_stats(target_id))
        render_uptime_timeline(services.get_uptime_timeline(target_id))
        render_downtime_incidents(services.get_downtime_incidents(target_id))

    render_uptime_section()

    ui.label("Yanıt Süresi Yüzdelikleri (7 gün)").classes("text-h6")

    @ui.refreshable
    def render_percentiles_section() -> None:
        render_response_time_percentiles(services.get_response_time_percentiles(target_id))

    render_percentiles_section()

    window_start = datetime.utcnow() - timedelta(minutes=services.CHART_WINDOW_MINUTES)
    points = services.get_chart_points(target_id)

    ui.label("Yanıt Süresi (ms)").classes("text-h6")
    response_chart = build_line_chart(points, "response_time_ms")
    ui.label("Skor").classes("text-h6")
    score_chart = build_line_chart(points, "score")
    ui.label("Zaman Kırılımı").classes("text-h6")
    timing_chart = build_stacked_bar_chart(points)
    ui.label("Sayfa Boyutu").classes("text-h6")
    size_chart = build_line_chart(points, "body_size_kb")

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
        render_uptime_section.refresh()
        render_percentiles_section.refresh()

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
        update_stacked_bar_chart(timing_chart, points)
        update_line_chart(size_chart, points, "body_size_kb")
        last_update_label.set_text(f"son güncelleme: {datetime.now().strftime('%H:%M:%S')}")
        last_update_label.set_visibility(True)

    ui.timer(POLL_INTERVAL_SECONDS, tick)
