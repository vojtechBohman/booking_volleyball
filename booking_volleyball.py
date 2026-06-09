import os
import sys
import time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
# Importing stealth package to bypass Cloudflare
from playwright_stealth import stealth_sync

# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================
BASE_URL = "https://skodasportpark.isportsystem.cz/"
USERNAME = os.environ.get("BOOKING_USERNAME", "your_email@centrum.cz")
PASSWORD = os.environ.get("BOOKING_PASSWORD", "your_password")

TARGET_DATE = "2026-06-22"  
TIME_START = "17:30"       
TIME_END = "19:00"         
SPORT_TAB_ID = "7" 
# ==============================================================================

def generate_required_slots(start_str, end_str):
    start_dt = datetime.strptime(start_str, "%H:%M")
    end_dt = datetime.strptime(end_str, "%H:%M")
    slots = []
    current_dt = start_dt
    while current_dt < end_dt:
        next_dt = current_dt + timedelta(minutes=30)
        slot_string = f"{current_dt.strftime('%H:%M')}–{next_dt.strftime('%H:%M')}"
        slots.append(slot_string)
        current_dt = next_dt
    return slots

def execute_court_booking():
    required_slots = generate_required_slots(TIME_START, TIME_END)
    print(f"Required time blocks to secure: {required_slots}")

    with sync_playwright() as p:
        # Launching with stealth arguments to mask automation signatures
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--use-fake-ui-for-media-stream",
                "--window-size=1400,900"
            ]
        )
        
        # Defining a realistic modern User-Agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
            locale="cs-CZ",
            timezone_id="Europe/Prague"
        )
        
        page = context.new_page()
        # Activating the stealth scripts on the active page
        stealth_sync(page)

        try:
            print(f"Navigating to: {BASE_URL}")
            page.goto(BASE_URL, wait_until="commit")
            
            # Giving Cloudflare a small time window to validate the stealth profile
            page.wait_for_timeout(5000)
            
            # Check if we successfully bypassed Cloudflare and see the main site element
            page.wait_for_selector("#wrapper", timeout=20000)
            print("Page DOM loaded successfully, Cloudflare bypass achieved.")

            # 2. Handle Login
            if page.locator("#show_button").is_visible():
                print("Clicking login panel trigger...")
                page.click("#show_button a")
                page.wait_for_selector(".panelContent", state="visible", timeout=10000)
                
                print("Filling credentials...")
                page.fill("input[name='email'], input[type='email']", USERNAME)
                page.fill("input[name='password'], input[type='password']", PASSWORD)
                page.click("input[type='submit'], button:has-text('Přihlásit'), .panelContent button")
                
                page.wait_for_selector(".userLoggedName", state="visible", timeout=15000)
            
            print("Login check complete.")

            # 3. Calendar Date Selection
            target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
            target_day = str(target_dt.day)
            target_month_js = str(target_dt.month - 1)  
            target_year = str(target_dt.year)

            day_locator = page.locator(f"table.ui-datepicker-calendar td[data-month='{target_month_js}'][data-year='{target_year}'] a:text-is('{target_day}')")
            
            if not day_locator.is_visible():
                print("Target date not visible in current month view. Trying next month...")
                page.click("a.ui-datepicker-next")
                page.wait_for_timeout(1000)
                
            if day_locator.is_visible():
                print(f"Selecting date: {TARGET_DATE}")
                day_locator.click()
                page.wait_for_timeout(2000)
            else:
                raise Exception(f"Target date {TARGET_DATE} could not be selected.")

            # 4. Activate sports category tab
            print(f"Switching to sports tab ID: {SPORT_TAB_ID}")
            page.click(f"a.tab[id_sport='{SPORT_TAB_ID}']")
            page.wait_for_selector(f"table.schema_sport_{SPORT_TAB_ID}", state="visible")
            page.wait_for_timeout(2000) 

            # 5. Search for a free court
            grid_table_selector = f"table.schemaIndividual.schema_sport_{SPORT_TAB_ID}"
            rows = page.locator(f"{grid_table_selector} tbody tr").all()
            
            booking_anchors_to_click = []
            target_court_found = False

            print("Scanning rows for fully available consecutive blocks...")
            for row in rows:
                row_class = row.get_attribute("class") or ""
                if "trSchemaLane" not in row_class:
                    continue
                
                court_slots = []
                all_slots_free_on_this_court = True
                
                for slot in required_slots:
                    slot_locator = row.locator(f"a.empty[title^='{slot}']")
                    if slot_locator.count() > 0:
                        court_slots.append(slot_locator)
                    else:
                        all_slots_free_on_this_court = False
                        break
                
                if all_slots_free_on_this_court:
                    print(f"Success! Found a completely free court in row block: {row_class}")
                    booking_anchors_to_click = court_slots
                    target_court_found = True
                    break

            if not target_court_found:
                raise Exception(f"No court has a free continuous block from {TIME_START} to {TIME_END}.")

            # 6. Click slots into the basket
            print("Clicking all required time blocks into the basket...")
            for anchor in booking_anchors_to_click:
                anchor.click()
                page.wait_for_timeout(500) 

            # 7. Proceed to checkout summary
            print("Proceeding to reservation summary dialog...")
            page.click("a.showRecapDialog")
            page.wait_for_selector("#recapDialog", state="visible")

            # 8. Submit final order
            print("Submitting the final reservation form...")
            page.click("#formSubmitReservation p.buttonSubmit a")
            page.wait_for_timeout(3000)
            
            # 9. Verify success page state
            page.wait_for_selector("text=Rezervace byla úspěšně odeslána", timeout=10000)
            print("Success! Court reservation has been successfully placed.")
            return True

        except Exception as e:
            print(f"CRITICAL: Automation run failed: {e}", file=sys.stderr)
            page.screenshot(path="booking_failure_dump.png")
            print("Saved debug screenshot to booking_failure_dump.png", file=sys.stderr)
            return False
            
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    status = execute_court_booking()
    if not status:
        sys.exit(1)
