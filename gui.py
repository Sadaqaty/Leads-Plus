import sys
import os
import asyncio
import csv
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget, 
                             QTableWidgetItem, QLabel, QHeaderView, QFrame, QSpinBox,
                             QFileDialog, QTextEdit, QGraphicsDropShadowEffect, QCheckBox)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSize
from PySide6.QtGui import QFont, QColor, QIcon, QPixmap
from scraper import MapsScraper
from database import DatabaseManager
from wakepy import keep

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller bundle."""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def load_svg_pixmap(svg_filename, width=38, height=38):
    """Load vector SVG icon cleanly into a QPixmap."""
    svg_path = get_resource_path(os.path.join("assets", "icons", svg_filename))
    if not os.path.exists(svg_path):
        svg_path = get_resource_path(svg_filename)
        
    if os.path.exists(svg_path):
        pixmap = QPixmap(svg_path)
        if not pixmap.isNull():
            return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QPixmap()

def get_svg_icon(svg_filename, width=18, height=18):
    pix = load_svg_pixmap(svg_filename, width, height)
    return QIcon(pix)


class StatCard(QFrame):
    def __init__(self, title, value="0", svg_filename="card_database.svg"):
        super().__init__()
        self.setObjectName("StatCard")
        self.setStyleSheet("""
            QFrame#StatCard {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
            }
            QFrame#StatCard:hover {
                border: 1px solid #CBD5E1;
            }
        """)
        
        # Subtle drop shadow effect for elevation
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 10))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        
        # Left Text box (Title & Count)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Inter", 9, QFont.Bold))
        self.title_label.setStyleSheet("color: #111827; background: transparent;")
        
        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Inter", 22, QFont.Bold))
        self.value_label.setStyleSheet("color: #111827; background: transparent;")
        
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.value_label)
        layout.addLayout(text_layout)
        
        layout.addStretch()
        
        # Right SVG Vector Icon
        icon_pixmap = load_svg_pixmap(svg_filename, 38, 38)
        icon_label = QLabel()
        icon_label.setPixmap(icon_pixmap)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

    def set_value(self, val):
        self.value_label.setText(str(val))


class ScraperThread(QThread):
    result_ready = Signal(dict, dict) # item, meta
    finished = Signal()
    error = Signal(str)

    def __init__(self, queries, limit, headless=True):
        super().__init__()
        self.queries = queries
        self.limit = limit
        self.headless = headless
        self.scraper = MapsScraper()
        self.stop_event = None

    def stop(self):
        if self.stop_event:
            self.stop_event.set()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.stop_event = asyncio.Event()
        
        async def callback(data, meta):
            if self.stop_event.is_set():
                return
            self.result_ready.emit(data, meta)
            
        try:
            with keep.running():
                loop.run_until_complete(self.scraper.scrape_maps(
                    self.queries, 
                    total_results=self.limit, 
                    callback=callback,
                    stop_event=self.stop_event,
                    headless=self.headless
                ))
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()


class ModernMapsExtractor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LeadPulse - Industrial Google Maps Intelligence")
        self.resize(1380, 860)
        self.db = DatabaseManager()
        self.set_clean_light_theme()
        
        self.fields = [
            "place_id", "name", "query", "is_spending_on_ads", "reviews", "rating", "first_review", "website", 
            "phone", "can_claim", "email", "contacts_count", "linkedin", "twitter", "facebook", 
            "youtube", "instagram", "owner_name", "main_category", "workday_timing", 
            "is_temporarily_closed", "address", "latitude", "longitude", "review_keywords", "link"
        ]

        self.results = []
        self.email_count = 0
        self.phone_count = 0
        self.social_count = 0
        
        # Central Widget & Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(16)

        # Header Bar
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)
        
        # Lightning Bolt Brand Icon
        brand_icon_label = QLabel()
        brand_icon_label.setPixmap(load_svg_pixmap("brand_lightning.svg", 26, 26))
        brand_icon_label.setStyleSheet("background: transparent;")
        header_layout.addWidget(brand_icon_label, 0, Qt.AlignVCenter)
        
        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        
        self.brand_title = QLabel("LeadPulse Enterprise")
        self.brand_title.setFont(QFont("Inter", 17, QFont.Bold))
        self.brand_title.setStyleSheet("color: #111827; margin: 0px; background: transparent;")
        
        self.brand_subtitle = QLabel("Google Maps Business Intelligence & Deep Web Enrichment Suite")
        self.brand_subtitle.setFont(QFont("Inter", 9.5))
        self.brand_subtitle.setStyleSheet("color: #6B7280; margin: 0px; background: transparent;")
        
        title_vbox.addWidget(self.brand_title)
        title_vbox.addWidget(self.brand_subtitle)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        self.main_layout.addLayout(header_layout)

        # Stat Cards Bar (4 clean vector cards)
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(16)
        
        self.card_total = StatCard("Total Extracted Leads", "0", "card_database.svg")
        self.card_emails = StatCard("Valid Contact Details", "0", "card_contacts.svg")
        self.card_socials = StatCard("Social Profile Links", "0", "card_globe.svg")
        self.card_verified = StatCard("Verified Business List", "0", "card_store.svg")
        
        stats_layout.addWidget(self.card_total)
        stats_layout.addWidget(self.card_emails)
        stats_layout.addWidget(self.card_socials)
        stats_layout.addWidget(self.card_verified)
        self.main_layout.addLayout(stats_layout)

        # Search Control Panel
        self.control_panel = QFrame()
        self.control_panel.setObjectName("ControlPanel")
        self.control_panel.setStyleSheet("""
            QFrame#ControlPanel {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 10px;
            }
        """)
        
        # Subtle drop shadow effect for elevation
        shadow_panel = QGraphicsDropShadowEffect(self)
        shadow_panel.setBlurRadius(8)
        shadow_panel.setColor(QColor(0, 0, 0, 8))
        shadow_panel.setOffset(0, 2)
        self.control_panel.setGraphicsEffect(shadow_panel)

        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setSpacing(12)
        self.control_layout.setContentsMargins(18, 16, 18, 16)
        
        label_queries = QLabel("Google Maps Search Queries (one query per line):")
        label_queries.setFont(QFont("Inter", 9.5, QFont.Bold))
        label_queries.setStyleSheet("color: #111827; background: transparent;")
        self.control_layout.addWidget(label_queries)

        self.queries_input = QTextEdit()
        self.queries_input.setPlaceholderText("e.g.\ncoffee shop in lahore pakistan\ndentists in manchester uk")
        self.queries_input.setMaximumHeight(85)
        self.queries_input.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF; 
                border: 1px solid #D1D5DB; 
                color: #111827; 
                border-radius: 6px; 
                padding: 10px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #3B3A68;
            }
        """)
        self.control_layout.addWidget(self.queries_input)

        # Controls & Action Buttons
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(16)
        
        limit_label = QLabel("Max Limit / Query:")
        limit_label.setStyleSheet("color: #111827; font-weight: bold; font-size: 13px; background: transparent;")
        settings_layout.addWidget(limit_label)
        
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 10000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSuffix(" items")
        self.limit_spin.setStyleSheet("""
            QSpinBox {
                background-color: #FFFFFF; 
                border: 1px solid #D1D5DB; 
                color: #111827; 
                padding: 6px 12px;
                border-radius: 6px;
                font-weight: bold;
            }
            QSpinBox::drop-down {
                border: none;
            }
        """)
        settings_layout.addWidget(self.limit_spin)
        
        # Silent Extraction Checkbox
        self.headless_cb = QCheckBox("Silent Background Extraction")
        self.headless_cb.setChecked(True)
        self.headless_cb.setStyleSheet("""
            QCheckBox {
                color: #111827;
                font-weight: bold;
                font-size: 13px;
                spacing: 8px;
                background: transparent;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid #9CA3AF;
                background-color: #FFFFFF;
            }
            QCheckBox::indicator:checked {
                background-color: #3B3A68;
                border: 1px solid #3B3A68;
            }
        """)
        settings_layout.addWidget(self.headless_cb)
        
        settings_layout.addStretch()
        
        # Stop Session Button
        self.stop_btn = QPushButton(" Stop Session")
        self.stop_btn.setIcon(get_svg_icon("icon_stop.svg", 14, 14))
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setMinimumWidth(125)
        self.stop_btn.clicked.connect(self.stop_scraping)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEE2E2; 
                color: #991B1B; 
                border: 1px solid #FCA5A5; 
                font-weight: bold; 
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FCA5A5;
                color: #7F1D1D;
            }
            QPushButton:disabled {
                background-color: #F3F4F6;
                color: #9CA3AF;
                border: 1px solid #E5E7EB;
            }
        """)
        settings_layout.addWidget(self.stop_btn)
        
        # Launch Extractor Engine Button
        self.start_btn = QPushButton(" Launch Extractor Engine")
        self.start_btn.setIcon(get_svg_icon("icon_rocket.svg", 16, 16))
        self.start_btn.setIconSize(QSize(16, 16))
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.setFont(QFont("Inter", 10, QFont.Bold))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2E2A68; 
                color: #FFFFFF; 
                border: none; 
                border-radius: 6px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #1E1A50;
            }
            QPushButton:disabled {
                background-color: #9CA3AF;
                color: #F3F4F6;
            }
        """)
        self.start_btn.clicked.connect(self.start_scraping)
        settings_layout.addWidget(self.start_btn)
        
        self.control_layout.addLayout(settings_layout)
        self.main_layout.addWidget(self.control_panel)

        # Data Results Table
        self.table = QTableWidget()
        
        # Custom Table Header Labels matching user's exact screenshot layout:
        # Place Id | Name | Query | Spending On Ad | Reviews | Rating | First Review | Website | Phone ↕ | Can Claim | Email ↕ | Contacts Count | Linkedin | Twitter
        display_headers = [
            "Place Id", "Name", "Query", "Spending On Ad", "Reviews", "Rating", 
            "First Review", "Website", "Phone ↕", "Can Claim", "Email ↕", 
            "Contacts Count", "Linkedin", "Twitter"
        ]
        
        # Map table columns
        self.table_fields = [
            "place_id", "name", "query", "is_spending_on_ads", "reviews", "rating",
            "first_review", "website", "phone", "can_claim", "email",
            "contacts_count", "linkedin", "twitter"
        ]
        
        self.table.setColumnCount(len(display_headers))
        self.table.setHorizontalHeaderLabels(display_headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #FAFAFA;
                color: #111827;
                gridline-color: #F3F4F6;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #F3F4F6;
            }
            QTableWidget::item:selected {
                background-color: #EEF2FF;
                color: #1E1B4B;
            }
            QHeaderView::section {
                background-color: #FFFFFF;
                color: #111827;
                padding: 10px;
                font-weight: bold;
                font-size: 12px;
                border: none;
                border-bottom: 2px solid #E5E7EB;
                border-right: 1px solid #E5E7EB;
            }
        """)
        self.main_layout.addWidget(self.table, 1)
        
        # Footer Bar
        self.footer_layout = QHBoxLayout()

        status_vbox = QVBoxLayout()
        status_vbox.setSpacing(2)
        self.status_label = QLabel("Status: Ready")
        self.status_label.setFont(QFont("Inter", 9.5, QFont.Bold))
        self.status_label.setStyleSheet("color: #111827; background: transparent;")
        status_vbox.addWidget(self.status_label)
        
        self.progress_detail = QLabel("System initialized. Ready for batch extraction.")
        self.progress_detail.setStyleSheet("color: #059669; font-size: 12px; font-weight: 500; background: transparent;")
        status_vbox.addWidget(self.progress_detail)
        
        self.footer_layout.addLayout(status_vbox)
        self.footer_layout.addStretch()
        
        # Copyright Footer Label
        self.copyright_label = QLabel("© Fixare Studio. All Rights Reserved. Intellectual Property of Fixare Studio.")
        self.copyright_label.setStyleSheet("color: #6B7280; font-size: 11px; font-weight: 500; background: transparent;")
        self.footer_layout.addWidget(self.copyright_label)
        self.footer_layout.addStretch()
        
        # Export Button with Chart Icon
        self.export_btn = QPushButton(" Export Clean CSV")
        self.export_btn.setIcon(get_svg_icon("icon_export.svg", 16, 16))
        self.export_btn.setIconSize(QSize(16, 16))
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setMinimumHeight(38)
        self.export_btn.setFont(QFont("Inter", 9.5, QFont.Bold))
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; 
                color: #FFFFFF; 
                border: none;
                padding: 8px 18px; 
                font-weight: bold; 
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)

        # Set AppUserModelID on Windows so taskbar displays custom icon instead of default Python logo
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FixareStudio.LeadPulse.Extractor.1.0")
            except Exception:
                pass

        # Set window icon reliably from resource path
        for icon_file in ["icon.png", "icon.ico", "icon.icns"]:
            icon_path = get_resource_path(icon_file)
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self.footer_layout.addWidget(self.export_btn)
        
        self.main_layout.addLayout(self.footer_layout)
        
    def set_clean_light_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #F8F9FA; }
            QWidget { background-color: #F8F9FA; color: #111827; font-family: 'Inter', 'Segoe UI', sans-serif; }
            QScrollBar:vertical {
                border: none;
                background: #F1F5F9;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #CBD5E1;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def start_scraping(self):
        raw_input = self.queries_input.toPlainText().strip()
        if not raw_input:
            self.status_label.setText("Status: No queries provided.")
            return

        queries = []
        for line in raw_input.split('\n'):
            q = line.strip()
            if q: queries.append(q)
            
        if not queries:
            self.status_label.setText("Status: No valid queries found.")
            return
            
        self.results = []
        self.email_count = 0
        self.phone_count = 0
        self.social_count = 0
        
        self.card_total.set_value("0")
        self.card_emails.set_value("0")
        self.card_socials.set_value("0")
        self.card_verified.set_value("0")
        
        self.table.setRowCount(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Status: Executing search batch ({len(queries)} queries)...")
        is_headless = self.headless_cb.isChecked()
        mode_str = "silent background" if is_headless else "visual browser"
        self.progress_detail.setText(f"Playwright engine starting up ({mode_str} mode)...")
        
        self.thread = ScraperThread(queries, self.limit_spin.value(), headless=is_headless)
        self.thread.result_ready.connect(self.on_item_extracted)
        self.thread.finished.connect(self.on_finished)
        self.thread.error.connect(self.on_error)
        self.thread.start()

    def stop_scraping(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()
            self.status_label.setText("Status: Halting extraction session...")
            self.progress_detail.setText("Sending cancellation signal to scraper engine...")
            self.stop_btn.setEnabled(False)

    @Slot(dict, dict)
    def on_item_extracted(self, item, meta):
        place_id = item.get("place_id")
        if place_id != "N/A" and any(r.get("place_id") == place_id for r in self.results):
            return
        
        self.results.append(item)
        
        # Track statistics
        if item.get("email") and item.get("email") != "N/A":
            self.email_count += 1
        if any(item.get(s) and item.get(s) != "N/A" for s in ["linkedin", "twitter", "facebook", "youtube", "instagram"]):
            self.social_count += 1
            
        self.card_total.set_value(len(self.results))
        self.card_emails.set_value(self.email_count)
        self.card_socials.set_value(self.social_count)
        self.card_verified.set_value(len(self.results))
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        for i, field in enumerate(self.table_fields):
            val = str(item.get(field, "N/A"))
            table_item = QTableWidgetItem(val)
            # Highlight items with emails
            if field == "email" and val != "N/A":
                table_item.setForeground(QColor("#059669"))
            self.table.setItem(row, i, table_item)
        
        query_info = f"Query {meta['query_idx']}/{meta['total_queries']}: '{meta['query_name']}'"
        item_info = f"Extracted item {meta['current_count']} | Total leads: {len(self.results)}"
        self.status_label.setText(f"Status: {query_info}")
        self.progress_detail.setText(f"Processing: {item_info}")
        self.table.scrollToBottom()

    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"Status: Completed Batch ({len(self.results)} total leads extracted)")
        self.progress_detail.setText("All queries processed successfully.")

    def on_error(self, error_msg):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"Status: Stopped with notice - {error_msg}")
        self.progress_detail.setText("Extraction engine released.")

    def export_csv(self):
        if not self.results:
            self.status_label.setText("Status: No active session data to export.")
            return
        
        filename, _ = QFileDialog.getSaveFileName(self, "Export Clean CSV Dataset", "google_maps_leads.csv", "CSV Files (*.csv)")
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.fields, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(self.results)
                self.status_label.setText(f"Status: Successfully exported dataset to {filename}")
            except Exception as e:
                self.status_label.setText(f"Status: Export failed - {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernMapsExtractor()
    window.show()
    sys.exit(app.exec())
