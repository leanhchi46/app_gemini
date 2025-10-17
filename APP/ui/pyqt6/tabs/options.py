"""Tab Options PyQt6 hiển thị cấu hình chi tiết."""

from __future__ import annotations

import json

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from APP.ui.state import UiConfigState


def _json_dumps(data: Any) -> str:
    if not data:
        return ""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _parse_keywords(text: str) -> list[str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or None
    result = [item.strip() for item in stripped.split(",") if item.strip()]
    return result or None


def _parse_mapping(text: str) -> dict[str, list[str]] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = None
    result: dict[str, list[str]] = {}
    if isinstance(value, dict):
        for key, items in value.items():
            if isinstance(items, list):
                values = [str(item).strip() for item in items if str(item).strip()]
                if values:
                    result[str(key)] = values
            elif isinstance(items, str) and items.strip():
                result[str(key)] = [items.strip()]
        return result or None
    for line in stripped.splitlines():
        if ":" not in line:
            continue
        key, raw_values = line.split(":", 1)
        entries = [item.strip() for item in raw_values.split(",") if item.strip()]
        if entries:
            result[key.strip()] = entries
    return result or None


def _parse_killzone(text: str) -> dict[str, dict[str, str]] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        value = None
    result: dict[str, dict[str, str]] = {}
    if isinstance(value, dict):
        for key, slots in value.items():
            if isinstance(slots, dict):
                start = str(slots.get("start", "")).strip()
                end = str(slots.get("end", "")).strip()
                result[str(key)] = {"start": start, "end": end}
        return result or None
    for line in stripped.splitlines():
        if ":" not in line or "-" not in line:
            continue
        name, time_range = line.split(":", 1)
        start, end = time_range.split("-", 1)
        result[name.strip()] = {"start": start.strip(), "end": end.strip()}
    return result or None


class OptionsTabWidget(QWidget):
    """Thay thế tab Options trong phiên bản Tkinter."""

    config_changed = pyqtSignal(dict)
    load_env_requested = pyqtSignal()
    save_safe_requested = pyqtSignal()
    delete_safe_requested = pyqtSignal()

    def __init__(self, state: UiConfigState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state

        self._tabs = QTabWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._tabs)

        self._build_api_tab()
        self._build_general_tab()
        self._build_context_tab()
        self._build_conditions_tab()
        self._build_autotrade_tab()
        self._build_services_tab()

        self.reset_from_state(state)

    # ------------------------------------------------------------------
    def _register_change(self, widget: QWidget, signal_name: str = "textChanged") -> None:
        signal = getattr(widget, signal_name, None)
        if callable(signal):
            signal.connect(lambda *_: self._emit_changes())

    def _emit_changes(self) -> None:
        self.config_changed.emit(self.collect_payload())

    # ------------------------------------------------------------------
    def _build_api_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        api_group = QGroupBox("API Keys")
        api_form = QFormLayout(api_group)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._register_change(self.api_key_edit)
        toggle_api = QCheckBox("Hiện khoá")

        def _toggle_api(state: int) -> None:
            mode = QLineEdit.EchoMode.Normal if state == Qt.CheckState.Checked.value else QLineEdit.EchoMode.Password
            self.api_key_edit.setEchoMode(mode)

        toggle_api.stateChanged.connect(_toggle_api)
        api_row = QHBoxLayout()
        api_row.addWidget(self.api_key_edit)
        api_row.addWidget(toggle_api)
        api_form.addRow("Google AI:", api_row)

        self.fmp_enabled = QCheckBox("Bật FMP")
        self._register_change(self.fmp_enabled, "stateChanged")
        self.fmp_key_edit = QLineEdit()
        self.fmp_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._register_change(self.fmp_key_edit)
        fmp_row = QHBoxLayout()
        fmp_row.addWidget(self.fmp_enabled)
        fmp_row.addWidget(self.fmp_key_edit)
        api_form.addRow("FMP:", fmp_row)

        self.te_enabled = QCheckBox("Bật TradingEconomics")
        self._register_change(self.te_enabled, "stateChanged")
        self.te_key_edit = QLineEdit()
        self.te_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._register_change(self.te_key_edit)
        self.te_skip_ssl = QCheckBox("Bỏ qua kiểm tra SSL (không khuyến khích)")
        self._register_change(self.te_skip_ssl, "stateChanged")
        te_row = QVBoxLayout()
        te_row.addWidget(self.te_enabled)
        te_row.addWidget(self.te_key_edit)
        te_row.addWidget(self.te_skip_ssl)
        api_form.addRow("TradingEconomics:", te_row)

        actions_row = QHBoxLayout()
        self.env_button = QPushButton("Tải từ .env")
        self.env_button.clicked.connect(self.load_env_requested.emit)
        self.save_safe_button = QPushButton("Lưu an toàn")
        self.save_safe_button.clicked.connect(self.save_safe_requested.emit)
        self.delete_safe_button = QPushButton("Xoá đã lưu")
        self.delete_safe_button.clicked.connect(self.delete_safe_requested.emit)
        actions_row.addWidget(self.env_button)
        actions_row.addWidget(self.save_safe_button)
        actions_row.addWidget(self.delete_safe_button)
        api_form.addRow("Thao tác:", actions_row)

        layout.addWidget(api_group)
        layout.addStretch(1)
        self._tabs.addTab(tab, "API Keys")

    # ------------------------------------------------------------------
    def _build_general_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        folder_group = QGroupBox("Thư mục & Lưu trữ")
        folder_form = QFormLayout(folder_group)
        self.delete_after_checkbox = QCheckBox("Tự xoá sau khi xử lý")
        self._register_change(self.delete_after_checkbox, "stateChanged")
        self.max_files_spin = QSpinBox()
        self.max_files_spin.setRange(1, 1000)
        self._register_change(self.max_files_spin, "valueChanged")
        self.only_changed_checkbox = QCheckBox("Chỉ tạo lại khi có thay đổi")
        self._register_change(self.only_changed_checkbox, "stateChanged")
        self.max_md_reports_spin = QSpinBox()
        self.max_md_reports_spin.setRange(0, 2000)
        self._register_change(self.max_md_reports_spin, "valueChanged")
        folder_form.addRow("Xoá tự động:", self.delete_after_checkbox)
        folder_form.addRow("Số tệp tối đa:", self.max_files_spin)
        folder_form.addRow("Chế độ tiết kiệm:", self.only_changed_checkbox)
        folder_form.addRow("Báo cáo Markdown tối đa:", self.max_md_reports_spin)

        upload_group = QGroupBox("Tải lên & bộ nhớ đệm")
        upload_form = QFormLayout(upload_group)
        self.upload_workers_spin = QSpinBox()
        self.upload_workers_spin.setRange(1, 16)
        self._register_change(self.upload_workers_spin, "valueChanged")
        self.cache_enabled_checkbox = QCheckBox("Bật cache")
        self._register_change(self.cache_enabled_checkbox, "stateChanged")
        self.optimize_lossless_checkbox = QCheckBox("Nén lossless")
        self._register_change(self.optimize_lossless_checkbox, "stateChanged")
        upload_form.addRow("Số worker:", self.upload_workers_spin)
        upload_form.addRow("Cache:", self.cache_enabled_checkbox)
        upload_form.addRow("Lossless:", self.optimize_lossless_checkbox)

        image_group = QGroupBox("Xử lý hình ảnh")
        image_form = QFormLayout(image_group)
        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(200, 4000)
        self._register_change(self.max_width_spin, "valueChanged")
        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(10, 100)
        self._register_change(self.jpeg_quality_spin, "valueChanged")
        image_form.addRow("Chiều rộng tối đa:", self.max_width_spin)
        image_form.addRow("Chất lượng JPEG:", self.jpeg_quality_spin)

        api_group = QGroupBox("API chung")
        api_form = QFormLayout(api_group)
        self.api_tries_spin = QSpinBox()
        self.api_tries_spin.setRange(1, 20)
        self._register_change(self.api_tries_spin, "valueChanged")
        self.api_delay_spin = QDoubleSpinBox()
        self.api_delay_spin.setRange(0.0, 30.0)
        self.api_delay_spin.setDecimals(2)
        self._register_change(self.api_delay_spin, "valueChanged")
        api_form.addRow("Số lần thử:", self.api_tries_spin)
        api_form.addRow("Độ trễ (s):", self.api_delay_spin)

        layout.addWidget(folder_group)
        layout.addWidget(upload_group)
        layout.addWidget(image_group)
        layout.addWidget(api_group)
        layout.addStretch(1)
        self._tabs.addTab(tab, "General")

    # ------------------------------------------------------------------
    def _build_context_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        context_group = QGroupBox("Ghi nhớ ngữ cảnh")
        form = QFormLayout(context_group)

        self.remember_context_checkbox = QCheckBox("Ghi nhớ ngữ cảnh các phiên trước")
        self._register_change(self.remember_context_checkbox, "stateChanged")
        self.n_reports_spin = QSpinBox()
        self.n_reports_spin.setRange(0, 20)
        self._register_change(self.n_reports_spin, "valueChanged")
        self.ctx_limit_spin = QSpinBox()
        self.ctx_limit_spin.setRange(0, 20000)
        self._register_change(self.ctx_limit_spin, "valueChanged")
        self.create_ctx_checkbox = QCheckBox("Sinh file ctx_*.json")
        self._register_change(self.create_ctx_checkbox, "stateChanged")
        self.prefer_ctx_checkbox = QCheckBox("Ưu tiên đọc ctx_*.json")
        self._register_change(self.prefer_ctx_checkbox, "stateChanged")
        self.ctx_json_spin = QSpinBox()
        self.ctx_json_spin.setRange(0, 20)
        self._register_change(self.ctx_json_spin, "valueChanged")

        form.addRow(self.remember_context_checkbox)
        form.addRow("Số báo cáo ghi nhớ:", self.n_reports_spin)
        form.addRow("Giới hạn ký tự:", self.ctx_limit_spin)
        form.addRow(self.create_ctx_checkbox)
        form.addRow(self.prefer_ctx_checkbox)
        form.addRow("Số file ctx JSON:", self.ctx_json_spin)

        layout.addWidget(context_group)
        layout.addStretch(1)
        self._tabs.addTab(tab, "Context")

    # ------------------------------------------------------------------
    def _build_conditions_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        norun_group = QGroupBox("Quy tắc No-Run")
        norun_form = QFormLayout(norun_group)
        self.weekend_checkbox = QCheckBox("Khoá cuối tuần")
        self._register_change(self.weekend_checkbox, "stateChanged")
        self.killzone_checkbox = QCheckBox("Bật kill zone")
        self._register_change(self.killzone_checkbox, "stateChanged")
        self.holiday_checkbox = QCheckBox("Kiểm tra ngày lễ")
        self._register_change(self.holiday_checkbox, "stateChanged")
        self.holiday_country_edit = QLineEdit()
        self._register_change(self.holiday_country_edit)
        self.timezone_edit = QLineEdit()
        self._register_change(self.timezone_edit)
        self.killzone_summer_edit = QPlainTextEdit()
        self.killzone_winter_edit = QPlainTextEdit()
        for editor in (self.killzone_summer_edit, self.killzone_winter_edit):
            editor.setPlaceholderText("JSON hoặc định dạng Session: HH:MM-HH:MM")
            editor.setMaximumHeight(80)
            self._register_change(editor)
        norun_form.addRow(self.weekend_checkbox)
        norun_form.addRow(self.killzone_checkbox)
        norun_form.addRow(self.holiday_checkbox)
        norun_form.addRow("Quốc gia nghỉ lễ:", self.holiday_country_edit)
        norun_form.addRow("Múi giờ:", self.timezone_edit)
        norun_form.addRow("Kill zone mùa hè:", self.killzone_summer_edit)
        norun_form.addRow("Kill zone mùa đông:", self.killzone_winter_edit)

        notrade_group = QGroupBox("Quy tắc No-Trade")
        notrade_form = QFormLayout(notrade_group)
        self.notrade_enabled = QCheckBox("Kích hoạt No-Trade")
        self._register_change(self.notrade_enabled, "stateChanged")
        self.spread_spin = QDoubleSpinBox()
        self.spread_spin.setRange(0.0, 20.0)
        self.spread_spin.setDecimals(2)
        self._register_change(self.spread_spin, "valueChanged")
        self.atr_spin = QDoubleSpinBox()
        self.atr_spin.setRange(0.0, 20.0)
        self.atr_spin.setDecimals(2)
        self._register_change(self.atr_spin, "valueChanged")
        self.min_dist_spin = QDoubleSpinBox()
        self.min_dist_spin.setRange(0.0, 50.0)
        self.min_dist_spin.setDecimals(2)
        self._register_change(self.min_dist_spin, "valueChanged")
        self.session_asia = QCheckBox("Cho phép phiên Á")
        self.session_london = QCheckBox("Cho phép phiên London")
        self.session_ny = QCheckBox("Cho phép phiên New York")
        for box in (self.session_asia, self.session_london, self.session_ny):
            self._register_change(box, "stateChanged")
        notrade_form.addRow(self.notrade_enabled)
        notrade_form.addRow("Spread tối đa (pips):", self.spread_spin)
        notrade_form.addRow("ATR M5 tối thiểu (pips):", self.atr_spin)
        notrade_form.addRow("Khoảng cách key level (pips):", self.min_dist_spin)
        notrade_form.addRow(self.session_asia)
        notrade_form.addRow(self.session_london)
        notrade_form.addRow(self.session_ny)

        news_group = QGroupBox("Tin tức & cảnh báo")
        news_form = QFormLayout(news_group)
        self.news_block_enabled = QCheckBox("Chặn giao dịch khi có tin quan trọng")
        self._register_change(self.news_block_enabled, "stateChanged")
        self.news_before_spin = QSpinBox()
        self.news_before_spin.setRange(0, 240)
        self._register_change(self.news_before_spin, "valueChanged")
        self.news_after_spin = QSpinBox()
        self.news_after_spin.setRange(0, 240)
        self._register_change(self.news_after_spin, "valueChanged")
        self.news_cache_spin = QSpinBox()
        self.news_cache_spin.setRange(30, 7200)
        self._register_change(self.news_cache_spin, "valueChanged")
        self.news_keywords_edit = QLineEdit()
        self._register_change(self.news_keywords_edit)
        self.news_surprise_spin = QDoubleSpinBox()
        self.news_surprise_spin.setRange(0.0, 10.0)
        self.news_surprise_spin.setDecimals(2)
        self._register_change(self.news_surprise_spin, "valueChanged")
        self.news_error_threshold_spin = QSpinBox()
        self.news_error_threshold_spin.setRange(1, 20)
        self._register_change(self.news_error_threshold_spin, "valueChanged")
        self.news_backoff_spin = QSpinBox()
        self.news_backoff_spin.setRange(30, 3600)
        self._register_change(self.news_backoff_spin, "valueChanged")
        self.news_currency_overrides = QPlainTextEdit()
        self.news_currency_overrides.setPlaceholderText("JSON hoặc Country:USD,GBP")
        self.news_symbol_overrides = QPlainTextEdit()
        self.news_symbol_overrides.setPlaceholderText("JSON hoặc Symbol:US,UK")
        for editor in (self.news_currency_overrides, self.news_symbol_overrides):
            editor.setMaximumHeight(80)
            self._register_change(editor)
        news_form.addRow(self.news_block_enabled)
        news_form.addRow("Khoảng chặn trước (phút):", self.news_before_spin)
        news_form.addRow("Khoảng chặn sau (phút):", self.news_after_spin)
        news_form.addRow("TTL cache (giây):", self.news_cache_spin)
        news_form.addRow("Từ khoá ưu tiên:", self.news_keywords_edit)
        news_form.addRow("Ngưỡng surprise:", self.news_surprise_spin)
        news_form.addRow("Ngưỡng lỗi nhà cung cấp:", self.news_error_threshold_spin)
        news_form.addRow("Thời gian backoff (giây):", self.news_backoff_spin)
        news_form.addRow("Override tiền tệ:", self.news_currency_overrides)
        news_form.addRow("Override symbol:", self.news_symbol_overrides)

        layout.addWidget(norun_group)
        layout.addWidget(notrade_group)
        layout.addWidget(news_group)
        layout.addStretch(1)
        self._tabs.addTab(tab, "Conditions")

    # ------------------------------------------------------------------
    def _build_autotrade_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        core_group = QGroupBox("Thiết lập cơ bản")
        core_form = QFormLayout(core_group)
        self.autotrade_enabled = QCheckBox("Bật auto trade")
        self._register_change(self.autotrade_enabled, "stateChanged")
        self.strict_bias_checkbox = QCheckBox("Tuân thủ bias nghiêm ngặt")
        self._register_change(self.strict_bias_checkbox, "stateChanged")
        self.size_mode_combo = QComboBox()
        self.size_mode_combo.addItems(["risk_percent", "fixed_lot"])
        self._register_change(self.size_mode_combo, "currentTextChanged")
        self.risk_spin = QDoubleSpinBox()
        self.risk_spin.setRange(0.0, 100.0)
        self.risk_spin.setDecimals(2)
        self._register_change(self.risk_spin, "valueChanged")
        self.split_enabled = QCheckBox("Chia TP")
        self._register_change(self.split_enabled, "stateChanged")
        self.split_ratio_spin = QSpinBox()
        self.split_ratio_spin.setRange(0, 100)
        self._register_change(self.split_ratio_spin, "valueChanged")
        core_form.addRow(self.autotrade_enabled)
        core_form.addRow(self.strict_bias_checkbox)
        core_form.addRow("Chế độ khối lượng:", self.size_mode_combo)
        core_form.addRow("Rủi ro mỗi lệnh (%):", self.risk_spin)
        core_form.addRow(self.split_enabled)
        core_form.addRow("Tỷ lệ TP1 (%):", self.split_ratio_spin)

        order_group = QGroupBox("Thông số lệnh")
        order_form = QFormLayout(order_group)
        self.deviation_spin = QSpinBox()
        self.deviation_spin.setRange(0, 500)
        self._register_change(self.deviation_spin, "valueChanged")
        self.magic_spin = QSpinBox()
        self.magic_spin.setRange(0, 99999999)
        self._register_change(self.magic_spin, "valueChanged")
        self.comment_edit = QLineEdit()
        self._register_change(self.comment_edit)
        self.pending_ttl_spin = QSpinBox()
        self.pending_ttl_spin.setRange(1, 1440)
        self._register_change(self.pending_ttl_spin, "valueChanged")
        self.min_rr_spin = QDoubleSpinBox()
        self.min_rr_spin.setRange(0.0, 20.0)
        self.min_rr_spin.setDecimals(2)
        self._register_change(self.min_rr_spin, "valueChanged")
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(0, 1440)
        self._register_change(self.cooldown_spin, "valueChanged")
        self.dynamic_pending_checkbox = QCheckBox("Lệnh chờ động")
        self._register_change(self.dynamic_pending_checkbox, "stateChanged")
        self.dry_run_checkbox = QCheckBox("Chế độ mô phỏng")
        self._register_change(self.dry_run_checkbox, "stateChanged")
        self.move_to_be_checkbox = QCheckBox("Dời SL về Entry sau TP1")
        self._register_change(self.move_to_be_checkbox, "stateChanged")
        self.trailing_spin = QDoubleSpinBox()
        self.trailing_spin.setRange(0.0, 10.0)
        self.trailing_spin.setDecimals(2)
        self._register_change(self.trailing_spin, "valueChanged")
        self.filling_combo = QComboBox()
        self.filling_combo.addItems(["IOC", "FOK"])
        self._register_change(self.filling_combo, "currentTextChanged")
        order_form.addRow("Deviation (points):", self.deviation_spin)
        order_form.addRow("Magic number:", self.magic_spin)
        order_form.addRow("Comment:", self.comment_edit)
        order_form.addRow("Pending TTL (phút):", self.pending_ttl_spin)
        order_form.addRow("R:R tối thiểu TP2:", self.min_rr_spin)
        order_form.addRow("Thời gian nghỉ (phút):", self.cooldown_spin)
        order_form.addRow(self.dynamic_pending_checkbox)
        order_form.addRow(self.dry_run_checkbox)
        order_form.addRow(self.move_to_be_checkbox)
        order_form.addRow("Trailing ATR multiplier:", self.trailing_spin)
        order_form.addRow("Filling type:", self.filling_combo)

        layout.addWidget(core_group)
        layout.addWidget(order_group)
        layout.addStretch(1)
        self._tabs.addTab(tab, "Auto Trade")

    # ------------------------------------------------------------------
    def _build_services_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        services_tabs = QTabWidget()

        # --- MT5 ---
        mt5_tab = QWidget()
        mt5_form = QFormLayout(mt5_tab)
        self.mt5_enabled = QCheckBox("Kích hoạt MT5")
        self._register_change(self.mt5_enabled, "stateChanged")
        self.mt5_terminal_edit = QLineEdit()
        self._register_change(self.mt5_terminal_edit)
        self.mt5_symbol_edit = QLineEdit()
        self._register_change(self.mt5_symbol_edit)
        self.mt5_m1_spin = QSpinBox()
        self.mt5_m1_spin.setRange(0, 1000)
        self._register_change(self.mt5_m1_spin, "valueChanged")
        self.mt5_m5_spin = QSpinBox()
        self.mt5_m5_spin.setRange(0, 1000)
        self._register_change(self.mt5_m5_spin, "valueChanged")
        self.mt5_m15_spin = QSpinBox()
        self.mt5_m15_spin.setRange(0, 1000)
        self._register_change(self.mt5_m15_spin, "valueChanged")
        self.mt5_h1_spin = QSpinBox()
        self.mt5_h1_spin.setRange(0, 1000)
        self._register_change(self.mt5_h1_spin, "valueChanged")
        mt5_form.addRow(self.mt5_enabled)
        mt5_form.addRow("Đường dẫn terminal:", self.mt5_terminal_edit)
        mt5_form.addRow("Symbol mặc định:", self.mt5_symbol_edit)
        mt5_form.addRow("Số nến M1:", self.mt5_m1_spin)
        mt5_form.addRow("Số nến M5:", self.mt5_m5_spin)
        mt5_form.addRow("Số nến M15:", self.mt5_m15_spin)
        mt5_form.addRow("Số nến H1:", self.mt5_h1_spin)
        services_tabs.addTab(mt5_tab, "MT5")

        # --- Telegram ---
        tele_tab = QWidget()
        tele_form = QFormLayout(tele_tab)
        self.telegram_enabled = QCheckBox("Bật Telegram")
        self._register_change(self.telegram_enabled, "stateChanged")
        self.telegram_token_edit = QLineEdit()
        self._register_change(self.telegram_token_edit)
        self.telegram_chat_edit = QLineEdit()
        self._register_change(self.telegram_chat_edit)
        self.telegram_skip_verify = QCheckBox("Bỏ qua xác minh SSL")
        self._register_change(self.telegram_skip_verify, "stateChanged")
        self.telegram_ca_edit = QLineEdit()
        self._register_change(self.telegram_ca_edit)
        self.telegram_notify_checkbox = QCheckBox("Thông báo khi thoát sớm")
        self._register_change(self.telegram_notify_checkbox, "stateChanged")
        tele_form.addRow(self.telegram_enabled)
        tele_form.addRow("Token:", self.telegram_token_edit)
        tele_form.addRow("Chat ID:", self.telegram_chat_edit)
        tele_form.addRow(self.telegram_skip_verify)
        tele_form.addRow("CA Path:", self.telegram_ca_edit)
        tele_form.addRow(self.telegram_notify_checkbox)
        services_tabs.addTab(tele_tab, "Telegram")

        layout.addWidget(services_tabs)
        layout.addStretch(1)
        self._tabs.addTab(tab, "Services")

    # ------------------------------------------------------------------
    def reset_from_state(self, state: UiConfigState) -> None:
        """Đưa toàn bộ form về trạng thái của cấu hình hiện có."""

        self._state = state
        self.api_key_edit.setText("")
        self.fmp_enabled.setChecked(state.fmp.enabled)
        self.fmp_key_edit.setText(state.fmp.api_key)
        self.te_enabled.setChecked(state.telegram.enabled)
        self.te_key_edit.setText(state.telegram.token)
        self.te_skip_ssl.setChecked(state.telegram.skip_verify)

        self.delete_after_checkbox.setChecked(state.folder.delete_after)
        self.max_files_spin.setValue(state.folder.max_files)
        self.only_changed_checkbox.setChecked(state.folder.only_generate_if_changed)
        self.upload_workers_spin.setValue(state.upload.upload_workers)
        self.cache_enabled_checkbox.setChecked(state.upload.cache_enabled)
        self.optimize_lossless_checkbox.setChecked(state.upload.optimize_lossless)
        self.max_width_spin.setValue(state.image_processing.max_width)
        self.jpeg_quality_spin.setValue(state.image_processing.jpeg_quality)
        self.api_tries_spin.setValue(state.api.tries)
        self.api_delay_spin.setValue(state.api.delay)
        self.max_md_reports_spin.setValue(state.persistence.max_md_reports)

        self.remember_context_checkbox.setChecked(state.context.remember_context)
        self.n_reports_spin.setValue(state.context.n_reports)
        self.ctx_limit_spin.setValue(state.context.ctx_limit)
        self.create_ctx_checkbox.setChecked(state.context.create_ctx_json)
        self.prefer_ctx_checkbox.setChecked(state.context.prefer_ctx_json)
        self.ctx_json_spin.setValue(state.context.ctx_json_n)

        self.weekend_checkbox.setChecked(state.no_run.weekend_enabled)
        self.killzone_checkbox.setChecked(state.no_run.killzone_enabled)
        self.holiday_checkbox.setChecked(state.no_run.holiday_check_enabled)
        self.holiday_country_edit.setText(state.no_run.holiday_check_country)
        self.timezone_edit.setText(state.no_run.timezone)
        self.killzone_summer_edit.setPlainText(_json_dumps(state.no_run.killzone_summer))
        self.killzone_winter_edit.setPlainText(_json_dumps(state.no_run.killzone_winter))

        self.notrade_enabled.setChecked(state.no_trade.enabled)
        self.spread_spin.setValue(state.no_trade.spread_max_pips)
        self.atr_spin.setValue(state.no_trade.min_atr_m5_pips)
        self.min_dist_spin.setValue(state.no_trade.min_dist_keylvl_pips)
        self.session_asia.setChecked(state.no_trade.allow_session_asia)
        self.session_london.setChecked(state.no_trade.allow_session_london)
        self.session_ny.setChecked(state.no_trade.allow_session_ny)

        self.news_block_enabled.setChecked(state.news.block_enabled)
        self.news_before_spin.setValue(state.news.block_before_min)
        self.news_after_spin.setValue(state.news.block_after_min)
        self.news_cache_spin.setValue(state.news.cache_ttl_sec)
        self.news_keywords_edit.setText(", ".join(state.news.priority_keywords) if state.news.priority_keywords else "")
        self.news_surprise_spin.setValue(state.news.surprise_score_threshold)
        self.news_error_threshold_spin.setValue(state.news.provider_error_threshold)
        self.news_backoff_spin.setValue(state.news.provider_error_backoff_sec)
        self.news_currency_overrides.setPlainText(_json_dumps(state.news.currency_country_overrides))
        self.news_symbol_overrides.setPlainText(_json_dumps(state.news.symbol_country_overrides))

        self.autotrade_enabled.setChecked(state.auto_trade.enabled)
        self.strict_bias_checkbox.setChecked(state.auto_trade.strict_bias)
        index = self.size_mode_combo.findText(state.auto_trade.size_mode)
        if index >= 0:
            self.size_mode_combo.setCurrentIndex(index)
        self.risk_spin.setValue(state.auto_trade.risk_per_trade)
        self.split_enabled.setChecked(state.auto_trade.split_tp_enabled)
        self.split_ratio_spin.setValue(state.auto_trade.split_tp_ratio)
        self.deviation_spin.setValue(state.auto_trade.deviation)
        self.magic_spin.setValue(state.auto_trade.magic_number)
        self.comment_edit.setText(state.auto_trade.comment)
        self.pending_ttl_spin.setValue(state.auto_trade.pending_ttl_min)
        self.min_rr_spin.setValue(state.auto_trade.min_rr_tp2)
        self.cooldown_spin.setValue(state.auto_trade.cooldown_min)
        self.dynamic_pending_checkbox.setChecked(state.auto_trade.dynamic_pending)
        self.dry_run_checkbox.setChecked(state.auto_trade.dry_run)
        self.move_to_be_checkbox.setChecked(state.auto_trade.move_to_be_after_tp1)
        self.trailing_spin.setValue(state.auto_trade.trailing_atr_mult)
        index = self.filling_combo.findText(state.auto_trade.filling_type)
        if index >= 0:
            self.filling_combo.setCurrentIndex(index)

        self.mt5_enabled.setChecked(state.mt5.enabled)
        self.mt5_terminal_edit.setText(state.mt5_terminal_path)
        self.mt5_symbol_edit.setText(state.mt5.symbol)
        self.mt5_m1_spin.setValue(state.mt5.n_M1)
        self.mt5_m5_spin.setValue(state.mt5.n_M5)
        self.mt5_m15_spin.setValue(state.mt5.n_M15)
        self.mt5_h1_spin.setValue(state.mt5.n_H1)

        self.telegram_enabled.setChecked(state.telegram.enabled)
        self.telegram_token_edit.setText(state.telegram.token)
        self.telegram_chat_edit.setText(state.telegram.chat_id)
        self.telegram_skip_verify.setChecked(state.telegram.skip_verify)
        self.telegram_ca_edit.setText(state.telegram.ca_path)
        self.telegram_notify_checkbox.setChecked(state.telegram.notify_on_early_exit)

    # ------------------------------------------------------------------
    def collect_payload(self) -> dict[str, Any]:
        """Thu thập dữ liệu từ form để chuẩn bị ghi workspace."""

        priority = _parse_keywords(self.news_keywords_edit.text())
        currency_overrides = _parse_mapping(self.news_currency_overrides.toPlainText())
        symbol_overrides = _parse_mapping(self.news_symbol_overrides.toPlainText())
        killzone_summer = _parse_killzone(self.killzone_summer_edit.toPlainText())
        killzone_winter = _parse_killzone(self.killzone_winter_edit.toPlainText())

        payload: dict[str, Any] = {
            "folder": {
                "delete_after": self.delete_after_checkbox.isChecked(),
                "max_files": self.max_files_spin.value(),
                "only_generate_if_changed": self.only_changed_checkbox.isChecked(),
            },
            "upload": {
                "upload_workers": self.upload_workers_spin.value(),
                "cache_enabled": self.cache_enabled_checkbox.isChecked(),
                "optimize_lossless": self.optimize_lossless_checkbox.isChecked(),
            },
            "persistence": {
                "max_md_reports": self.max_md_reports_spin.value(),
            },
            "image_processing": {
                "max_width": self.max_width_spin.value(),
                "jpeg_quality": self.jpeg_quality_spin.value(),
            },
            "api": {
                "tries": self.api_tries_spin.value(),
                "delay": float(self.api_delay_spin.value()),
            },
            "fmp": {
                "enabled": self.fmp_enabled.isChecked(),
                "api_key": self.fmp_key_edit.text().strip(),
            },
            "telegram": {
                "enabled": self.telegram_enabled.isChecked(),
                "token": self.telegram_token_edit.text().strip(),
                "chat_id": self.telegram_chat_edit.text().strip(),
                "skip_verify": self.telegram_skip_verify.isChecked(),
                "ca_path": self.telegram_ca_edit.text().strip(),
                "notify_on_early_exit": self.telegram_notify_checkbox.isChecked(),
            },
            "context": {
                "remember_context": self.remember_context_checkbox.isChecked(),
                "n_reports": self.n_reports_spin.value(),
                "ctx_limit": self.ctx_limit_spin.value(),
                "create_ctx_json": self.create_ctx_checkbox.isChecked(),
                "prefer_ctx_json": self.prefer_ctx_checkbox.isChecked(),
                "ctx_json_n": self.ctx_json_spin.value(),
            },
            "mt5": {
                "enabled": self.mt5_enabled.isChecked(),
                "terminal_path": self.mt5_terminal_edit.text().strip(),
                "symbol": self.mt5_symbol_edit.text().strip(),
                "n_M1": self.mt5_m1_spin.value(),
                "n_M5": self.mt5_m5_spin.value(),
                "n_M15": self.mt5_m15_spin.value(),
                "n_H1": self.mt5_h1_spin.value(),
            },
            "no_run": {
                "weekend_enabled": self.weekend_checkbox.isChecked(),
                "killzone_enabled": self.killzone_checkbox.isChecked(),
                "holiday_check_enabled": self.holiday_checkbox.isChecked(),
                "holiday_check_country": self.holiday_country_edit.text().strip(),
                "timezone": self.timezone_edit.text().strip(),
                "killzone_summer": killzone_summer,
                "killzone_winter": killzone_winter,
            },
            "no_trade": {
                "enabled": self.notrade_enabled.isChecked(),
                "spread_max_pips": float(self.spread_spin.value()),
                "min_atr_m5_pips": float(self.atr_spin.value()),
                "min_dist_keylvl_pips": float(self.min_dist_spin.value()),
                "allow_session_asia": self.session_asia.isChecked(),
                "allow_session_london": self.session_london.isChecked(),
                "allow_session_ny": self.session_ny.isChecked(),
            },
            "auto_trade": {
                "enabled": self.autotrade_enabled.isChecked(),
                "strict_bias": self.strict_bias_checkbox.isChecked(),
                "size_mode": self.size_mode_combo.currentText(),
                "risk_per_trade": float(self.risk_spin.value()),
                "split_tp_enabled": self.split_enabled.isChecked(),
                "split_tp_ratio": self.split_ratio_spin.value(),
                "deviation": self.deviation_spin.value(),
                "magic_number": self.magic_spin.value(),
                "comment": self.comment_edit.text().strip(),
                "pending_ttl_min": self.pending_ttl_spin.value(),
                "min_rr_tp2": float(self.min_rr_spin.value()),
                "cooldown_min": self.cooldown_spin.value(),
                "dynamic_pending": self.dynamic_pending_checkbox.isChecked(),
                "dry_run": self.dry_run_checkbox.isChecked(),
                "move_to_be_after_tp1": self.move_to_be_checkbox.isChecked(),
                "trailing_atr_mult": float(self.trailing_spin.value()),
                "filling_type": self.filling_combo.currentText(),
            },
            "news": {
                "block_enabled": self.news_block_enabled.isChecked(),
                "block_before_min": self.news_before_spin.value(),
                "block_after_min": self.news_after_spin.value(),
                "cache_ttl_sec": self.news_cache_spin.value(),
                "priority_keywords": priority,
                "surprise_score_threshold": float(self.news_surprise_spin.value()),
                "provider_error_threshold": self.news_error_threshold_spin.value(),
                "provider_error_backoff_sec": self.news_backoff_spin.value(),
                "currency_country_overrides": currency_overrides,
                "symbol_country_overrides": symbol_overrides,
            },
        }

        if self.api_key_edit.text().strip():
            payload.setdefault("api_keys", {})["google_ai"] = self.api_key_edit.text().strip()

        return payload
