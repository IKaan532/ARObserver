import asyncio
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode

from nicegui import ui

from app import reports, services
from app.auth import (
    attempt_login,
    clear_session_authentication,
    is_safe_redirect_path,
    mark_session_authenticated,
)
from app.config import settings
from app.scheduler import trigger_manual_check
from app.ui.components import (
    TOKEN_CSS,
    build_line_chart,
    build_stacked_bar_chart,
    format_last_update,
    render_active_filters,
    render_alerts,
    render_certificate_calendar,
    render_certificate_chain,
    render_content_section,
    render_ct_log_result,
    render_deep_check_result,
    render_downtime_incidents,
    grade_to_status,
    render_empty_state,
    render_event_feed,
    render_grade_distribution,
    render_header_matrix,
    render_overview_summary,
    render_page_shell,
    render_panel,
    render_rankings,
    render_response_time_percentiles,
    render_score_breakdown,
    render_score_heatmap,
    render_status_table,
    render_target_card,
    render_tls_status,
    render_uptime_summary,
    render_uptime_timeline,
    flash_last_point,
    shift_time_axis,
    update_line_chart,
    update_stacked_bar_chart,
)

POLL_INTERVAL_SECONDS = 10.0
GRADE_OPTIONS = ["A", "B", "C", "D", "F"]

ui.add_head_html(
    TOKEN_CSS
    + """
    <style>
    @keyframes ar-event-slide-in {
        from { transform: translateY(-12px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
    .ar-event-row { animation: ar-event-slide-in 0.35s ease-out; }
    </style>
    """,
    shared=True,
)


def _current_request():
    return ui.context.client.request


def _do_logout() -> None:
    request = _current_request()
    if request is not None:
        session_id = request.session.get("id")
        if session_id is not None:
            clear_session_authentication(session_id)
    ui.navigate.to("/login")


@ui.page("/login")
def login_page() -> None:
    ui.page_title("Giriş — ARObserver")

    def try_login() -> None:
        client_key = ui.context.client.ip or "unknown"
        if attempt_login(password_input.value, client_key):
            request = _current_request()
            redirect_to = "/"
            if request is not None:
                session_id = request.session.get("id")
                if session_id is not None:
                    mark_session_authenticated(session_id)
                redirect_to = request.session.pop("redirect_to", "/")
                if not is_safe_redirect_path(redirect_to):
                    redirect_to = "/"
            ui.navigate.to(redirect_to)
        else:
            ui.notify("Hatalı şifre veya çok fazla deneme, biraz bekleyin.", type="negative")

    with ui.card().classes("absolute-center"):
        ui.label("ARObserver — Giriş").classes("text-h6")
        password_input = ui.input("Şifre", password=True, password_toggle_button=True).on(
            "keydown.enter", try_login
        )
        ui.button("Giriş", on_click=try_login).classes("w-full")


VALID_TABS = ("hedefler", "genel-bakis", "olaylar")


@ui.page("/")
def index_page(tab: str = "hedefler", grade: str = "", group: str = "", q: str = "") -> None:
    ui.page_title("ARObserver — Hedefler")

    initial_tab = tab if tab in VALID_TABS else "hedefler"

    state = {
        "grades": [value for value in grade.split(",") if value],
        "groups": [value for value in group.split(",") if value],
        "query": q,
    }
    current_tab = {"value": initial_tab}

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
        params = {"tab": current_tab["value"]}
        if state["grades"]:
            params["grade"] = ",".join(state["grades"])
        if state["groups"]:
            params["group"] = ",".join(state["groups"])
        if state["query"]:
            params["q"] = state["query"]
        query_string = urlencode(params)
        new_url = "/" + (f"?{query_string}" if query_string else "")
        ui.run_javascript(f"history.replaceState(null, '', {json.dumps(new_url)})")

    with render_page_shell(on_logout=_do_logout):
        @ui.refreshable
        def render_overview() -> None:
            render_overview_summary(services.get_overview_summary())

        render_overview()

        with ui.tabs().classes("w-full") as tabs:
            with ui.tab("hedefler", label="Hedefler"):
                alert_badge = ui.badge("0", color="negative").props("floating")
                alert_badge.set_visibility(False)
            ui.tab("genel-bakis", label="Genel Bakış")
            ui.tab("olaylar", label="Olay Akışı")

    with ui.tab_panels(tabs, value=initial_tab).classes("w-full"):
        with ui.tab_panel("hedefler"):
            hedefler_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("genel-bakis"):
            genel_bakis_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("olaylar"):
            olaylar_container = ui.column().classes("w-full gap-2")

    containers = {"hedefler": hedefler_container, "genel-bakis": genel_bakis_container, "olaylar": olaylar_container}
    built = {"hedefler": False, "genel-bakis": False, "olaylar": False}
    timers: dict[str, ui.timer] = {}

    def build_genel_bakis() -> None:
        with containers["genel-bakis"]:
            genel_bakis_update_label = ui.label("").classes("text-caption text-grey")

            async def handle_download_report() -> None:
                pdf_button.set_enabled(False)
                pdf_spinner.set_visibility(True)
                try:
                    pdf_bytes = await asyncio.to_thread(reports.generate_monthly_pdf_report)
                    filename = f"arobserver-rapor-{datetime.now().strftime('%Y-%m-%d')}.pdf"
                    ui.download.content(pdf_bytes, filename=filename, media_type="application/pdf")
                except Exception:
                    ui.notify("PDF rapor oluşturulamadı.", type="negative")
                    raise
                finally:
                    pdf_button.set_enabled(True)
                    pdf_spinner.set_visibility(False)

            with ui.row().classes("items-center gap-2"):
                pdf_button = ui.button("PDF Raporu İndir", icon="download", on_click=handle_download_report)
                pdf_spinner = ui.spinner(size="1.5em")
                pdf_spinner.set_visibility(False)

            with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 gap-4"):
                with render_panel("Harf Notu Dağılımı"):
                    @ui.refreshable
                    def render_distribution() -> None:
                        render_grade_distribution(services.get_overview_summary()["grade_distribution"])

                    render_distribution()
                with render_panel("Sıralamalar"):
                    @ui.refreshable
                    def render_rankings_section() -> None:
                        render_rankings(services.get_rankings())

                    render_rankings_section()
                with render_panel("Güvenlik Başlığı Matrisi"):
                    @ui.refreshable
                    def render_header_matrix_section() -> None:
                        render_header_matrix(services.get_header_matrix())

                    render_header_matrix_section()
                with render_panel("Sertifika Takvimi"):
                    @ui.refreshable
                    def render_certificate_calendar_section() -> None:
                        render_certificate_calendar(services.get_certificate_calendar())

                    render_certificate_calendar_section()
                with ui.element("div").classes("md:col-span-2"):
                    with render_panel("Skor Isı Haritası (30 gün)"):
                        @ui.refreshable
                        def render_score_heatmap_section() -> None:
                            render_score_heatmap(services.get_score_heatmap())

                        render_score_heatmap_section()

        def genel_bakis_tick() -> None:
            render_distribution.refresh()
            render_rankings_section.refresh()
            render_header_matrix_section.refresh()
            render_certificate_calendar_section.refresh()
            render_score_heatmap_section.refresh()
            genel_bakis_update_label.set_text(format_last_update())

        timers["genel-bakis"] = ui.timer(POLL_INTERVAL_SECONDS, genel_bakis_tick)

    def build_olaylar() -> None:
        with containers["olaylar"]:
            olaylar_update_label = ui.label("").classes("text-caption text-grey")

            @ui.refreshable
            def render_event_feed_section() -> None:
                render_event_feed(services.get_event_feed())

            with render_panel("Olay Akışı"):
                with ui.scroll_area().classes("w-full h-[70vh]"):
                    render_event_feed_section()

        def olaylar_tick() -> None:
            render_event_feed_section.refresh()
            olaylar_update_label.set_text(format_last_update())

        timers["olaylar"] = ui.timer(POLL_INTERVAL_SECONDS, olaylar_tick)

    def build_hedefler() -> None:
        def open_target_dialog(target: dict | None) -> None:
            is_edit = target is not None

            with ui.dialog() as dialog, ui.card().classes("w-96"):
                ui.label("Hedefi Düzenle" if is_edit else "Yeni Hedef").classes("text-h6")
                name_input = ui.input(label="Ad", value=target["name"] if is_edit else "").classes("w-full")
                url_input = ui.input(label="URL", value=target["url"] if is_edit else "").classes("w-full")
                interval_input = ui.number(
                    label="Kontrol Aralığı (dk)",
                    value=target["interval_minutes"] if is_edit else 5,
                    min=1,
                    precision=0,
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

                with ui.row().classes("w-full gap-2"):
                    maintenance_start_input = ui.input(label="Bakım Penceresi Başlangıcı (isteğe bağlı)").props(
                        "type=datetime-local"
                    ).classes("flex-1")
                    maintenance_end_input = ui.input(label="Bakım Penceresi Bitişi (isteğe bağlı)").props(
                        "type=datetime-local"
                    ).classes("flex-1")
                    if is_edit and target["maintenance_start"]:
                        maintenance_start_input.value = services.to_local(target["maintenance_start"]).strftime(
                            "%Y-%m-%dT%H:%M"
                        )
                    if is_edit and target["maintenance_end"]:
                        maintenance_end_input.value = services.to_local(target["maintenance_end"]).strftime(
                            "%Y-%m-%dT%H:%M"
                        )

                def _parse_maintenance_input(value: str) -> datetime | None:
                    if not value:
                        return None
                    return services.local_naive_to_utc(datetime.strptime(value, "%Y-%m-%dT%H:%M"))

                def save() -> None:
                    maintenance_start = _parse_maintenance_input(maintenance_start_input.value)
                    maintenance_end = _parse_maintenance_input(maintenance_end_input.value)
                    if maintenance_start and maintenance_end and maintenance_start >= maintenance_end:
                        ui.notify("Bakım penceresi başlangıcı bitişten önce olmalı.", type="negative")
                        return
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
                                maintenance_start,
                                maintenance_end,
                            )
                        else:
                            new_id = services.create_target(
                                name_input.value,
                                url_input.value,
                                int(interval_input.value),
                                list(tags_select.value or []),
                                keyword_input.value,
                                int(status_input.value),
                                maintenance_start,
                                maintenance_end,
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

                            ui.button("Sil", on_click=do_delete, color="negative")
                    confirm.open()

                def handle_reset() -> None:
                    services.reset_baseline(target["id"])
                    trigger_manual_check(target["id"])
                    ui.notify("Temel çizgi sıfırlandı, yeni kontrol tetiklendi.", type="info")

                with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
                    if is_edit:
                        ui.button("Yeni Durumu Temel Al", on_click=handle_reset).props("flat")
                        ui.button("Sil", on_click=confirm_delete, color="negative").props("flat")
                    ui.button("Vazgeç", on_click=dialog.close).props("flat")
                    ui.button("Kaydet", on_click=save)

            dialog.open()

        def open_edit_dialog(target_id: int) -> None:
            target = services.get_editable_target(target_id)
            if target is not None:
                open_target_dialog(target)

        def open_create_dialog() -> None:
            open_target_dialog(None)

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

        with containers["hedefler"]:
            with ui.row().classes("items-center gap-4"):
                grade_select = ui.select(
                    GRADE_OPTIONS,
                    value=state["grades"],
                    multiple=True,
                    label="Harf Notu",
                    on_change=lambda e: on_filter_change(),
                ).classes("min-w-[140px]")
                group_select = ui.select(
                    services.list_groups(),
                    value=state["groups"],
                    multiple=True,
                    label="Grup",
                    on_change=lambda e: on_filter_change(),
                ).classes("min-w-[140px]")
                search_input = ui.input(
                    label="Ara (ad/url)", value=state["query"], on_change=lambda e: on_filter_change()
                )
                ui.button("+ Yeni Hedef", on_click=open_create_dialog)

            hedefler_update_label = ui.label("").classes("text-caption text-grey")

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

                with ui.element("div").classes("w-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"):
                    for card in filtered:
                        render_target_card(card, add_group_filter, open_edit_dialog)

            render_cards()

        def hedefler_tick() -> None:
            render_cards.refresh()
            render_overview.refresh()
            open_count = services.get_overview_summary()["open_alerts_count"]
            alert_badge.set_text(str(open_count))
            alert_badge.set_visibility(open_count > 0)
            hedefler_update_label.set_text(format_last_update())

        timers["hedefler"] = ui.timer(POLL_INTERVAL_SECONDS, hedefler_tick)

    BUILDERS = {"hedefler": build_hedefler, "genel-bakis": build_genel_bakis, "olaylar": build_olaylar}

    def activate_tab(name: str) -> None:
        current_tab["value"] = name
        for tab_name, timer in timers.items():
            timer.active = tab_name == name
        if not built[name]:
            built[name] = True
            BUILDERS[name]()
        sync_url()

    tabs.on_value_change(lambda e: activate_tab(e.value))
    activate_tab(initial_tab)


DETAIL_TABS = ("genel-bakis", "kontrol-durumu", "sertifika", "derin-kontrol", "gecmis")


@ui.page("/targets/{target_id}")
async def detail_page(target_id: int, tab: str = "genel-bakis") -> None:
    detail = services.get_target_detail(target_id)
    if detail is None:
        ui.label("Hedef bulunamadı").classes("text-h5")
        return

    initial_tab = tab if tab in DETAIL_TABS else "genel-bakis"
    current_tab = {"value": initial_tab}
    last_check = detail["last_check"]
    last_check_status = grade_to_status(last_check["letter_grade"]) if last_check else None
    cert_days = ((last_check or {}).get("tls_result") or {}).get("days_remaining")
    cert_warning = cert_days is not None and cert_days < 7
    open_alert_count = len(detail["open_alerts"])

    ui.page_title(f"{detail['name']} — ARObserver")

    def sync_url() -> None:
        new_url = f"/targets/{target_id}?tab={current_tab['value']}"
        ui.run_javascript(f"history.replaceState(null, '', {json.dumps(new_url)})")

    with render_page_shell(on_logout=_do_logout, back_link=("/", "Hedefler")):
        ui.label(detail["name"]).classes("text-h4")
        ui.label(f"{detail['url']} — kontrol aralığı: {detail['interval_minutes']} dk").classes(
            "text-caption text-grey"
        )

        last_update_label = ui.label("").classes("text-caption text-grey")
        last_update_label.set_visibility(False)

        with ui.tabs().classes("w-full") as tabs:
            with ui.tab("genel-bakis", label="Genel Bakış"):
                if open_alert_count:
                    ui.badge(str(open_alert_count), color="negative").props("floating")
            ui.tab("kontrol-durumu", label="Kontrol Durumu")
            with ui.tab("sertifika", label="Sertifika"):
                if cert_warning:
                    ui.badge("!", color="negative").props("floating")
            ui.tab("derin-kontrol", label="Derin Kontrol")
            ui.tab("gecmis", label="Geçmiş")

    with ui.tab_panels(tabs, value=initial_tab).classes("w-full"):
        with ui.tab_panel("genel-bakis"):
            genel_bakis_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("kontrol-durumu"):
            kontrol_durumu_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("sertifika"):
            sertifika_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("derin-kontrol"):
            derin_kontrol_container = ui.column().classes("w-full gap-2")
        with ui.tab_panel("gecmis"):
            gecmis_container = ui.column().classes("w-full gap-2")

    containers = {
        "genel-bakis": genel_bakis_container,
        "kontrol-durumu": kontrol_durumu_container,
        "sertifika": sertifika_container,
        "derin-kontrol": derin_kontrol_container,
        "gecmis": gecmis_container,
    }
    built = {name: False for name in DETAIL_TABS}
    refreshables = {}
    chart_state = {
        "points": [],
        "charts": {},
        "charts_built": False,
        "containers": {},
        "window_start": datetime.utcnow() - timedelta(minutes=services.CHART_WINDOW_MINUTES),
    }

    def build_genel_bakis() -> None:
        with containers["genel-bakis"]:
            render_alerts(detail["open_alerts"])

            with render_panel("Kullanılabilirlik"):
                @ui.refreshable
                def render_uptime_section() -> None:
                    render_uptime_summary(services.get_uptime_stats(target_id))
                    render_uptime_timeline(services.get_uptime_timeline(target_id))

                render_uptime_section()
            refreshables["uptime"] = render_uptime_section

            with render_panel("Yanıt Süresi Yüzdelikleri (7 gün)"):
                @ui.refreshable
                def render_percentiles_section() -> None:
                    render_response_time_percentiles(services.get_response_time_percentiles(target_id))

                render_percentiles_section()
            refreshables["percentiles"] = render_percentiles_section

            points = services.get_chart_points(target_id)
            chart_state["points"] = points
            chart_containers: dict[str, ui.column] = {}
            for key, title in (
                ("response_time_ms", "Yanıt Süresi (ms)"),
                ("score", "Skor"),
                ("timing", "Zaman Kırılımı"),
                ("body_size_kb", "Sayfa Boyutu"),
            ):
                with render_panel(title):
                    chart_containers[key] = ui.column().classes("w-full")
            chart_state["containers"] = chart_containers

            window_minutes = services.CHART_WINDOW_MINUTES

            def build_charts() -> None:
                charts = chart_state["charts"]
                pts = chart_state["points"]
                with chart_containers["response_time_ms"]:
                    charts["response_time_ms"] = build_line_chart(pts, "response_time_ms", window_minutes)
                with chart_containers["score"]:
                    charts["score"] = build_line_chart(pts, "score", window_minutes)
                with chart_containers["timing"]:
                    charts["timing"] = build_stacked_bar_chart(pts, window_minutes)
                with chart_containers["body_size_kb"]:
                    charts["body_size_kb"] = build_line_chart(pts, "body_size_kb", window_minutes)
                chart_state["charts_built"] = True

            chart_state["build_charts"] = build_charts

            if points:
                build_charts()
            else:
                for container in chart_containers.values():
                    with container:
                        render_empty_state("Henüz grafik verisi yok.")

            def chart_data_tick() -> None:
                pts = chart_state["points"]
                since = pts[-1]["checked_at"] if pts else chart_state["window_start"]
                new_points = services.get_chart_points(target_id, since=since)
                if not new_points:
                    return

                pts.extend(new_points)
                cutoff = datetime.utcnow() - timedelta(minutes=services.CHART_WINDOW_MINUTES)
                while pts and pts[0]["checked_at"] < cutoff:
                    pts.pop(0)
                if len(pts) > services.MAX_CHART_POINTS:
                    del pts[: len(pts) - services.MAX_CHART_POINTS]

                if not chart_state["charts_built"]:
                    for container in chart_state["containers"].values():
                        container.clear()
                    chart_state["build_charts"]()
                else:
                    charts = chart_state["charts"]
                    update_line_chart(charts["response_time_ms"], pts, "response_time_ms")
                    update_line_chart(charts["score"], pts, "score")
                    update_stacked_bar_chart(charts["timing"], pts)
                    update_line_chart(charts["body_size_kb"], pts, "body_size_kb")
                    flash_last_point(charts["response_time_ms"], "response_time_ms", pts)
                    flash_last_point(charts["score"], "score", pts)
                    flash_last_point(charts["body_size_kb"], "body_size_kb", pts)
                last_update_label.set_text(format_last_update())
                last_update_label.set_visibility(True)

            def axis_shift_tick() -> None:
                if not chart_state["charts_built"]:
                    return
                charts = chart_state["charts"]
                shift_time_axis(charts["response_time_ms"], window_minutes)
                shift_time_axis(charts["score"], window_minutes)
                shift_time_axis(charts["timing"], window_minutes)
                shift_time_axis(charts["body_size_kb"], window_minutes)

            chart_state["axis_timer"] = ui.timer(1.0, axis_shift_tick)
            chart_state["chart_timer"] = ui.timer(10.0, chart_data_tick)

    def build_kontrol_durumu() -> None:
        with containers["kontrol-durumu"]:
            with render_panel("Son Kontrol Durumu", status=last_check_status):
                render_status_table(last_check)

            with render_panel("Skor Kırılımı", status=last_check_status):
                check_history = services.get_check_history(target_id)
                default_check_id = last_check["id"] if last_check else None

                if check_history:
                    check_selector = ui.select(
                        {entry["id"]: entry["label"] for entry in check_history},
                        value=default_check_id,
                        label="Kontrol Seç",
                    ).classes("min-w-[320px]")

                @ui.refreshable
                def render_breakdown_section() -> None:
                    selected_id = check_selector.value if check_history else default_check_id
                    selected_check = services.get_check_by_id(selected_id) if selected_id else None
                    previous_check = services.get_previous_check(target_id, selected_id) if selected_id else None
                    render_score_breakdown(selected_check, previous_check)

                render_breakdown_section()
                if check_history:
                    check_selector.on_value_change(lambda e: render_breakdown_section.refresh())

            def handle_reset_baseline() -> None:
                services.reset_baseline(target_id)
                trigger_manual_check(target_id)
                ui.notify("Temel çizgi sıfırlandı, yeni kontrol tetiklendi.", type="info")

            with render_panel("İçerik Bütünlüğü"):
                render_content_section(
                    last_check["content_result"] if last_check else None, handle_reset_baseline
                )

    def build_sertifika() -> None:
        with containers["sertifika"]:
            with render_panel("TLS", status=last_check_status):
                render_tls_status(last_check)

            with render_panel("Sertifika Zinciri"):
                render_certificate_chain(((last_check or {}).get("tls_result") or {}).get("chain") or [])

            if settings.ct_log_check_enabled:
                with render_panel("Certificate Transparency (deneysel)"):
                    render_ct_log_result(detail["ct_log_result"], detail["ct_log_checked_at"])

    async def build_derin_kontrol() -> None:
        with containers["derin-kontrol"]:
            deep_available, deep_unavailable_reason = await services.check_deep_check_service_available()
            deep_running_initial = services.is_deep_check_running(target_id)

            with render_panel("Derin Kontrol"):
                with ui.row().classes("items-center gap-2"):
                    deep_check_button = ui.button("Derin Kontrol")
                    deep_spinner = ui.spinner(size="1.5em")
                    deep_spinner.set_visibility(deep_running_initial)
                deep_check_button.set_enabled(deep_available and not deep_running_initial)
                if not deep_available:
                    ui.label(deep_unavailable_reason or "Derin kontrol servisi şu anda erişilemiyor.").classes(
                        "text-caption text-orange"
                    )

                @ui.refreshable
                def render_deep_check_section() -> None:
                    render_deep_check_result(services.get_deep_check_result(target_id))

                render_deep_check_section()

            deep_was_running = {"value": deep_running_initial}

            def handle_deep_check() -> None:
                result = services.trigger_deep_check(target_id)
                if result == "running":
                    ui.notify("Derin kontrol zaten çalışıyor.", type="info")
                    return
                deep_was_running["value"] = True
                deep_check_button.set_enabled(False)
                deep_spinner.set_visibility(True)
                ui.notify("Derin kontrol başlatıldı, 10-30 sn sürebilir.", type="info")

            deep_check_button.on_click(handle_deep_check)

            def deep_check_tick() -> None:
                running = services.is_deep_check_running(target_id)
                if running:
                    deep_was_running["value"] = True
                    return
                if deep_was_running["value"]:
                    deep_was_running["value"] = False
                    deep_spinner.set_visibility(False)
                    deep_check_button.set_enabled(deep_available)
                    render_deep_check_section.refresh()
                    ui.notify("Derin kontrol tamamlandı.", type="positive")

            ui.timer(2.0, deep_check_tick)

    def build_gecmis() -> None:
        with containers["gecmis"]:
            with render_panel("Kesinti Geçmişi"):
                @ui.refreshable
                def render_downtime_section() -> None:
                    render_downtime_incidents(services.get_downtime_incidents(target_id))

                render_downtime_section()
            refreshables["downtime"] = render_downtime_section

    BUILDERS = {
        "genel-bakis": build_genel_bakis,
        "kontrol-durumu": build_kontrol_durumu,
        "sertifika": build_sertifika,
        "derin-kontrol": build_derin_kontrol,
        "gecmis": build_gecmis,
    }

    def activate_tab(name: str) -> None:
        current_tab["value"] = name
        if not built[name]:
            built[name] = True
            result = BUILDERS[name]()
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        if "axis_timer" in chart_state:
            is_active = name == "genel-bakis"
            chart_state["axis_timer"].active = is_active
            chart_state["chart_timer"].active = is_active
        sync_url()

    tabs.on_value_change(lambda e: activate_tab(e.value))
    activate_tab(initial_tab)

    def tick() -> None:
        if built["gecmis"]:
            refreshables["downtime"].refresh()
        if built["genel-bakis"]:
            refreshables["uptime"].refresh()
            refreshables["percentiles"].refresh()

    ui.timer(POLL_INTERVAL_SECONDS, tick)
