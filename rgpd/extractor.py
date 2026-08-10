import json
import random
import re
import subprocess
import time
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://www.enforcementtracker.com"

OUTPUT_FILE = "cms.json"
FAILED_FILE = "etid_failed.txt"

BRAVE_PATH = "/usr/bin/brave-browser"
CDP_URL = "http://127.0.0.1:9222"


def connect_browser (playwright):

    try:
        browser = playwright.chromium.connect_over_cdp (CDP_URL)
        print("Connected to Brave.")
        return browser, None

    except Exception:

        print("Could not connect to Brave.")
        print("Starting Brave...")
        brave_process = start_brave()

        for _ in range(10):
            try:
                browser = playwright.chromium.connect_over_cdp(CDP_URL)
                print("Connected to Brave.")
                return browser, brave_process

            except Exception:
                time.sleep(1)

        raise RuntimeError ("Unable to connect to Brave via CDP.")

def crawl (start_ETid, end_ETid):

    results = load_existing_json()
    existing = {item.get("etid") for item in results}
    if len (existing) > 0:
        print (f"{len(existing)} ETid already present in {OUTPUT_FILE}")

    with sync_playwright() as p:

        browser, brave_process = connect_browser(p)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = browser.new_context()

        page = (context.pages[0] if context.pages else context.new_page())
        page.set_default_timeout(60000)

        # Loop ETid
        for number in range (start_ETid, end_ETid+1):

            etid = f"ETid-{number}"
            if etid in existing:
                print (f"{etid}: already downloaded")
                continue
            else:
                print (f"Processing {etid}")
            # Load etid page
            result = download_etid (page, etid)

            # No more pages
            if result == "END":
                break
            
            # Success
            if result is not None:
                results.append(result)
                existing.add(etid)
                save_json(results)

            # Failure: etid has been saved in failed ones

            # Random pause for server consideration
            if number < end_ETid:
                delay = random.uniform (1, 3)
                time.sleep(delay)

        browser.close()
        if brave_process is not None:
            brave_process.terminate()
            brave_process.wait(timeout=5)

# Download page for one specific ETid
# Returns either:
#   "END" if page does not exist
#   None if error (challenge, server not responding...etc.)
#   Dictionary of ETid fields
def download_etid (page, etid):
    MAX_RETRY = 5
    url = f"{BASE_URL}/{etid}"

    success = False
    for attempt in range(MAX_RETRY):
        try:

            response = page.goto (url, wait_until="domcontentloaded", timeout=120000)
            status = response.status if response else None

            if status == 404:
                # No more pages
                return "END"

            if response:
                print(
                    f"{etid}: HTTP {response.status} "
                    f"{response.url}"
                )
            
            # Let Javascript finish its job
            page.wait_for_timeout(1500)
            if page_is_valid (page, etid):
                return extract_etid_data (page, etid)

            # Some unidentified problem: retry.
            print(f"{etid}: blocked/challenge or not found.")

        except PlaywrightTimeoutError:
            # Time out -> try again.
            print (f"{etid}: timeout")

        except Exception as e:
            if "ERR_HTTP2_PROTOCOL_ERROR" in str(e):
                # Protocol error -> try again.
                print(f"{etid}: HTTP/2 error " )
            else:
                # Some unidentified problem: stop there.
                print(f"{etid}: {type(e).__name__}: {e}")
                break

        wait = random.uniform(1, 5) * (attempt + 1)
        print(f"Waiting {wait:.1f}s before retry...Attempt: {attempt+1} / {MAX_RETRY}")
        time.sleep(wait)

    # Failure:
    print(f"Giving up page on ETid {etid} - url = {url}.")
    save_failed_etid (etid)
    return None



# Extract data for this etid
# Return dictionary
def extract_etid_data (page, etid):
    text = page.locator("body").inner_text()
    result = {"etid": etid, "url": page.url}

    # Clean text
    text = re.sub (r"[ \t]+", " ", text)

    # Get controller
    headings = page.locator ("h1").all_inner_texts()

    if headings:
        controller = (headings[0].strip())
        if controller:
            result["controller"] = controller

    # Get fine
    # Look for word EUR or symbol €.
    # to avoid JS:405000000.
    fine_match = re.search(
        r"(?:EUR|€)\s*([\d][\d.,]*)|"
        r"([\d][\d.,]*)\s*(?:EUR|€)",
        text,
        re.I)

    if fine_match:
        fine_string = (fine_match.group(1) or fine_match.group(2))

        # Remove comma separator:
        # 405,000,000 or 3,000 or 480
        fine_string = fine_string.replace (",", "")

        try:
            result["fine"] = int(fine_string)

        except ValueError:
            result["fine"] = fine_string

    # Search case details
    case_match = re.search(
        r"Case details\s+(.*?)(?="
        r"\s+(?:VIOLATION|TYPE OF VIOLATION|"
        r"QUOTED ARTICLES|SUMMARY|"
        r"ORIGINAL SOURCE|SOURCE)\b"
        r"|$)",
        text,
        re.I | re.S
    )

    if case_match:
        details = case_match.group(1).strip()

        # Get authority
        match = re.search (r"\bAUTHORITY\s+(.*?)\s+DATE\b", details,  re.I | re.S)
        if match:
            authority = re.sub (r"\s+",  " ", match.group(1)).strip()
            if authority:
                result["authority"] = authority

        # Get date
        match = re.search(r"\bDATE\s+(\d{4}-\d{2}-\d{2})\b", details, re.I)
        if match:
            result["date"] = match.group(1)

        # Get Controller / Processor
        match = re.search(
            r"\bCONTROLLER\s*/\s*PROCESSOR\s+(.*?)"
            r"\s+SECTOR\b",
            details,
            re.I | re.S
        )
        if match:
            controller_processor = re.sub(r"\s+", " ", match.group(1)).strip()
            if controller_processor:
                result["controller_processor"] = controller_processor

    # Get quoted articles

    match = re.search(
        r"\bQUOTED ARTICLES\s+(.*?)(?="
        r"\s+(?:TYPE OF VIOLATION|VIOLATION|"
        r"SUMMARY|ORIGINAL SOURCE|SOURCE)\b"
        r"|$)",
        text,
        re.I | re.S
    )
    if match:
        articles = re.sub (r"\s+", " ", match.group(1)).strip()
        if articles:
            result["quoted_articles"] = articles

    # Get summary
    match = re.search(
        r"\bSUMMARY\s+(.*?)(?="
        r"\s+(?:ORIGINAL SOURCE|SOURCE)\b"
        r"|$)",
        text,
        re.I | re.S
    )
    if match:
        summary = re.sub (r"\s+", " ", match.group(1)).strip()
        if summary:
            result["summary"] = summary

    return result


# If no json or error in reading json file: return empty list
# else return json content
def load_existing_json ():

    # No json file => nothing to do
    if not Path(OUTPUT_FILE).exists():
        return []

    try:
        with open (OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print (f"Unable to read {OUTPUT_FILE}: {e}")
        return []



# Page valid <=> contains a specific etid number
def page_is_valid (page, etid):
    expected = BASE_URL + f"/{etid}"
    if page.url.rstrip("/") != expected:
        # Wrong page
        return False 
    html = page.content()
    a = expected in html
    return expected in html



# Keep track of etid that can't be extracted.
# But make sure there is no duplicate
def save_failed_etid (etid):

    # Check for duplicate
    existing = set()
    if Path(FAILED_FILE).exists():
        with open (FAILED_FILE, "r", encoding="utf-8") as f:
            existing = {line.strip() for line in f if line.strip()}

    # New failed etid => add it
    if etid not in existing:
        with open (FAILED_FILE, "a", encoding="utf-8") as f:
            f.write(etid + "\n")


# Write data into temp file then replace official json file.
def save_json(data):
    tmp_file = OUTPUT_FILE + ".tmp"

    with open (tmp_file, "w", encoding="utf-8") as f:
        json.dump (data, f, ensure_ascii=False, indent=2)

    Path(tmp_file).replace(OUTPUT_FILE)




# Brave / Playwright
def start_brave():
    process = subprocess.Popen([
        BRAVE_PATH,
        "--remote-debugging-port=9222",
        "--user-data-dir=/tmp/brave-et",
        "--no-first-run",
        "--no-default-browser-check",
    ])

    print("Brave started.")
    time.sleep(3)
    return process


# Run: python extractor.py xx yy
# optional parameter xx = start ETid
# optional parameter yy = end  ETid
def main():
    start_ETid = 1
    end_ETid = 99999

    # Get parameters if any
    if len(sys.argv) >= 2:
        start_ETid = int(sys.argv[1])

    if len(sys.argv) >= 3:
         end_ETid = int(sys.argv[2])

    crawl (start_ETid, end_ETid)
    print (f"Results in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()