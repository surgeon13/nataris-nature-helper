# ==========================================
#           NATARIS LOGIN BOT
#           Main entry point for the bot.
#           Handles login, main menu, and
#           coordinates all scripts.
#           Smart login - skips if already
#           logged in, retries up to 3 times.
#           Scheduler runs in background thread.
#           Checks scheduler flags every menu loop.
# ==========================================

import time
import random
import threading
import signal
import subprocess
import platform
import importlib
import importlib.util
import os
import tempfile
import shutil
import json
import sys


def ensure_core_dependencies():
    """
    Ensure core runtime dependencies are available before importing bot modules.
    """
    missing = []
    if importlib.util.find_spec("selenium") is None:
        missing.append("selenium")
    if importlib.util.find_spec("webdriver_manager") is None:
        missing.append("webdriver-manager")
    if not missing:
        return
    print(f"[BOOT] Installing missing dependencies: {', '.join(missing)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_core_dependencies()

from accounts import accounts, MIN_WAIT, MAX_WAIT
from village_builder_engine import run_build_logic
from resource_upgrader import run_resource_upgrade
from template_loader import run_template_loader
from multi_village_builder import run_multi_village_builder
from resource_sender import run_resource_sender
from farmlist_sender import run_farmlist_sender
from destroyer import run_destroyer
from village_checkup import run_village_checkup
from scheduler import start_scheduler, check_flags, schedule_checkup, stop_scheduler
from helpers import get_all_villages, red, yellow, green, cyan, blue, bold, info, ok, warn, err, status
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ==========================================
#           HOT RELOAD SYSTEM
# ==========================================

import village_builder_engine
import resource_upgrader
import template_loader
import multi_village_builder
import resource_sender
import farmlist_sender
import destroyer
import village_checkup
import scheduler
import helpers

# Modules to monitor for changes
RELOADABLE_MODULES = [
    village_builder_engine,
    resource_upgrader,
    template_loader,
    multi_village_builder,
    resource_sender,
    farmlist_sender,
    destroyer,
    village_checkup,
    scheduler,
    helpers,
]

# Track last modification time of each module
module_mtimes = {}

def check_and_reload_modules():
    """
    Checks if any reloadable modules have been modified on disk.
    If modified, reloads them automatically.
    Returns list of reloaded module names for logging.
    """
    reloaded = []
    
    for module in RELOADABLE_MODULES:
        try:
            module_file = module.__file__
            if not module_file or not os.path.exists(module_file):
                continue
            
            current_mtime = os.path.getmtime(module_file)
            module_name = module.__name__
            
            # First time seeing this module
            if module_name not in module_mtimes:
                module_mtimes[module_name] = current_mtime
                continue
            
            # File was modified
            if current_mtime > module_mtimes[module_name]:
                try:
                    importlib.reload(module)
                    module_mtimes[module_name] = current_mtime
                    reloaded.append(module_name)
                except Exception as e:
                    err(f"Failed to reload {module_name}: {e}")
        
        except Exception as e:
            pass  # Skip any modules that can't be checked
    
    # Re-import functions from reloaded modules so bot uses updated code
    if reloaded:
        try:
            global run_build_logic, run_resource_upgrade, run_template_loader
            global run_multi_village_builder, run_resource_sender, run_farmlist_sender, run_destroyer, run_village_checkup
            from village_builder_engine import run_build_logic
            from resource_upgrader import run_resource_upgrade
            from template_loader import run_template_loader
            from multi_village_builder import run_multi_village_builder
            from resource_sender import run_resource_sender
            from farmlist_sender import run_farmlist_sender
            from destroyer import run_destroyer
            from village_checkup import run_village_checkup
        except Exception as e:
            err(f"Warning: Could not re-import functions after reload: {e}")
    
    return reloaded

USERNAME = accounts[0]["username"]
PASSWORD = accounts[0]["password"]
TRIBE    = accounts[0]["tribe"]
GAME_URL = "https://project-nataris.com/"
LOGIN_URL = "https://project-nataris.com/login.php"
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "bot_settings.json")


def load_bot_settings():
    """
    Loads persisted runtime settings from disk.
    Falls back to sane defaults when file is missing/corrupt.
    """
    defaults = {
        "use_gold": True,
        "batch_autocomplete": False,
        "send_threshold": 0,
        "round_robin_queue_actions": 2,
        "res_send_close_distance": 15,
        "res_send_donor_full_pct": 85,
        "res_send_topup_target_pct": 90,
        "headless_mode": False,
        "farmlist_captcha_mode": "manual_terminal",
        "farmlist_captcha_preview_size": "medium",
    }
    if not os.path.exists(SETTINGS_FILE):
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        out = dict(defaults)
        for key in defaults:
            if key in data:
                out[key] = data[key]
        # Basic clamping/sanitization
        out["send_threshold"] = int(out.get("send_threshold", 0))
        if out["send_threshold"] < 0:
            out["send_threshold"] = 0
        if out["send_threshold"] > 90:
            out["send_threshold"] = 90
        out["round_robin_queue_actions"] = int(out.get("round_robin_queue_actions", 2))
        if out["round_robin_queue_actions"] < 1:
            out["round_robin_queue_actions"] = 1
        if out["round_robin_queue_actions"] > 2:
            out["round_robin_queue_actions"] = 2
        out["res_send_close_distance"] = int(out.get("res_send_close_distance", 15))
        if out["res_send_close_distance"] < 1:
            out["res_send_close_distance"] = 1
        if out["res_send_close_distance"] > 100:
            out["res_send_close_distance"] = 100
        out["res_send_donor_full_pct"] = int(out.get("res_send_donor_full_pct", 85))
        if out["res_send_donor_full_pct"] < 50:
            out["res_send_donor_full_pct"] = 50
        if out["res_send_donor_full_pct"] > 99:
            out["res_send_donor_full_pct"] = 99
        out["res_send_topup_target_pct"] = int(out.get("res_send_topup_target_pct", 90))
        if out["res_send_topup_target_pct"] < 60:
            out["res_send_topup_target_pct"] = 60
        if out["res_send_topup_target_pct"] > 100:
            out["res_send_topup_target_pct"] = 100
        out["use_gold"] = bool(out.get("use_gold", True))
        out["batch_autocomplete"] = bool(out.get("batch_autocomplete", False))
        out["headless_mode"] = bool(out.get("headless_mode", False))
        mode = str(out.get("farmlist_captcha_mode", "manual_terminal")).strip().lower()
        if mode not in ("manual_terminal", "auto"):
            mode = "manual_terminal"
        out["farmlist_captcha_mode"] = mode
        preview_size = str(out.get("farmlist_captcha_preview_size", "medium")).strip().lower()
        if preview_size not in ("small", "medium", "large"):
            preview_size = "medium"
        out["farmlist_captcha_preview_size"] = preview_size
        return out
    except Exception:
        return defaults


def save_bot_settings(settings):
    """
    Saves runtime settings to disk so they persist across bot restarts.
    """
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        warn(f"Could not save settings: {e}")


def ensure_dependency(module_name, pip_package=None, feature_name=None):
    """
    Ensures an optional runtime dependency is installed.
    Returns True if available after check/install, False otherwise.
    """
    try:
        import importlib.util
        if importlib.util.find_spec(module_name):
            return True
    except Exception:
        pass

    pkg = pip_package or module_name
    feature = feature_name or module_name
    warn(f"Missing optional dependency '{pkg}' for {feature}. Installing automatically...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
    except Exception as e:
        warn(f"Auto-install failed for '{pkg}': {e}")
        warn(f"Feature '{feature}' will run in fallback mode.")
        return False

    try:
        import importlib.util
        if importlib.util.find_spec(module_name):
            ok(f"Installed optional dependency '{pkg}' successfully.")
            return True
    except Exception:
        pass

    warn(f"Dependency '{pkg}' still not available after install.")
    return False

# Global abort flag shared across all scripts
abort_flag = [False]

# Module-level driver reference so KeyboardInterrupt can close Chrome cleanly
_driver = None
_bot_profile_dir = None

# ==========================================
#           SIGNAL HANDLING
# ==========================================

def cleanup_chrome():
    """
    Gracefully closes the Selenium-controlled Chrome browser.
    Only closes the bot's window, NOT all Chrome processes.
    Called on Ctrl+C or abnormal exit.
    """
    global _driver, _bot_profile_dir
    if _driver:
        try:
            _driver.quit()
            ok("Browser closed gracefully.")
        except Exception as e:
            warn(f"Could not close browser: {e}")
        finally:
            _driver = None
    else:
        ok("No active browser to close.")

    if _bot_profile_dir:
        try:
            shutil.rmtree(_bot_profile_dir, ignore_errors=True)
        except Exception as e:
            warn(f"Could not remove temp Chrome profile: {e}")
        finally:
            _bot_profile_dir = None


_last_ctrl_c = [0]
_force_exiting = [False]

def signal_handler(signum, frame):
    """
    Handles Ctrl+C:
      - First press: sets abort flag -> scripts stop at next checkpoint -> returns to menu.
      - Second press within 3 seconds: force-exits and closes Chrome.
    """
    if _force_exiting[0]:
        return

    now = time.time()
    if now - _last_ctrl_c[0] < 3:
        _force_exiting[0] = True
        err("\n\n[!] Double Ctrl+C - force exit.")
        try:
            stop_scheduler()
        except Exception:
            pass
        cleanup_chrome()
        # Hard exit avoids lingering output from in-flight round-robin/checkup work.
        os._exit(0)

    _last_ctrl_c[0] = now
    abort_flag[0] = True
    warn("\n[!] Ctrl+C - aborting to main menu... (press again quickly to force-exit)")

# Attach signal handler for Ctrl+C
signal.signal(signal.SIGINT, signal_handler)

# ==========================================
#           HELPERS
# ==========================================

def wait_interruptible(seconds):
    """
    Waits for a given number of seconds.
    User can press any key at any time to skip the wait early.
    Uses msvcrt.kbhit() on Windows so no thread consumes stdin —
    the main menu's input() always gets the first keypress cleanly.
    """
    warn(f"Waiting {round(seconds)} seconds... (press any key to skip)")
    import msvcrt
    start = time.time()
    while time.time() - start < seconds:
        if msvcrt.kbhit():
            msvcrt.getch()  # consume the keypress without passing it to stdin
            ok("Wait skipped!")
            return
        time.sleep(0.1)

def is_logged_in(driver):
    """
    Checks if already logged in by looking for logout link.
    Returns True if logged in, False if not.
    """
    try:
        driver.find_element(By.CSS_SELECTOR, "a[href='logout.php']")
        return True
    except Exception:
        return False


def is_session_lost_error(e, driver=None):
    """
    Returns True when an exception indicates the underlying Chrome/WebDriver
    session is gone and the caller should restart Chrome instead of retrying
    commands on the same driver instance.
    """
    try:
        e_str = str(e).lower()
    except Exception:
        e_str = ""

    lost = (
        "disconnected" in e_str
        or "detached" in e_str
        or "window was closed" in e_str
        or "invalid session id" in e_str
        or "no such window" in e_str
        or "no such session" in e_str
    )

    if lost:
        return True
    if driver is not None and not is_driver_alive(driver):
        return True
    return False


def open_game_home(driver, retries=3):
    """
    Opens the game homepage with retries and verification.
    Returns True once the browser is confirmed on project-nataris.com.
    """
    for attempt in range(1, retries + 1):
        if not is_driver_alive(driver):
            return False
        try:
            driver.set_page_load_timeout(40)
            driver.get(GAME_URL)
            time.sleep(2)
            current = (driver.current_url or "").lower()
            if "project-nataris.com" in current:
                return True

            # Try the login page directly if the homepage no longer redirects.
            driver.get(LOGIN_URL)
            time.sleep(2)
            current = (driver.current_url or "").lower()
            if "project-nataris.com" in current:
                return True

            # Fallback in case navigation got stuck on about:blank/new tab.
            driver.execute_script(f"window.location.href='{LOGIN_URL}'")
            time.sleep(2)
            current = (driver.current_url or "").lower()
            if "project-nataris.com" in current:
                return True
        except Exception as e:
            warn(f"Open URL attempt {attempt}/{retries} failed: {e}")
            if is_session_lost_error(e, driver=driver):
                return False
        time.sleep(1)
    return False

# ==========================================
#           LOGIN
# ==========================================

def attempt_login(driver, wait):
    """
    Attempts to log in up to 3 times.
    Clears input fields before typing to avoid double input
    from browser autofill or previous session data.
    Returns True if login successful, False if all attempts fail.
    """
    max_attempts = 3

    def _try_click(css_selector, timeout=6):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector))
            )
            el.click()
            return True
        except Exception:
            try:
                el = driver.find_element(By.CSS_SELECTOR, css_selector)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:
                return False

    def _find_first_visible(css_selectors, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            for sel in css_selectors:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed() and el.is_enabled():
                        return el
                except Exception:
                    pass
            time.sleep(0.2)
        raise TimeoutException(f"Timed out waiting for a visible element: {css_selectors}")

    def _type_into_css(css_selectors, text, timeout=15):
        el = _find_first_visible(css_selectors, timeout=timeout)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        except Exception:
            pass
        try:
            el.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass
        try:
            el.clear()
        except Exception:
            pass
        # Some inputs don't clear reliably; force select-all delete.
        try:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
        except Exception:
            pass
        el.send_keys(text)
        return el

    for attempt in range(1, max_attempts + 1):
        err(f"Login attempt {attempt} of {max_attempts}...")

        try:
            # Step 1 - Open the login page or server list.
            current = (driver.current_url or "").lower()
            if "login.php" not in current:
                # Prefer the direct Login nav link (current UI).
                if _try_click("a.btn-login-nav[href*='login.php']") or _try_click("a.btn-login-nav"):
                    time.sleep(3)
                    print("Login page opened")
                # Fallback: some layouts show a server-list/login button first.
                elif _try_click("button.btn-login"):
                    time.sleep(3)
                    print("Server list opened")
                else:
                    raise Exception("Could not find a login navigation control")

            # Best-effort: close common cookie/consent overlays if they exist.
            _try_click("button#onetrust-accept-btn-handler", timeout=2)
            _try_click("button[aria-label*='accept' i]", timeout=2)

            # Step 2 - Select server if present.
            try:
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn-login"))).click()
                time.sleep(3)
                print("Server selected")
            except TimeoutException:
                print("No server selector found; continuing to login form")

            # Step 3 - Fill in credentials
            # Always clear first to avoid double input from autofill
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

            _type_into_css(
                [
                    "input#user",
                    "input[name='user']",
                    "input[name='username']",
                    "input[autocomplete='username']",
                    "input[placeholder*='user' i]",
                ],
                USERNAME,
                timeout=20,
            )
            time.sleep(1)

            _type_into_css(
                [
                    "input#pw",
                    "input[name='pw']",
                    "input[name='password']",
                    "input[type='password']",
                    "input[autocomplete='current-password']",
                ],
                PASSWORD,
                timeout=20,
            )
            time.sleep(1)

            # Click login; prefer normal click but fall back to JS click if an overlay blocks it.
            try:
                btn = _find_first_visible(["#btn_login", "button#btn_login", "button[type='submit']", "input[type='submit']"], timeout=15)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                btn.click()
            except Exception:
                btn = _find_first_visible(["#btn_login", "button#btn_login", "button[type='submit']", "input[type='submit']"], timeout=15)
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)

            try:
                driver.switch_to.default_content()
            except Exception:
                pass

            if is_logged_in(driver):
                ok("Logged in successfully!")
                return True
            else:
                err(f"Login attempt {attempt} failed - wrong credentials or server issue.")

        except Exception as e:
            msg = getattr(e, "msg", None)
            if msg:
                err(f"Login attempt {attempt} failed with {type(e).__name__}: {msg}")
            else:
                err(f"Login attempt {attempt} failed with {type(e).__name__}: {e!r}")
            try:
                err(f"Debug: url={driver.current_url!r} title={driver.title!r}")
            except Exception:
                pass

        if attempt < max_attempts:
            warn("Retrying in 5 seconds...")
            time.sleep(5)
            if not open_game_home(driver):
                err("Could not open game homepage during login retry.")
                return False
            time.sleep(3)

    err("All login attempts failed - shutting down.")
    return False

# ==========================================
#           MAIN BOT
# ==========================================

def kill_stale_bot_processes():
    """
    Kills any chromedriver.exe processes left over from a previous crash.
    Also kills chrome.exe instances that are holding the bot profile directory.
    Only runs on Windows. Safe to call even when no stale processes exist.
    """
    if platform.system() != "Windows":
        return
    for proc_name in ("chromedriver.exe",):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    # Give the OS a moment to release file locks on the profile directory
    time.sleep(1)


def start_chrome(headless_mode=False):
    """
    Kills any stale chromedriver process, then starts a fresh Chrome instance.
    Uses a temporary profile directory per launch to avoid any profile lock
    collisions after crashes or with normal user Chrome windows.
    Uses Selenium Manager (built into Selenium 4.6+) to auto-manage ChromeDriver.
    chromedriver is started in its own process group so Ctrl+C in the console
    does not broadcast CTRL_C_EVENT to Chrome/chromedriver.
    headless_mode: True -> run Chrome without visible UI.
    """
    global _bot_profile_dir
    kill_stale_bot_processes()
    last_error = None

    # Try multiple launch profiles from safest to most defensive.
    launch_profiles = [
        {
            "name": "default",
            "extra_args": [],
        },
        {
            "name": "pipe+gpu-fallback",
            "extra_args": [
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-features=RendererCodeIntegrity",
            ],
        },
        {
            "name": "sandbox-fallback",
            "extra_args": [
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-features=RendererCodeIntegrity",
                "--no-sandbox",
            ],
        },
    ]

    for attempt, profile in enumerate(launch_profiles, start=1):
        info(f"Chrome startup attempt {attempt}/{len(launch_profiles)} ({profile['name']})...")
        if _bot_profile_dir:
            shutil.rmtree(_bot_profile_dir, ignore_errors=True)
            _bot_profile_dir = None

        _bot_profile_dir = tempfile.mkdtemp(prefix="nataris_chrome_")

        options = Options()
        options.add_argument(f"--user-data-dir={_bot_profile_dir}")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-component-update")
        options.add_argument("--disable-domain-reliability")
        options.add_argument("--disable-features=MediaRouter")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-pings")
        options.add_argument("--disable-notifications")
        # Pipe mode avoids localhost DevTools polling failures on some Windows setups.
        options.add_argument("--remote-debugging-pipe")
        if headless_mode:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")
        for arg in profile["extra_args"]:
            options.add_argument(arg)

        # Prefer stable Chrome install path when present.
        chrome_path = os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Google", "Chrome", "Application", "chrome.exe")
        if os.path.exists(chrome_path):
            options.binary_location = chrome_path

        # Selenium Manager auto-downloads the correct ChromeDriver - no webdriver-manager needed
        service = Service()
        # Windows: isolate chromedriver from CTRL_C_EVENT broadcast by the console.
        # Without this, every Ctrl+C kills Chrome even though the signal handler
        # only sets abort_flag.
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            service.creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            driver = webdriver.Chrome(service=service, options=options)
            wait   = WebDriverWait(driver, 10)
            return driver, wait
        except Exception as e:
            last_error = e
            warn(f"Chrome startup attempt {attempt} failed: {e}")
            # Clean this attempt profile and try the next launch profile.
            shutil.rmtree(_bot_profile_dir, ignore_errors=True)
            _bot_profile_dir = None
            time.sleep(1)

    raise last_error

def is_driver_alive(driver):
    """
    Checks if Chrome is still running and responsive.
    Returns False if the browser has crashed or been closed.
    """
    try:
        _ = driver.window_handles
        return True
    except Exception:
        return False

def login():
    """
    Main bot function.
    Handles startup settings, opens Chrome,
    logs in only if needed, starts scheduler,
    and runs the main menu loop indefinitely.
    Automatically recovers from Chrome crashes by restarting
    the browser and re-logging in without asking for settings again.
    Exits when user selects Q or presses Ctrl+C.
    """
    info("========== NATARIS BOT SETTINGS ==========")

    # Optional dependency for terminal captcha image preview in farmlist mode.
    ensure_dependency("PIL", pip_package="Pillow", feature_name="farmlist captcha terminal preview")

    min_wait       = 1    # minutes - change in accounts.py if needed
    max_wait       = 2    # minutes
    saved = load_bot_settings()
    use_gold       = saved.get("use_gold", True)
    batch_autocomplete = saved.get("batch_autocomplete", False)
    master_builder     = False
    send_threshold     = saved.get("send_threshold", 0)  # % of warehouse to keep before sending
    round_robin_queue_actions = saved.get("round_robin_queue_actions", 2)
    res_send_close_distance = saved.get("res_send_close_distance", 15)
    res_send_donor_full_pct = saved.get("res_send_donor_full_pct", 85)
    res_send_topup_target_pct = saved.get("res_send_topup_target_pct", 90)
    headless_mode      = saved.get("headless_mode", False)
    farmlist_captcha_mode = saved.get("farmlist_captcha_mode", "manual_terminal")
    farmlist_captcha_preview_size = saved.get("farmlist_captcha_preview_size", "medium")

    def persist_runtime_settings():
        save_bot_settings({
            "use_gold": use_gold,
            "batch_autocomplete": batch_autocomplete,
            "send_threshold": send_threshold,
            "round_robin_queue_actions": round_robin_queue_actions,
            "res_send_close_distance": res_send_close_distance,
            "res_send_donor_full_pct": res_send_donor_full_pct,
            "res_send_topup_target_pct": res_send_topup_target_pct,
            "headless_mode": headless_mode,
            "farmlist_captcha_mode": farmlist_captcha_mode,
            "farmlist_captcha_preview_size": farmlist_captcha_preview_size,
        })

    ok(f"Gold autocomplete: {'ON' if use_gold else 'OFF'}")
    info("==========================================\n")

    # Start scheduler once - survives Chrome restarts
    start_scheduler()
    schedule_checkup(60)

    # Outer loop handles Chrome crash recovery
    while True:
        ok("Starting Nataris Login Bot...")
        driver, wait = start_chrome(headless_mode=headless_mode)
        global _driver
        _driver = driver

        # Navigate to game
        if not open_game_home(driver):
            err("Could not open game homepage. Restarting Chrome...")
            cleanup_chrome()
            time.sleep(3)
            continue
        ok("Page loaded")

        # Smart login - skip if already logged in
        if is_logged_in(driver):
            warn("Already logged in - skipping login!")
        else:
            ok("Not logged in - attempting login...")
            if not attempt_login(driver, wait):
                driver.quit()
                return

        ok("Chrome running - entering main menu.")

        # Inner loop - main menu, exits on crash or user exit
        user_exit = False
        while True:
            # Check if Chrome is still alive before every menu loop
            if not is_driver_alive(driver):
                err("\n[!] Chrome crashed or was closed - restarting in 5 seconds...")
                time.sleep(5)
                break  # Break inner loop -> outer loop restarts Chrome

            abort_flag[0] = False
            master_builder = False

            # Check and reload modified modules (hot reload)
            reloaded = check_and_reload_modules()
            if reloaded:
                ok(f"🔄 Reloaded: {', '.join(reloaded)}")

            # Check scheduler flags before every menu display
            try:
                check_flags(driver, abort_flag)
            except KeyboardInterrupt:
                raise
            except Exception:
                err("\n[!] Chrome lost during scheduler check - restarting...")
                time.sleep(5)
                break

            gold_tag = green("ON  (autocomplete enabled)") if use_gold else red("OFF (manual only)")
            headless_tag = green("YES") if headless_mode else yellow("NO")
            print(f"\n{'─'*48}")
            print(f"  {bold(cyan('NATARIS BOT [1.01]'))}  │  Gold: {gold_tag}")
            print(f"  Send threshold: {send_threshold}% of warehouse kept before sending")
            print(f"  Round-robin queue cap: {round_robin_queue_actions} action(s) per village pass")
            print(
                f"  ResSend tune: close<= {res_send_close_distance} fields, "
                f"donor full>= {res_send_donor_full_pct}%, top-up target {res_send_topup_target_pct}%"
            )
            print(f"  Headless mode: {headless_tag}")
            print(f"{'─'*48}")
            print(f"  {blue('[0]')} Farmlist send")
            print(f"  {blue('[1]')} Build village (template)")
            print(f"  {blue('[2]')} Upgrade resource fields")
            print(f"  {blue('[3]')} Build all villages (round-robin)")
            print(f"  {blue('[4]')} Demolish buildings")
            print(f"  {blue('[5]')} Send resources between villages")
            print(f"  {blue('[6]')} Village checkup & analysis")
            print(f"  {yellow('[S]')} Settings")
            print(f"{'─'*48}")
            print(f"  {blue('[I]')} Idle / wait   {red('[Q]')} Quit bot")
            print(f"{'─'*48}")
            choice = input(f"  Choice: ").strip().lower()
            restart_browser = False

            try:
                if choice == "0":
                    run_farmlist_sender(
                        driver,
                        abort_flag,
                        captcha_mode=farmlist_captcha_mode,
                        captcha_preview_size=farmlist_captcha_preview_size,
                    )
                elif choice == "i":
                    wait_time = random.uniform(min_wait * 60, max_wait * 60)
                    wait_interruptible(wait_time)
                elif choice == "1":
                    # Only JSON template build is supported now
                    run_template_loader(driver, use_gold, abort_flag, TRIBE)
                elif choice == "2":
                    run_resource_upgrade(driver, use_gold, batch_autocomplete, master_builder, abort_flag, send_threshold, tribe=TRIBE)
                elif choice == "3":
                    run_multi_village_builder(
                        driver,
                        use_gold,
                        abort_flag,
                        TRIBE,
                        max_queue_actions_per_pass=round_robin_queue_actions,
                    )
                    master_builder = False
                elif choice == "4":
                    run_destroyer(driver, abort_flag)
                elif choice == "5":
                    run_resource_sender(driver, abort_flag)
                elif choice == "6":
                    villages = get_all_villages(driver)
                    run_village_checkup(driver, villages)
                elif choice == "s":
                    # Settings submenu
                    while True:
                        print(f"\n  {cyan('[SETTINGS MENU]')}")
                        print(f"    {yellow('1')}  Gold autocomplete: {green('ON') if use_gold else red('OFF')} (toggle)")
                        print(f"    {yellow('2')}  Batch autocomplete: {green('ON') if batch_autocomplete else red('OFF')} (toggle)")
                        print(f"    {yellow('3')}  Master builder: {green('READY') if not master_builder else yellow('ACTIVE')} (next run only)")
                        print(f"    {yellow('4')}  Set resource send threshold (current: {send_threshold}%)")
                        print(f"    {yellow('5')}  Round-robin queue actions per village pass (current: {round_robin_queue_actions})")
                        print(f"    {yellow('6')}  ResSend close donor distance (current: {res_send_close_distance} fields)")
                        print(f"    {yellow('7')}  ResSend donor full threshold (current: {res_send_donor_full_pct}%)")
                        print(f"    {yellow('8')}  ResSend top-up target (current: {res_send_topup_target_pct}%)")
                        print(f"    {yellow('9')}  Headless mode: {green('YES') if headless_mode else red('NO')} (toggle)")
                        print(f"    {yellow('10')} Farmlist captcha mode: {green('MANUAL') if farmlist_captcha_mode == 'manual_terminal' else yellow('AUTO')} (toggle)")
                        print(f"    {yellow('11')} Farmlist preview size: {cyan(farmlist_captcha_preview_size.upper())} (toggle)")
                        print(f"    {red('B')}  Back to main menu")
                        sub_choice = input(f"\nChoose a settings option: ").strip().lower()
                        if sub_choice == "1":
                            use_gold = not use_gold
                            ok(f"Gold autocomplete is now {green('ON') if use_gold else red('OFF')}")
                            persist_runtime_settings()
                        elif sub_choice == "2":
                            batch_autocomplete = not batch_autocomplete
                            ok(f"Batch autocomplete is now {green('ON') if batch_autocomplete else red('OFF')}")
                            persist_runtime_settings()
                        elif sub_choice == "3":
                            master_builder = True
                            ok("Master builder ACTIVE for next run (auto-resets after)")
                        elif sub_choice == "4":
                            while True:
                                try:
                                    val = input(f"Keep what % of warehouse before sending? (0-90) [current: {send_threshold}%]: ").strip()
                                    val = int(val) if val else send_threshold
                                    if 0 <= val <= 90:
                                        send_threshold = val
                                        ok(f"Send threshold set to {send_threshold}%")
                                        persist_runtime_settings()
                                        break
                                    else:
                                        warn("Please enter a value between 0 and 90.")
                                except ValueError:
                                    warn("Invalid input - please enter a number.")
                        elif sub_choice == "5":
                            while True:
                                try:
                                    val = input(
                                        f"Round-robin queue actions per village pass? (1-2) [current: {round_robin_queue_actions}]: "
                                    ).strip()
                                    val = int(val) if val else round_robin_queue_actions
                                    if 1 <= val <= 2:
                                        round_robin_queue_actions = val
                                        ok(f"Round-robin queue actions set to {round_robin_queue_actions}")
                                        persist_runtime_settings()
                                        break
                                    else:
                                        warn("Please enter 1 or 2.")
                                except ValueError:
                                    warn("Invalid input - please enter a number.")
                        elif sub_choice == "6":
                            while True:
                                try:
                                    val = input(
                                        f"Close donor distance in fields? (1-100) [current: {res_send_close_distance}]: "
                                    ).strip()
                                    val = int(val) if val else res_send_close_distance
                                    if 1 <= val <= 100:
                                        res_send_close_distance = val
                                        ok(f"ResSend close donor distance set to {res_send_close_distance} fields")
                                        persist_runtime_settings()
                                        break
                                    else:
                                        warn("Please enter a value between 1 and 100.")
                                except ValueError:
                                    warn("Invalid input - please enter a number.")
                        elif sub_choice == "7":
                            while True:
                                try:
                                    val = input(
                                        f"Donor full threshold %? (50-99) [current: {res_send_donor_full_pct}%]: "
                                    ).strip()
                                    val = int(val) if val else res_send_donor_full_pct
                                    if 50 <= val <= 99:
                                        res_send_donor_full_pct = val
                                        ok(f"ResSend donor full threshold set to {res_send_donor_full_pct}%")
                                        persist_runtime_settings()
                                        break
                                    else:
                                        warn("Please enter a value between 50 and 99.")
                                except ValueError:
                                    warn("Invalid input - please enter a number.")
                        elif sub_choice == "8":
                            while True:
                                try:
                                    val = input(
                                        f"Top-up target % for close+full donors? (60-100) [current: {res_send_topup_target_pct}%]: "
                                    ).strip()
                                    val = int(val) if val else res_send_topup_target_pct
                                    if 60 <= val <= 100:
                                        res_send_topup_target_pct = val
                                        ok(f"ResSend top-up target set to {res_send_topup_target_pct}%")
                                        persist_runtime_settings()
                                        break
                                    else:
                                        warn("Please enter a value between 60 and 100.")
                                except ValueError:
                                    warn("Invalid input - please enter a number.")
                        elif sub_choice == "9":
                            headless_mode = not headless_mode
                            persist_runtime_settings()
                            ok(f"Headless mode is now {green('YES') if headless_mode else red('NO')}.")
                            warn("Restarting Chrome now so headless change takes effect...")
                            restart_browser = True
                            break
                        elif sub_choice == "10":
                            farmlist_captcha_mode = "auto" if farmlist_captcha_mode == "manual_terminal" else "manual_terminal"
                            persist_runtime_settings()
                            if farmlist_captcha_mode == "manual_terminal":
                                ok("Farmlist captcha mode is now MANUAL (terminal input).")
                            else:
                                ok("Farmlist captcha mode is now AUTO (falls back to manual if unavailable).")
                        elif sub_choice == "11":
                            order = ["small", "medium", "large"]
                            try:
                                idx = order.index(farmlist_captcha_preview_size)
                            except Exception:
                                idx = 1
                            farmlist_captcha_preview_size = order[(idx + 1) % len(order)]
                            persist_runtime_settings()
                            ok(f"Farmlist captcha preview size is now {farmlist_captcha_preview_size.upper()}.")
                        elif sub_choice == "b":
                            break
                        else:
                            warn("Invalid option, please try again.")
                    if restart_browser:
                        cleanup_chrome()
                        time.sleep(1)
                        break
                elif choice == "x":
                    abort_flag[0] = True
                    err("Abort flag set - will stop at next checkpoint.")
                elif choice == "q":
                    err("Shutting down bot...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    user_exit = True
                    break
                else:
                    err("Invalid option, please try again.")

            except Exception as e:
                e_str = str(e).lower()
                is_chrome_dead = (
                    "disconnected" in e_str
                    or "detached" in e_str
                    or "window was closed" in e_str
                    or "invalid session id" in e_str
                    or "no such window" in e_str
                    or "no such session" in e_str
                    or not is_driver_alive(driver)
                )
                if is_chrome_dead:
                    err(f"\n[!] Chrome session lost: {e}")
                    err("[!] Restarting Chrome in 5 seconds...")
                    time.sleep(5)
                    break
                else:
                    err(f"Error: {e}")

        if user_exit:
            cleanup_chrome()
            break

# ==========================================
#           ENTRY POINT
# ==========================================

try:
    login()
except KeyboardInterrupt:
    err("\nBot stopped by user (Ctrl+C).")
    cleanup_chrome()
except SystemExit:
    pass
except Exception as e:
    err(f"\nBot crashed: {e}")
    cleanup_chrome()
