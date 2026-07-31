import sys
import subprocess
import os

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# Configure bundled Playwright browsers path if present in PyInstaller bundle
bundled_browsers = get_resource_path("ms-playwright")
if os.path.exists(bundled_browsers):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

def main():
    # Handle browser pre-installation CLI flag (e.g. called by installer post-setup)
    if "--install-browsers" in sys.argv:
        from scraper import ensure_playwright_browsers
        print("Installing Playwright Chromium browser binaries...")
        success = ensure_playwright_browsers()
        sys.exit(0 if success else 1)

    # Ensure we run using the virtual environment if running from source and venv exists
    venv_python_1 = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")
    venv_python_2 = os.path.join(os.path.dirname(__file__), "venv", "bin", "python")
    venv_python = venv_python_1 if os.path.exists(venv_python_1) else (venv_python_2 if os.path.exists(venv_python_2) else None)
    
    if not getattr(sys, 'frozen', False) and venv_python and os.path.abspath(sys.executable) != os.path.abspath(venv_python):
        print(f"Relaunching in virtual environment ({venv_python})...")
        subprocess.run([venv_python, os.path.join(os.path.dirname(__file__), "gui.py")] + sys.argv[1:])
    else:
        # Import and run directly
        from gui import ModernMapsExtractor
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon
        
        app = QApplication(sys.argv)

        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FixareStudio.LeadPulse.Extractor.1.0")
            except Exception:
                pass

        for icon_file in ["icon.png", "icon.ico", "icon.icns"]:
            icon_path = get_resource_path(icon_file)
            if os.path.exists(icon_path):
                app.setWindowIcon(QIcon(icon_path))
                break

        window = ModernMapsExtractor()
        window.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()
