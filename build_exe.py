import os
import sys
import subprocess

def build():
    print("🚀 Building LeadPulse Enterprise Extractor Executable...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "LeadPulse",
        "--icon", os.path.join(base_dir, "icon.ico"),
        "--add-data", f"{os.path.join(base_dir, 'icon.ico')}{os.pathsep}.",
        "--add-data", f"{os.path.join(base_dir, 'icon.png')}{os.pathsep}.",
        "--add-data", f"{os.path.join(base_dir, 'assets')}{os.pathsep}assets",
        "--add-data", f"{os.path.join(base_dir, 'config.env.example')}{os.pathsep}.",
    ]

    ms_playwright_dir = os.path.join(base_dir, "ms-playwright")
    if os.path.exists(ms_playwright_dir):
        cmd.extend(["--add-data", f"{ms_playwright_dir}{os.pathsep}ms-playwright"])

    cmd.extend([
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.async_api",
        "--hidden-import", "PySide6",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "database",
        "--hidden-import", "scraper",
        "--hidden-import", "wakepy",
        os.path.join(base_dir, "main.py")
    ])
    
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("\n✅ PyInstaller Build Complete! Executable created in dist/LeadPulse/LeadPulse.exe")
    else:
        print("\n❌ PyInstaller Build Failed!")

if __name__ == "__main__":
    build()
