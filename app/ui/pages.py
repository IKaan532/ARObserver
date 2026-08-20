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
    COLOR_TOKENS,
    TOKEN_CSS,
    UPTIME_GAUGE_MAX,
    UPTIME_GAUGE_MIN,
    UPTIME_GAUGE_STOPS,
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
    render_domain_expiry_calendar,
    render_downtime_incidents,
    grade_to_status,
    render_empty_state,
    render_event_feed,
    render_fleet_status,
    render_gauge,
    render_grade_distribution,
    render_header_matrix,
    render_overview_summary,
    render_page_shell,
    render_panel,
    render_rankings,
    render_reputation_result,
    render_response_time_percentiles,
    render_score_breakdown,
    render_score_heatmap,
    render_sidebar_target_row,
    render_status_chip,
    render_status_table,
    render_tls_status,
    render_uptime_summary,
    render_uptime_timeline,
    uptime_pct_to_status,
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


@ui.page("/")
def index_page(grade: str = "", group: str = "", q: str = "") -> None:
    ui.page_title("ARObserver — Hedefler")

    state = {
        "grades": [value for value in grade.split(",") if value],
        "groups": [value for value in group.split(",") if value],
        "query": q,
    }
    selected_target_id: dict[str, int | None] = {"value": None}

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

    with render_page_shell(on_logout=_do_logout):
        pass

    right_pane_timer: dict[str, ui.timer | None] = {"value": None}
    deep_check_timer_ref: dict[str, ui.timer | None] = {"value": None}
    sidebar_refs = {"refresh": None}

    with ui.row().classes("w-full items-start gap-4 flex-col md:flex-row"):
        sidebar_column = ui.column().classes("w-full md:w-72 shrink-0 gap-2")
        right_pane = ui.column().classes("flex-1 gap-4 min-w-0")

    def build_panel_view() -> None:
        with right_pane:
            panel_update_label = ui.label("").classes("text-caption text-grey")

            @ui.refreshable
            def render_overview() -> None:
                render_overview_summary(services.get_overview_summary())

            render_overview()

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
                with render_panel("Alan Adı Takvimi"):
                    @ui.refreshable
                    def render_domain_expiry_calendar_section() -> None:
                        render_domain_expiry_calendar(services.get_domain_expiry_calendar())

                    render_domain_expiry_calendar_section()
                with render_panel("Durum"):
                    @ui.refreshable
                    def render_fleet_status_section() -> None:
                        render_fleet_status(services.get_fleet_status())

                    render_fleet_status_section()
                with ui.element("div").classes("md:col-span-2"):
                    with render_panel("Skor Isı Haritası (30 gün)"):
                        @ui.refreshable
                        def render_score_heatmap_section() -> None:
                            render_score_heatmap(services.get_score_heatmap())

                        render_score_heatmap_section()

            @ui.refreshable
            def render_event_feed_section() -> None:
                render_event_feed(services.get_event_feed())

            with render_panel("Olay Akışı"):
                with ui.scroll_area().classes("w-full h-96"):
                    render_event_feed_section()

            def panel_tick() -> None:
                render_overview.refresh()
                render_distribution.refresh()
                render_rankings_section.refresh()
                render_header_matrix_section.refresh()
                render_certificate_calendar_section.refresh()
                render_domain_expiry_calendar_section.refresh()
                render_fleet_status_section.refresh()
                render_score_heatmap_section.refresh()
                render_event_feed_section.refresh()
                panel_update_label.set_text(format_last_update())

            right_pane_timer["value"] = ui.timer(POLL_INTERVAL_SECONDS, panel_tick)

    def build_quick_view(target_id: int) -> None:
        with right_pane:
            ui.button("Panel'e Dön", icon="arrow_back", on_click=show_panel).props("flat dense")
            quick_view_update_label = ui.label("").classes("text-caption text-grey")

            @ui.refreshable
            def render_quick_view() -> None:
                detail = services.get_target_detail(target_id)
                if detail is None:
                    render_empty_state("Hedef bulunamadı.")
                    return
                last_check = detail["last_check"]

                ui.label(detail["name"]).classes("text-h5")
                ui.label(detail["url"]).classes("text-caption").style(f"color: {COLOR_TOKENS['text_muted']}")

                if last_check is None:
                    render_empty_state("Henüz kontrol verisi yok.")
                else:
                    if last_check["network_issue"]:
                        status_text, status = "Ağ sorunu (test edilemedi)", "neutral"
                    elif last_check["status_code"]:
                        status_text, status = f"HTTP {last_check['status_code']}", "good"
                    else:
                        status_text, status = "Erişilemiyor", "bad"
                    render_status_chip(status, status_text)

                uptime_stats = services.get_uptime_stats(target_id)
                cert_days = (last_check["tls_result"] or {}).get("days_remaining") if last_check else None
                response_ms = last_check["response_time_ms"] if last_check else None

                with ui.row().classes("items-end gap-6 q-mt-sm"):
                    with ui.column().classes("items-start gap-0"):
                        ui.label("Yanıt Süresi").style(
                            f"font-size: 0.7rem; color: {COLOR_TOKENS['text_muted']}; text-transform: uppercase; "
                            "letter-spacing: 0.04em"
                        )
                        ui.label(f"{response_ms} ms" if response_ms is not None else "-").classes("ar-mono").style(
                            f"font-size: 1.5rem; font-weight: 600; color: {COLOR_TOKENS['text_primary']}"
                        )
                    for label, key in (("Uptime 7g", "uptime_7d"), ("Uptime 30g", "uptime_30d")):
                        pct = uptime_stats.get(key)
                        render_gauge(
                            value=pct,
                            min_value=UPTIME_GAUGE_MIN,
                            max_value=UPTIME_GAUGE_MAX,
                            color_stops=UPTIME_GAUGE_STOPS,
                            status=uptime_pct_to_status(pct),
                            center_text=f"{pct}%" if pct is not None else "-",
                            center_subtext=label,
                            height="110px",
                        )
                    with ui.column().classes("items-start gap-0"):
                        ui.label("Sertifika (kalan gün)").style(
                            f"font-size: 0.7rem; color: {COLOR_TOKENS['text_muted']}; text-transform: uppercase; "
                            "letter-spacing: 0.04em"
                        )
                        ui.label(str(cert_days) if cert_days is not None else "-").classes("ar-mono").style(
                            f"font-size: 1.5rem; font-weight: 600; color: {COLOR_TOKENS['text_primary']}"
                        )

                with render_panel("Yanıt Süresi"):
                    points = services.get_chart_points(target_id)
                    if points:
                        build_line_chart(points, "response_time_ms", services.CHART_WINDOW_MINUTES)
                    else:
                        render_empty_state("Henüz grafik verisi yok.")

            render_quick_view()

            def quick_view_tick() -> None:
                render_quick_view.refresh()
                quick_view_update_label.set_text(format_last_update())

            right_pane_timer["value"] = ui.timer(POLL_INTERVAL_SECONDS, quick_view_tick)

            detail_expansion = ui.expansion("Tüm Detaylar", icon="expand_more").classes("w-full ar-panel")
            detail_built = {"value": False}

            def build_detail_expansion() -> None:
                detail = services.get_target_detail(target_id)
                last_check = detail["last_check"] if detail else None
                last_check_status = grade_to_status(last_check["letter_grade"]) if last_check else None

                with detail_expansion:
                    with ui.tabs().classes("w-full") as inline_tabs:
                        ui.tab("kontrol-durumu", label="Kontrol Durumu")
                        ui.tab("sertifika", label="Sertifika")
                        ui.tab("derin-kontrol", label="Derin Kontrol")
                        ui.tab("gecmis", label="Geçmiş")

                    with ui.tab_panels(inline_tabs, value="kontrol-durumu").classes("w-full"):
                        with ui.tab_panel("kontrol-durumu"):
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
                                    ).classes("min-w-[280px]")

                                @ui.refreshable
                                def render_inline_breakdown() -> None:
                                    selected_id = check_selector.value if check_history else default_check_id
                                    selected_check = services.get_check_by_id(selected_id) if selected_id else None
                                    previous_check = (
                                        services.get_previous_check(target_id, selected_id) if selected_id else None
                                    )
                                    render_score_breakdown(selected_check, previous_check)

                                render_inline_breakdown()
                                if check_history:
                                    check_selector.on_value_change(lambda e: render_inline_breakdown.refresh())

                            def handle_reset_baseline() -> None:
                                services.reset_baseline(target_id)
                                trigger_manual_check(target_id)
                                ui.notify("Temel çizgi sıfırlandı, yeni kontrol tetiklendi.", type="info")

                            with render_panel("İçerik Bütünlüğü"):
                                render_content_section(
                                    last_check["content_result"] if last_check else None, handle_reset_baseline
                                )

                            with render_panel("İtibar Kontrolü"):
                                render_reputation_result(detail["reputation_result"], detail["reputation_checked_at"])

                        with ui.tab_panel("sertifika"):
                            with render_panel("TLS", status=last_check_status):
                                render_tls_status(last_check)

                            with render_panel("Sertifika Zinciri"):
                                render_certificate_chain(((last_check or {}).get("tls_result") or {}).get("chain") or [])

                            if settings.ct_log_check_enabled:
                                with render_panel("Certificate Transparency (deneysel)"):
                                    render_ct_log_result(detail["ct_log_result"], detail["ct_log_checked_at"])

                        with ui.tab_panel("derin-kontrol"):
                            derin_kontrol_container = ui.column().classes("w-full gap-2")

                            async def build_deep_check_panel() -> None:
                                deep_available, deep_unavailable_reason = await services.check_deep_check_service_available()
                                deep_running_initial = services.is_deep_check_running(target_id)
                                with derin_kontrol_container:
                                    with render_panel("Derin Kontrol"):
                                        with ui.row().classes("items-center gap-2"):
                                            deep_check_button = ui.button("Derin Kontrol")
                                            deep_spinner = ui.spinner(size="1.5em")
                                            deep_spinner.set_visibility(deep_running_initial)
                                        deep_check_button.set_enabled(deep_available and not deep_running_initial)
                                        if not deep_available:
                                            ui.label(
                                                deep_unavailable_reason or "Derin kontrol servisi şu anda erişilemiyor."
                                            ).classes("text-caption text-orange")

                                        @ui.refreshable
                                        def render_inline_deep_check() -> None:
                                            render_deep_check_result(services.get_deep_check_result(target_id))

                                        render_inline_deep_check()

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
                                            render_inline_deep_check.refresh()
                                            ui.notify("Derin kontrol tamamlandı.", type="positive")

                                    deep_check_timer_ref["value"] = ui.timer(2.0, deep_check_tick)

                            asyncio.ensure_future(build_deep_check_panel())

                        with ui.tab_panel("gecmis"):
                            with render_panel("Kesinti Geçmişi"):
                                render_downtime_incidents(services.get_downtime_incidents(target_id))

            def on_detail_expansion_toggle(e) -> None:
                if e.value and not detail_built["value"]:
                    detail_built["value"] = True
                    build_detail_expansion()

            detail_expansion.on_value_change(on_detail_expansion_toggle)

    def show_panel() -> None:
        if right_pane_timer["value"] is not None:
            right_pane_timer["value"].deactivate()
            right_pane_timer["value"] = None
        if deep_check_timer_ref["value"] is not None:
            deep_check_timer_ref["value"].deactivate()
            deep_check_timer_ref["value"] = None
        selected_target_id["value"] = None
        right_pane.clear()
        build_panel_view()
        if sidebar_refs["refresh"] is not None:
            sidebar_refs["refresh"]()

    def show_quick_view(target_id: int) -> None:
        if right_pane_timer["value"] is not None:
            right_pane_timer["value"].deactivate()
            right_pane_timer["value"] = None
        if deep_check_timer_ref["value"] is not None:
            deep_check_timer_ref["value"].deactivate()
            deep_check_timer_ref["value"] = None
        selected_target_id["value"] = target_id
        right_pane.clear()
        build_quick_view(target_id)
        if sidebar_refs["refresh"] is not None:
            sidebar_refs["refresh"]()

    def build_sidebar() -> None:
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
                    render_sidebar_rows.refresh()
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
                                render_sidebar_rows.refresh()
                                if selected_target_id["value"] == target["id"]:
                                    show_panel()
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
            render_sidebar_rows.refresh()

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

        with sidebar_column:
            with ui.column().classes("w-full gap-2"):
                ui.button("+ Yeni Hedef", on_click=open_create_dialog).classes("w-full")
                search_input = ui.input(
                    label="Ara (ad/url)", value=state["query"], on_change=lambda e: on_filter_change()
                ).classes("w-full")
                with ui.row().classes("w-full gap-2"):
                    grade_select = ui.select(
                        GRADE_OPTIONS,
                        value=state["grades"],
                        multiple=True,
                        label="Harf Notu",
                        on_change=lambda e: on_filter_change(),
                    ).classes("flex-1 min-w-0")
                    group_select = ui.select(
                        services.list_groups(),
                        value=state["groups"],
                        multiple=True,
                        label="Grup",
                        on_change=lambda e: on_filter_change(),
                    ).classes("flex-1 min-w-0")

            sidebar_update_label = ui.label("").classes("text-caption text-grey")

            @ui.refreshable
            def render_sidebar_rows() -> None:
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

                heartbeats = services.get_target_heartbeats()
                with ui.column().classes("w-full gap-1"):
                    for card in filtered:
                        render_sidebar_target_row(
                            card,
                            heartbeats.get(card["id"], []),
                            selected_target_id["value"] == card["id"],
                            show_quick_view,
                            open_edit_dialog,
                            add_group_filter,
                        )

            render_sidebar_rows()
            sidebar_refs["refresh"] = render_sidebar_rows.refresh

        def sidebar_tick() -> None:
            render_sidebar_rows.refresh()
            sidebar_update_label.set_text(format_last_update())

        ui.timer(POLL_INTERVAL_SECONDS, sidebar_tick)

    build_sidebar()
    show_panel()


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

            with render_panel("İtibar Kontrolü"):
                render_reputation_result(detail["reputation_result"], detail["reputation_checked_at"])

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
