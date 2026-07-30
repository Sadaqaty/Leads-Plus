import sys
import asyncio
import csv
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget, 
                             QTableWidgetItem, QLabel, QHeaderView, QFrame, QSpinBox,
                             QFileDialog, QTextEdit, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QColor, QIcon, QPalette
from scraper import MapsScraper
from database import DatabaseManager
from wakepy import keep

class StatCard(QFrame):
    def __init__(self, title, value="0", icon_str="📊", accent_color="#8B5CF6"):
        super().__init__()
        self.setObjectName("StatCard")
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background-color: #1E1E24;
                border: 1px solid #2D2D38;
                border-radius: 12px;
                padding: 12px;
            }}
            QFrame#StatCard:hover {{
                border: 1px solid {accent_color};
                background-color: #24242D;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        
        # Icon box
        icon_label = QLabel(icon_str)
        icon_label.setFont(QFont("Segoe UI Emoji", 18))
        layout.addWidget(icon_label)
        
        # Text box
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Inter", 9, QFont.Medium))
        self.title_label.setStyleSheet("color: #9CA3AF;")
        
        self.value_label = QLabel(value)
        self.value_label.setFont(QFont("Inter", 16, QFont.Bold))
        self.value_label.setStyleSheet(f"color: {accent_color};")
        
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.value_label)
        layout.addLayout(text_layout)
        layout.addStretch()

    def set_value(self, val):
        self.value_label.setText(str(val))


class ScraperThread(QThread):
    result_ready = Signal(dict, dict) # item, meta
    finished = Signal()
    error = Signal(str)

    def __init__(self, queries, limit):
        super().__init__()
        self.queries = queries
        self.limit = limit
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
                    stop_event=self.stop_event
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
        self.resize(1450, 900)
        self.db = DatabaseManager()
        self.set_modern_dark_theme()
        
        self.fields = [
            "place_id", "name", "query", "is_spending_on_ads", "reviews", "rating", "first_review", "website", 
            "phone", "can_claim", "email", "contacts_count", "linkedin", "twitter", "facebook", 
            "youtube", "instagram", "owner_name", "main_category", "workday_timing", 
            "is_temporarily_closed", "address", "review_keywords", "link"
        ]

        self.results = []
        self.email_count = 0
        self.phone_count = 0
        self.social_count = 0
        
        # Central Widget & Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(20, 15, 20, 15)
        self.main_layout.setSpacing(15)

        # Header Bar
        header_layout = QHBoxLayout()
        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        
        self.brand_title = QLabel("⚡ LeadPulse Enterprise")
        self.brand_title.setFont(QFont("Inter", 18, QFont.Bold))
        self.brand_title.setStyleSheet("color: #F3F4F6; margin: 0px;")
        
        self.brand_subtitle = QLabel("Google Maps Business Intelligence & Deep Web Enrichment Suite")
        self.brand_subtitle.setFont(QFont("Inter", 10))
        self.brand_subtitle.setStyleSheet("color: #6B7280; margin: 0px;")
        
        title_vbox.addWidget(self.brand_title)
        title_vbox.addWidget(self.brand_subtitle)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        self.main_layout.addLayout(header_layout)

        # Stat Cards Bar
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)
        
        self.card_total = StatCard("TOTAL EXTRACTED", "0", "🚀", "#8B5CF6")
        self.card_emails = StatCard("VALID EMAILS", "0", "✉️", "#10B981")
        self.card_phones = StatCard("PHONE NUMBERS", "0", "📞", "#3B82F6")
        self.card_socials = StatCard("SOCIAL PROFILES", "0", "🌐", "#F59E0B")
        
        stats_layout.addWidget(self.card_total)
        stats_layout.addWidget(self.card_emails)
        stats_layout.addWidget(self.card_phones)
        stats_layout.addWidget(self.card_socials)
        self.main_layout.addLayout(stats_layout)

        # Search Control Panel
        self.control_panel = QFrame()
        self.control_panel.setObjectName("ControlPanel")
        self.control_panel.setStyleSheet("""
            QFrame#ControlPanel {
                background-color: #1E1E24;
                border: 1px solid #2D2D38;
                border-radius: 14px;
                padding: 15px;
            }
        """)
        self.control_layout = QVBoxLayout(self.control_panel)
        self.control_layout.setSpacing(10)
        self.control_layout.setContentsMargins(15, 12, 15, 12)
        
        label_queries = QLabel("🎯 Target Search Queries (enter one query per line):")
        label_queries.setFont(QFont("Inter", 10, QFont.Bold))
        label_queries.setStyleSheet("color: #E5E7EB;")
        self.control_layout.addWidget(label_queries)

        self.queries_input = QTextEdit()
        self.queries_input.setPlaceholderText("e.g.\ncoffee shop in lahore pakistan\ndentists in manchester uk\nsoftware companies in austin tx")
        self.queries_input.setMaximumHeight(85)
        self.queries_input.setStyleSheet("""
            QTextEdit {
                background-color: #121216; 
                border: 1px solid #374151; 
                color: #F9FAFB; 
                border-radius: 8px; 
                padding: 10px;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #6366F1;
            }
        """)
        self.control_layout.addWidget(self.queries_input)

        # Controls & Action Buttons
        settings_layout = QHBoxLayout()
        settings_layout.setSpacing(15)
        
        limit_label = QLabel("Max Limit / Query:")
        limit_label.setStyleSheet("color: #9CA3AF; font-weight: bold;")
        settings_layout.addWidget(limit_label)
        
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 10000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSuffix(" items")
        self.limit_spin.setStyleSheet("""
            QSpinBox {
                background-color: #121216; 
                border: 1px solid #374151; 
                color: #F9FAFB; 
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: bold;
            }
        """)
        settings_layout.addWidget(self.limit_spin)
        
        settings_layout.addStretch()
        
        self.stop_btn = QPushButton("🛑 Stop Session")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(42)
        self.stop_btn.setMinimumWidth(130)
        self.stop_btn.clicked.connect(self.stop_scraping)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #7F1D1D; 
                color: #FCA5A5; 
                border: 1px solid #991B1B; 
                font-weight: bold; 
                border-radius: 8px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #991B1B;
                color: #FFFFFF;
            }
            QPushButton:disabled {
                background-color: #262626;
                color: #525252;
                border: 1px solid #333;
            }
        """)
        settings_layout.addWidget(self.stop_btn)
        
        self.start_btn = QPushButton("🚀 Launch Extractor Engine")
        self.start_btn.setMinimumHeight(42)
        self.start_btn.setMinimumWidth(210)
        self.start_btn.setFont(QFont("Inter", 10, QFont.Bold))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366F1, stop:1 #8B5CF6); 
                color: white; 
                border: none; 
                border-radius: 8px;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4F46E5, stop:1 #7C3AED);
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9CA3AF;
            }
        """)
        self.start_btn.clicked.connect(self.start_scraping)
        settings_layout.addWidget(self.start_btn)
        
        self.control_layout.addLayout(settings_layout)
        self.main_layout.addWidget(self.control_panel)

        # Data Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.fields))
        self.table.setHorizontalHeaderLabels([f.replace('_', ' ').title() for f in self.fields])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #121216;
                alternate-background-color: #18181F;
                color: #E5E7EB;
                gridline-color: #27272A;
                border: 1px solid #27272A;
                border-radius: 10px;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #4F46E5;
                color: white;
            }
            QHeaderView::section {
                background-color: #1E1E24;
                color: #A78BFA;
                padding: 10px;
                font-weight: bold;
                font-size: 11px;
                border: none;
                border-bottom: 2px solid #374151;
                border-right: 1px solid #27272A;
            }
        """)
        self.main_layout.addWidget(self.table, 1)
        
        # Footer Bar
        self.footer_layout = QHBoxLayout()

        status_vbox = QVBoxLayout()
        status_vbox.setSpacing(2)
        self.status_label = QLabel("Status: Ready")
        self.status_label.setFont(QFont("Inter", 10, QFont.Bold))
        self.status_label.setStyleSheet("color: #9CA3AF;")
        status_vbox.addWidget(self.status_label)
        
        self.progress_detail = QLabel("System initialized. Ready for batch extraction.")
        self.progress_detail.setStyleSheet("color: #10B981; font-size: 12px;")
        status_vbox.addWidget(self.progress_detail)
        
        self.footer_layout.addLayout(status_vbox)
        self.footer_layout.addStretch()
        
        self.export_btn = QPushButton("📊 Export Clean CSV")
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setMinimumHeight(38)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669; 
                color: white; 
                border: none;
                padding: 8px 18px; 
                font-weight: bold; 
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #10B981;
            }
        """)
        self.footer_layout.addWidget(self.export_btn)
        
        self.main_layout.addLayout(self.footer_layout)
        
    def set_modern_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0B0B0E; }
            QWidget { background-color: #0B0B0E; color: #F3F4F6; font-family: 'Inter', 'Segoe UI', sans-serif; }
            QScrollBar:vertical {
                border: none;
                background: #121216;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4B5563;
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
        self.card_phones.set_value("0")
        self.card_socials.set_value("0")
        
        self.table.setRowCount(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Status: Executing search batch ({len(queries)} queries)...")
        self.progress_detail.setText("Playwright engine starting up...")
        
        self.thread = ScraperThread(queries, self.limit_spin.value())
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
        if item.get("phone") and item.get("phone") != "N/A":
            self.phone_count += 1
        if any(item.get(s) and item.get(s) != "N/A" for s in ["linkedin", "twitter", "facebook", "youtube", "instagram"]):
            self.social_count += 1
            
        self.card_total.set_value(len(self.results))
        self.card_emails.set_value(self.email_count)
        self.card_phones.set_value(self.phone_count)
        self.card_socials.set_value(self.social_count)
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        for i, field in enumerate(self.fields):
            val = str(item.get(field, "N/A"))
            table_item = QTableWidgetItem(val)
            # Highlight items with emails
            if field == "email" and val != "N/A":
                table_item.setForeground(QColor("#34D399"))
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
