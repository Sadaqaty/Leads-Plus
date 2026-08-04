import os
import sys
import subprocess
import argparse

def build_gui(base_dir):
    print("\n🚀 Building LeadPulse Enterprise Desktop GUI Executable...")
    icon_file = "icon.ico" if sys.platform == "win32" else "icon.png"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", "LeadPulse",
        "--icon", os.path.join(base_dir, icon_file),
        "--add-data", f"{os.path.join(base_dir, 'assets')}{os.pathsep}assets",
        "--add-data", f"{os.path.join(base_dir, 'config.env.example')}{os.pathsep}.",
    ]

    ms_playwright_dir = os.path.join(base_dir, "ms-playwright")
    if os.path.exists(ms_playwright_dir):
        cmd.extend(["--add-data", f"{ms_playwright_dir}{os.pathsep}ms-playwright"])

    cmd.extend([
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.async_api",
        "--hidden-import", "database",
        "--hidden-import", "scraper",
        "--hidden-import", "country_data",
        os.path.join(base_dir, "main.py")
    ])
    
    result = subprocess.run(cmd)
    return result.returncode == 0

def build_server(base_dir):
    print("\n🚀 Building LeadPulse Headless Server Binary (for Ubuntu VPS / Linux Servers)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name", "LeadPulse-Server",
        "--add-data", f"{os.path.join(base_dir, 'assets')}{os.pathsep}assets",
        "--add-data", f"{os.path.join(base_dir, 'config.env.example')}{os.pathsep}.",
        "--exclude-module", "PySide6",
        "--exclude-module", "shiboken6",
    ]

    ms_playwright_dir = os.path.join(base_dir, "ms-playwright")
    if os.path.exists(ms_playwright_dir):
        cmd.extend(["--add-data", f"{ms_playwright_dir}{os.pathsep}ms-playwright"])

    cmd.extend([
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.async_api",
        "--hidden-import", "database",
        "--hidden-import", "scraper",
        "--hidden-import", "country_data",
        os.path.join(base_dir, "main.py")
    ])
    
    result = subprocess.run(cmd)
    return result.returncode == 0

def main():
    parser = argparse.ArgumentParser(description="LeadPulse Enterprise Executable Builder")
    parser.add_argument("--server", action="store_true", help="Build Headless Server Binary (No GUI)")
    parser.add_argument("--gui", action="store_true", help="Build Graphical Desktop Executable")
    parser.add_argument("--all", action="store_true", help="Build both GUI and Headless Server binaries")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.server:
        build_server(base_dir)
    elif args.gui:
        build_gui(base_dir)
    else:
        build_server(base_dir)
        try:
            import PySide6
            build_gui(base_dir)
        except ImportError:
            print("PySide6 not installed, skipping GUI desktop build.")

if __name__ == "__main__":
    main()
