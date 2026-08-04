import requests
import fitz
import re
import yaml
import time
import subprocess
import sys
import os
import random
from bs4 import BeautifulSoup
from typing import Dict, Any
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
#from urllib.parse import urlencode
from urllib.parse import quote

"""
Extraction of AED fines -> Text -> OUTUT_FOLDER
for further processing with LLM .

This program crawls the AEPD resolution archive and extracts all available sanction decisions.
It builds the archive URLs, downloads each results page, and parses the HTML content with BeautifulSoup.
For each page, it identifies the PDF links corresponding to individual decisions.
The program downloads the PDF documents and extracts their text content.
It processes the extracted text to retrieve relevant information such as dates, identifiers, and conclusions.
The results are saved locally for further analysis.

Note: some pages have a challenge from anti-bot Akamai, In case the program can't read them, it
saves the page number in skipped_pages.txt
Later on (try to reach a skipped page with a browser first) the program can be re-run: python extractor.py xxx xxx
where xxx is one of the skipped page.
"""

# ----- CONFIGURATION -----
HEADERS = {"User-Agent": "Mozilla/5.0"}
YAML_FILE = "../sources.yaml"
OUTPUT_FOLDER = "extracts/"

COOKIE_FILE = "aepd_cookies.json"


"""
The url of the page needs to be built this way.
Adding page=xxx at the end does not work
"""
def build_aepd_url(page):
    value = quote(
        "tipo_procedimiento:Procedimiento Sancionador (PS)",
        safe=""
    )

    return (
        "https://www.aepd.es/informes-y-resoluciones/resoluciones"
        f"?f%5B0%5D={value}&page={page}"
    )

def page_is_valid(html):

    soup = BeautifulSoup (html, "html.parser")
    articles = soup.find_all("article")

    return len(articles) > 0

def get_aepd_session (test_url):
    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    })

    try:
        r = session.get (test_url, timeout=60)

        if page_is_valid(r.text):
            print("AEPD accessible")
            return session

        print("AEPD challenge detected.")

    except:
        print (f"test_url:\n{test_url}")
        raise Exception("AEPD inaccessible - check URL construction")


def crawl (base_url, start_page_nb = 0, end_page_nb = None):
    test_url = build_aepd_url(start_page_nb)

    session = get_aepd_session (test_url)
    if session is None:
        print (f"test_url invalid for page {start_page_nb}")
        print (test_url) 
        print (f"Program terminated.")
        return       

    page_nb = start_page_nb
    skipped_pages = []

    while True:

        # Stop if requested
        if (end_page_nb is not None and page_nb > end_page_nb):
            print("Last requested page reached.")
            break

        # Recreate the HTTP session every 25 pages
        if page_nb != start_page_nb and page_nb % 25 == 0:
            print("\nRecreating HTTP session...\n")
            session.close()
            session = requests.Session()
            session.headers.update(HEADERS)

        # Build URL
        aepd_url = build_aepd_url (page_nb)

        success = False
        # Trying to get to the page which could be challenged
        for attempt in range(5):

            try:
                print(f"\nPage {page_nb} (attempt {attempt+1})")
                r = session.get(aepd_url, timeout=120)
                r.raise_for_status()

                if page_is_valid(r.text):
                    success = True
                    break

                print(f"Challenge detected. (HTML size={len(r.text)})")

            except requests.RequestException as e:
                print(f"HTTP error: {e}")

            wait = random.uniform(1, 5) * (attempt + 1)
            print(f"Waiting {wait:.1f}s before retry...")
            time.sleep(wait)

        if not success:
            print(f"Giving up page {page_nb}.")
            print(f"r.status_code = {r.status_code}")
            print(f"r.url = {r.url}")
            print(f"r.headers.get('Server') = {r.headers.get('Server')}")
            print(f"r.headers.get('Set-Cookie') = {r.headers.get('Set-Cookie')}")
            print(f"r.headers.get('Retry-After') = {r.headers.get('Retry-After')}")

            skipped_pages.append(page_nb)

            with open("skipped_pages.txt", "a", encoding="utf-8") as f:
                f.write(f"{page_nb}\n")
            page_nb += 1
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        pdfs = extract_pdf_links(soup, aepd_url)

        if not pdfs:
            print("No more pages to crawl.")
            break

        print(f"{len(pdfs)} PDF(s) found.")

        for p in pdfs:
            pdf_content = download_pdf( p["url"], session)
            doc = fitz.open (stream=pdf_content, filetype="pdf")
            # Extract around word "euros"
            extracts = extract_euro_context(doc, window=5)
            #    snippets = extract_snippets (one_pdf)
            print (f"page #:{page_nb} from crawled url - document id:: {p["id"]} ")
            output_file = OUTPUT_FOLDER + p["id"] + ".txt"
            with open (output_file, "w", encoding="utf-8") as f:
                f.write (f"Date: {p["date"]}\n")    
                f.write (f"Conclusion: \n {extracts}")    

        page_nb += 1

        # Random delay between pages to fool Akamai (challenge)
        time.sleep(random.uniform(3, 8))

"""
Download one pdf - returns the content
"""
def download_pdf(pdf_url, session):

    r = session.get(pdf_url, timeout=120)
    r.raise_for_status()

    return r.content

"""
Extract the links of each pdf in a given page
"""
def extract_pdf_links (soup, page_url):

    pdfs = []
    for article in soup.find_all("article"):

        href = article.find ("a", href=lambda h: h and h.lower().endswith(".pdf"))
        fecha_de_firma = article.find ("time", class_="datetime")
        if href:
            pdfs.append(
                {
                    "url": urljoin (page_url, href["href"]),
                    "id": href.get_text (strip=True),
                    "date": fecha_de_firma["datetime"][:10] if fecha_de_firma else None
                }
            )

    return pdfs

def extract_euro_context(doc, window=2, keyword_pattern=r"euros|€"):

    # 1. Flatten all lines in document order
    all_lines = []
    for page in doc:
        text = page.get_text("text")
        all_lines.extend(text.split("\n"))

    n = len(all_lines)
    pattern = re.compile(keyword_pattern, re.IGNORECASE)

    # 2. Find lines containing the keyword/symbol
    match_indices = [i for i, line in enumerate(all_lines) if pattern.search(line)]
    if not match_indices:
        return []

    # 3. Build inclusive window around each match (window lines each side)
    ranges = []
    for idx in match_indices:
        start = max(0, idx - window)
        end = min(n - 1, idx + window)
        ranges.append((start, end))

    # 4. Merge overlapping/adjacent windows
    ranges.sort()
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        last = merged[-1]
        if start <= last[1] + 1:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])

    # 5. Build final text blocks (match lines included)
    extracts = [all_lines[start:end + 1] for start, end in merged]

    return extracts

"""
Launch Brave instance for Playwright with CDP protocol activated
Use a separate profile to avoid conflicts with the user's normal Brave.
That was used in a debug phase...
"""
def start_brave():
    # Make sure only one Brave will be running
    subprocess.run (["pkill", "brave-browser"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    profile = "/tmp/brave-aepd-profile"

    proc = subprocess.Popen([
        "brave-browser",
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check"
    ])

    # Wait until the remote debugging port is available
    for i in range(30):
        try:
            r = requests.get ("http://127.0.0.1:9222/json/version", timeout=1)

            if r.status_code == 200:
                print("Brave CDP ready")
                return proc

        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

    raise RuntimeError ("Brave did not start remote debugging")


# Run: python extractor.py xx yy
# optional parameter xx = start page
# optional parameter yy = end  page
def main():
    with open(YAML_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get the archive to be scraped
    data = config ["countries"]["ES"]
    archive = data ["archive"]
    authority = data ["authority"]

    start_page_nb = 0
    end_page_nb = None

    # Get parameters if any
    if len(sys.argv) >= 2:
        start_page_nb = int(sys.argv[1])

    if len(sys.argv) >= 3:
        end_page_nb = int(sys.argv[2])

    print(f"Get {authority} resolutions - from page {start_page_nb} to {end_page_nb}...")

  
    crawl(archive, start_page_nb, end_page_nb)

#---------------------------------------------------------------------

if __name__ == "__main__":
    main()