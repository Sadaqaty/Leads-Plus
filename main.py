import sys
import subprocess
import os
import argparse
import asyncio
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# Configure bundled Playwright browsers path if present in PyInstaller bundle and contains Chromium
bundled_browsers = get_resource_path("ms-playwright")
if os.path.exists(bundled_browsers):
    # Check if chromium browser folder exists inside bundled path
    has_chromium = any("chromium" in d for d in os.listdir(bundled_browsers)) if os.path.isdir(bundled_browsers) else False
    if has_chromium:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

def run_cli_mode(args):
    """Execute scraping in 100% headless Command Line Interface (CLI) server mode."""
    from scraper import MapsScraper, ensure_playwright_browsers
    from database import DatabaseManager

    if args.install_browsers:
        print("Installing Playwright Chromium browser binaries...")
        success = ensure_playwright_browsers()
        sys.exit(0 if success else 1)

    queries = []
    if args.query:
        queries.append(args.query.strip())

    if args.file:
        if os.path.exists(args.file):
            with open(args.file, "r", encoding="utf-8") as f:
                for line in f:
                    q = line.strip()
                    if q and not q.startswith("#"):
                        queries.append(q)
        else:
            print(f"❌ Error: Queries file not found at path: {args.file}")
            sys.exit(1)

    # Fallback to queries.txt in current directory if no query or file specified
    if not queries and os.path.exists("queries.txt") and not args.gui:
        print("ℹ️  No --query or --file specified. Reading queries from 'queries.txt'...")
        with open("queries.txt", "r", encoding="utf-8") as f:
            for line in f:
                q = line.strip()
                if q and not q.startswith("#"):
                    queries.append(q)

    if not queries:
        print("\n❌ Error: No search queries provided!")
        print("Usage examples:")
        print("  python main.py --query 'dentists in manchester'")
        print("  python main.py --file queries.txt --max-results 50 --output results.csv\n")
        sys.exit(1)

    output_path = args.output if args.output else "google_maps_leads.csv"
    headless = args.headless

    max_res_display = "UNLIMITED (Scrape until end of list)" if args.max_results <= 0 else args.max_results
    print("\n" + "=" * 75)
    print(" 🚀 LeadPulse Enterprise Extractor - Headless Server Mode")
    print("=" * 75)
    print(f" 📌 Total Queries to Extract : {len(queries)}")
    print(f" 🎯 Max Results per Query   : {max_res_display}")
    print(f" 🌐 Browser Execution       : {'HEADLESS (Server Mode)' if headless else 'VISIBLE UI'}")
    print(f" 💾 CSV Export Path         : {os.path.abspath(output_path)}")
    print("=" * 75 + "\n")

    # Ensure logs directory exists
    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Determine log filename based on query file or timestamp
    log_name = "scraper.log"
    if args.file:
        file_base = os.path.basename(args.file).replace(".", "_")
        log_name = f"worker_{file_base}.log"
    log_file_path = os.path.join(logs_dir, log_name)

    # Attach FileHandler to root logger for persistent disk logging
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
    logging.getLogger().addHandler(file_handler)
    logging.info(f"Logging activity to persistent disk log file: {log_file_path}")

    db = DatabaseManager()
    scraper = MapsScraper(proxy_list=args.proxy, proxy_file=args.proxy_file)
    total_extracted = 0

    async def cli_callback(item, meta):
        nonlocal total_extracted
        total_extracted += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = item.get("name", "N/A")
        cat = item.get("main_category", "N/A")
        phone = item.get("phone", "N/A")
        email = item.get("email", "N/A")
        website = item.get("website", "N/A")
        rating = item.get("rating", "0.0")
        reviews = item.get("reviews", "0")
        
        social_count = sum(1 for platform in ['facebook', 'instagram', 'linkedin', 'twitter', 'youtube'] if item.get(platform, "N/A") != "N/A")
        social_str = f" | 📲 {social_count} socials" if social_count > 0 else ""
        web_str = f" | 🌐 {website[:35]}" if website != "N/A" else ""
        cat_str = f" [{cat}]" if cat != "N/A" else ""
        
        print(f"[{now_str}] [{meta['current_count']}/{meta['max_results']}] Extracted: {name}{cat_str}{web_str} | 📞 {phone} | ✉️ {email}{social_str} | ⭐ {rating} ({reviews} rev)")

    target_query_file = args.file if args.file else ("queries.txt" if os.path.exists("queries.txt") else None)

    async def main_async():
        retry_count = 0
        while True:
            try:
                await scraper.scrape_maps(
                    queries,
                    total_results=args.max_results,
                    callback=cli_callback,
                    headless=headless,
                    proxy_list=args.proxy,
                    proxy_file=args.proxy_file,
                    no_proxy=getattr(args, 'no_proxy', False),
                    query_file=target_query_file
                )
                break
            except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                retry_count += 1
                logging.error(f"Uncaught exception in scraper loop (Attempt {retry_count}): {exc}", exc_info=True)
                print(f"\n⚠️ Unexpected error occurred: {exc}. Auto-restarting engine in 5 seconds...")
                await asyncio.sleep(5)
                if retry_count >= 10:
                    logging.critical("Max auto-restarts exceeded. Stopping worker loop.")
                    break

    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit):
        print("\n⚠️ Extraction stopped by user.")
    except Exception as e:
        print(f"\n⚠️ Extraction process finished with error: {e}")

    print("\n" + "=" * 75)
    print(f" ✅ Extraction Batch Completed! Total leads processed: {total_extracted}")
    exported = db.export_to_csv(output_path)
    if exported:
        print(f" 📁 All leads saved to CSV: {os.path.abspath(output_path)}")
    print("=" * 75 + "\n")
    print(f" 📌 Worker log file saved at: {log_file_path}")
    print(" ℹ️ Worker entering persistent idle mode to preserve tmux session logs...")
    
    # Keep tmux session alive so user can view logs anytime
    try:
        import time
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass

def main():
    parser = argparse.ArgumentParser(
        description="LeadPulse Enterprise Extractor - Headless CLI & Server Lead Generation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract a single query on Ubuntu VPS:
  python main.py --query "dentists in manchester" --max-results 50

  # Extract batch queries from a file headlessly:
  python main.py --file queries.txt --max-results 100 --output output/leads.csv

  # Install Playwright browser binaries on server:
  python main.py --install-browsers
"""
    )
    parser.add_argument("-q", "--query", type=str, help="Single Google Maps search query")
    parser.add_argument("-f", "--file", type=str, help="Path to text file containing queries (1 per line)")
    parser.add_argument("-m", "--max-results", type=int, default=0, help="Max leads to extract per query (default: 0 = UNLIMITED / Scrape until end of list)")
    parser.add_argument("-o", "--output", type=str, help="Output CSV export path")
    parser.add_argument("-p", "--proxy", type=str, help="Proxy URL or string (e.g. http://user:pass@ip:port or ip:port:user:pass)")
    parser.add_argument("--proxy-file", type=str, help="Path to file containing proxies (1 per line)")
    parser.add_argument("--no-proxy", "--direct", action="store_true", help="Disable proxies and connect directly using server IP")
    parser.add_argument("--cli", action="store_true", help="Force command line interface (CLI) mode")
    parser.add_argument("--gui", action="store_true", help="Force graphical user interface (GUI) mode")
    parser.add_argument("--no-headless", action="store_false", dest="headless", help="Disable headless mode (show browser)")
    parser.add_argument("--install-browsers", action="store_true", help="Install Playwright Chromium browser binaries")

    args = parser.parse_args()

    # If --install-browsers is set, execute install immediately
    if args.install_browsers:
        from scraper import ensure_playwright_browsers
        print("Installing Playwright Chromium browser binaries...")
        success = ensure_playwright_browsers()
        sys.exit(0 if success else 1)

    # Ensure virtual environment if running from source
    venv_python_1 = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")
    venv_python_2 = os.path.join(os.path.dirname(__file__), "venv", "bin", "python")
    venv_python = venv_python_1 if os.path.exists(venv_python_1) else (venv_python_2 if os.path.exists(venv_python_2) else None)
    
    if not getattr(sys, 'frozen', False) and venv_python and os.path.abspath(sys.executable) != os.path.abspath(venv_python):
        print(f"Relaunching in virtual environment ({venv_python})...")
        cmd = [venv_python, os.path.join(os.path.dirname(__file__), "main.py")] + sys.argv[1:]
        result = subprocess.run(cmd)
        sys.exit(result.returncode)

    # Determine whether to run CLI or GUI mode
    is_vps_headless = not os.environ.get("DISPLAY") and sys.platform.startswith("linux")
    has_cli_flags = bool(args.query or args.file or args.cli)

    if has_cli_flags or is_vps_headless or not args.gui:
        try:
            # Check if PySide6 can even be imported; if not or if CLI requested, run CLI
            if has_cli_flags or is_vps_headless:
                run_cli_mode(args)
                return
            import PySide6
        except ImportError:
            # PySide6 not installed (typical for headless server binaries/environments)
            run_cli_mode(args)
            return

    # If GUI is requested or default desktop environment with display server
    if args.gui or (os.environ.get("DISPLAY") or sys.platform in ["win32", "darwin"]):
        try:
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
        except Exception as gui_err:
            print(f"⚠️ Unable to initialize GUI display ({gui_err}). Falling back to Headless CLI Mode...")
            run_cli_mode(args)
    else:
        run_cli_mode(args)

if __name__ == "__main__":
    main()
