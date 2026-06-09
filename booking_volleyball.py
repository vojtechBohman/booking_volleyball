import os
import sys
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# ==============================================================================
# CONFIGURATION CONSTANTS
# ==============================================================================
BASE_URL = "https://skodasportpark.isportsystem.cz/"
USERNAME = os.environ.get("BOOKING_USERNAME", "vojtech.bohman@centrum.cz")
PASSWORD = os.environ.get("BOOKING_PASSWORD", "your_password")

TARGET_DATE = "2026-06-22"  # Format: YYYY-MM-DD
TIME_START = "10:30"       # Format: HH:MM
TIME_END = "12:00"         # Format: HH:MM
SPORT_TAB_ID = "7"         # ID for "Hřiště - míčové hry"
# ==============================================================================

def generate_required_slots(start_str, end_str):
    """Generates 30-minute interval strings using the system's exact en-dash character."""
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

async def execute_court_booking():
    required_slots = generate_required_slots(TIME_START, TIME_END)
    print(f"Required time blocks to secure: {required_slots}")

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1400, "height": 900},
            locale="cs-CZ",
            timezone_id="Europe/Prague"
        )
        page = await context.new_page()

        try:
            print(f"Navigating to: {BASE_URL}")
            await page.goto(BASE_URL)
            
            # --- 1. LOGIN FLOW ---
            print("Waiting for login button trigger (#show_button)...")
            await page.wait_for_selector("#show_button", timeout=15000)
            print("Clicking login button...")
            await page.click("#show_button a")
            
            # Small pause to allow the login form container to expand
            await page.wait_for_timeout(1000)
            
            print("Filling credentials...")
            await page.fill("input[type='email'], input[name='email']", USERNAME)
            await page.fill("input[type='password']", PASSWORD)
            
            print("Submitting login form via userLoginSubmit...")
            # FIXED: Targeting the exact class provided from the HTML source
            await page.click("a.userLoginSubmit")
            
            # Confirm successful login by waiting for the sign-out link or logged-in class
            await page.wait_for_selector("a:has-text('Odhlásit'), .loggedIn", timeout=15000)
            print("Login successful.")

            # --- 2. SELECT SPORT CATEGORY ---
            print(f"Selecting sports category tab (id_sport='{SPORT_TAB_ID}')...")
            sport_tab_selector = f"a.tab[id_sport='{SPORT_TAB_ID}']"
            await page.wait_for_selector(sport_tab_selector, timeout=10000)
            await page.click(sport_tab_selector)
            
            # --- 3. CALENDAR DATE SELECTION ---
            target_dt = datetime.strptime(TARGET_DATE, "%Y-%m-%d")
            target_day = str(target_dt.day)
            target_month_js = str(target_dt.month - 1)  # jQuery UI calendar months are 0-indexed
            target_year = str(target_dt.year)

            print(f"Selecting target date: {TARGET_DATE}")
            day_locator = page.locator(f"table.ui-datepicker-calendar td[data-month='{target_month_js}'][data-year='{target_year}'] a:text-is('{target_day}')")
            
            if not await day_locator.is_visible():
                print("Target date not visible, checking next month...")
                await page.click("a.ui-datepicker-next")
                await page.wait_for_timeout(1000)
                
            await day_locator.click()
            await page.wait_for_timeout(2000) # Wait for the schedule table to redraw over Ajax

            # --- 4. SCAN GRID AND BOOK THE COURT ---
            grid_table_selector = f"table.schemaIndividual.schema_sport_{SPORT_TAB_ID}"
            await page.wait_for_selector(grid_table_selector, timeout=10000)
            rows = await page.locator(f"{grid_table_selector} tbody tr").all()
            
            booking_anchors_to_click = []
            target_court_found = False

            print("Scanning court rows for consecutive free blocks...")
            for row in rows:
                row_class = await row.get_attribute("class") or ""
                if "trSchemaLane" not in row_class:
                    continue
                
                court_slots = []
                all_slots_free_on_this_court = True
                
                for slot in required_slots:
                    slot_locator = row.locator(f"a.empty[title^='{slot}']")
                    if await slot_locator.count() > 0:
                        court_slots.append(slot_locator)
                    else:
                        all_slots_free_on_this_court = False
                        break
                
                if all_slots_free_on_this_court:
                    print(f"Found ideal free court row: {row_class}")
                    booking_anchors_to_click = court_slots
                    target_court_found = True
                    break

            if not target_court_found:
                raise Exception(f"No court available with a continuous free block from {TIME_START} to {TIME_END}.")

            print("Clicking slots into the booking basket...")
            for anchor in booking_anchors_to_click:
                await anchor.click()
                await page.wait_for_timeout(500) 

            # --- 5. CONFIRMATION STEPS ---
            print("Clicking continue button ('Pokračovat')...")
            await page.click("a.showRecapDialog")
            await page.wait_for_selector("#recapDialog", state="visible")

            print("Submitting the final reservation form...")
            await page.click("#formSubmitReservation p.buttonSubmit a")
            await page.wait_for_timeout(3000)
            
            # Final success message verification
            await page.wait_for_selector("text=Rezervace byla úspěšně odeslána", timeout=10000)
            print("Success! Court has been successfully booked.")
            return True

        except Exception as e:
            print(f"CRITICAL: Automation run failed: {e}", file=sys.stderr)
            await page.screenshot(path="booking_failure_dump.png")
            print("Saved failure dump screenshot.", file=sys.stderr)
            return False
            
        finally:
            await browser.close()

if __name__ == "__main__":
    success = asyncio.run(execute_court_booking())
    if not success:
        sys.exit(1)
