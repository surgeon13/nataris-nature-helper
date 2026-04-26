# ==========================================
#           NATARIS FARMLIST SENDER
#           One-shot farmlist send flow.
# ==========================================

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from helpers import BASE_URL, wait, info, ok, warn, err
import os


def save_captcha_enhanced(image_path):
    """
    Save a zoomed, high-contrast captcha helper image for manual reading.
    Returns path to enhanced image or None.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(image_path) as im:
            gray = ImageOps.autocontrast(im.convert("L"))
            up = gray.resize((gray.width * 4, gray.height * 4), Image.Resampling.NEAREST)
            bw = up.point(lambda p: 255 if p > 150 else 0)
            out_path = os.path.abspath("captcha_raid_zoom.png")
            bw.save(out_path)
        return out_path
    except Exception:
        return None


def render_captcha_ascii(image_path, width=96):
    """
    Render a high-contrast image into terminal-friendly ASCII.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(image_path) as im:
            gray = ImageOps.autocontrast(im.convert("L"))
            h = max(1, int((gray.height / max(1, gray.width)) * width * 0.45))
            small = gray.resize((width, h), Image.Resampling.NEAREST)
            pixels = list(small.getdata())

        # Light to dark ramp; we invert so dark letters look dense.
        ramp = " .,:;irsXA253hMHGS#9B&@"
        lines = []
        for y in range(h):
            row = pixels[y * width:(y + 1) * width]
            line = "".join(ramp[int((255 - p) * (len(ramp) - 1) / 255)] for p in row)
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return None


def run_farmlist_sender(driver, abort_flag, captcha_mode="manual_terminal", captcha_preview_size="medium"):
    """
    Farmlist sender (menu option 0).
    Flow:
    1) Open farmlist raid page (t=99) from dorf2 -> Rally Point
    2) Solve/fill captcha
    3) Select all farms
    4) Start raid
    """
    info("\n========== FARMLIST SENDER ==========")

    if abort_flag and abort_flag[0]:
        err("Aborted.")
        return

    def solve_and_fill_farmlist_captcha():
        try:
            captcha_input = driver.find_element(By.NAME, "captcha")
        except Exception:
            return True

        img_path = os.path.abspath("captcha_raid.png")
        while True:
            try:
                captcha_img = driver.find_element(By.ID, "captcha-image")
                try:
                    captcha_img.screenshot(img_path)
                except Exception:
                    driver.save_screenshot(img_path)
            except Exception:
                img_path = None

            ok(f"[Farmlist] Captcha detected. Read it manually from: {img_path or 'captcha image unavailable'}")
            if img_path and os.path.exists(img_path):
                enhanced = save_captcha_enhanced(img_path)
                if enhanced:
                    ok(f"[Farmlist] Enhanced captcha image: {enhanced}")
                    size_key = str(captcha_preview_size).strip().lower()
                    width_map = {"small": 72, "medium": 96, "large": 132}
                    preview_width = width_map.get(size_key, 96)
                    ascii_preview = render_captcha_ascii(enhanced, width=preview_width)
                    if ascii_preview:
                        print("\n[Farmlist] Terminal captcha preview:\n")
                        print(ascii_preview)
                        print()
                    else:
                        warn("[Farmlist] Could not render terminal preview; use captcha_raid_zoom.png.")

            if str(captcha_mode).strip().lower() == "auto":
                warn("[Farmlist] Auto mode is not available here; using manual terminal input.")

            solved_value = input("Enter captcha code (r to refresh, empty to abort): ").strip()

            if not solved_value:
                warn("[Farmlist] No captcha value entered.")
                return False

            if solved_value.lower() in ("r", "refresh"):
                try:
                    refresh_btn = driver.find_element(By.CSS_SELECTOR, ".fl-captcha-refresh")
                    refresh_btn.click()
                    wait()
                except Exception:
                    pass
                continue

            try:
                captcha_input.clear()
                captcha_input.send_keys(str(solved_value).strip())
                return True
            except Exception as e:
                err(f"[Farmlist] Could not fill captcha input: {e}")
                return False

    def open_farmlist_page():
        """
        Open Rally Point -> Farmlist page using the exact in-game click flow:
        dorf2 -> Rally Point (id=39) -> textmenu Farmlist (t=99).
        """
        try:
            driver.get(BASE_URL + "dorf2.php")
            wait()

            # Click rally point area on dorf2 map
            try:
                rally_area = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "area[href*='build.php?id=39'][title*='Rally Point']")
                    )
                )
                try:
                    rally_area.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", rally_area)
                wait()
            except Exception:
                # Fallback: direct overview URL
                driver.get(BASE_URL + "build.php?id=39")
                wait()

            # Click Farmlist in text menu
            try:
                farmlist_link = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "#textmenu a[href*='build.php?id=39'][href*='t=99']")
                    )
                )
                try:
                    farmlist_link.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", farmlist_link)
                wait()
            except Exception:
                # Fallback: direct farmlist URL
                driver.get(BASE_URL + "build.php?id=39&t=99")
                wait()

            cur = (driver.current_url or "").lower()
            if "t=99" in cur:
                return True

            if (
                driver.find_elements(By.ID, "raidListMarkAll")
                or driver.find_elements(By.ID, "start-raid-btn")
                or driver.find_elements(By.NAME, "action_start_raid")
                or driver.find_elements(By.NAME, "captcha")
            ):
                return True
            return False
        except Exception:
            return False

    if not open_farmlist_page():
        err("[Farmlist] Could not open farmlist page (t=99).")
        return

    if not solve_and_fill_farmlist_captcha():
        return

    try:
        mark_all = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.ID, "raidListMarkAll"))
        )
        if not mark_all.is_selected():
            mark_all.click()
    except Exception as e:
        err(f"[Farmlist] Could not select all farms: {e}")
        return

    started = False
    try:
        WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.ID, "start-raid-btn"))
        ).click()
        started = True
    except Exception:
        try:
            WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.NAME, "action_start_raid"))
            ).click()
            started = True
        except Exception as e:
            err(f"[Farmlist] Could not click Start Raid: {e}")
            return

    if started:
        wait()
        ok("[Farmlist] Start Raid submitted.")
