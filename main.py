import sys
import subprocess
import os

def main():
    # Ensure we run using the virtual environment if it exists
    venv_python_1 = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")
    venv_python_2 = os.path.join(os.path.dirname(__file__), "venv", "bin", "python")
    venv_python = venv_python_1 if os.path.exists(venv_python_1) else (venv_python_2 if os.path.exists(venv_python_2) else None)
    
    if venv_python and os.path.abspath(sys.executable) != os.path.abspath(venv_python):
        print(f"Relaunching in virtual environment ({venv_python})...")
        subprocess.run([venv_python, os.path.join(os.path.dirname(__file__), "gui.py")])
    else:
        # Import and run directly if already in venv or no venv
        from gui import ModernMapsExtractor
        from PySide6.QtWidgets import QApplication
        
        app = QApplication(sys.argv)
        window = ModernMapsExtractor()
        window.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()
