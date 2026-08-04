#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import re
import yaml
import time
import random
import subprocess
import os
import inspect
from bs4 import BeautifulSoup
from typing import Dict, Any
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError, Error

"""
Extraction of CNIL resolutions -> Text -> OUTUT_FOLDER
for further processing with LLM .

Note: the CNIL resolutions are published anonimized. The detail of each resolution is obtained by a link
      to the legifrance web site. That web site prevents crawling. So we need to
      - launch a separate browser (BRAVE) initially that will pass the challlenge
      - then use that browser to display the legifrance article
"""

# ----- CONFIGURATION -----
HEADERS = {"User-Agent": "Mozilla/5.0"}
YAML_FILE = "../sources.yaml"
OUTPUT_FOLDER = "extracts/"

def clean(text):
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def crawl (url, session):
    # Open URL containing table of CNIL sanctions in pure HTML
    html = fetch (url, session)

    soup = BeautifulSoup(html, "lxml")
    results = []

    # Extract info from table 
    for table in soup.find_all("table"):
        results.extend (parse_table(table))

    # Then we get all the links to Legifrance when available
    # to get the details of each decision
    brave_process = start_brave()

    with sync_playwright() as p:
        # Connect to the Brave already running
        browser = p.chromium.connect_over_cdp ("http://localhost:9222")
        context = browser.contexts[0]

        # Open Legifrance once to initialize the session
        page = context.new_page()

        # First page to validate the session and pass the challenge
        try:
            legifrance_url = "https://www.legifrance.gouv.fr/"
            page.goto (legifrance_url, wait_until="domcontentloaded", timeout=120000)
            print ("Browser ready:", page.title())
        finally:
            page.close()

        # Crawl decisions
        for r in results:
            url = r["decision_url"]
            if not url:
                continue
            print (f"URL: {url}")
            page = context.new_page ()

            try:
                for attempt in range(3):
                    try:
                        print(f"Attempt {attempt+1}", inspect.getfile(crawl))
                        page.goto (url, wait_until="domcontentloaded", timeout=120000)

                        # allow JS cleanup
                        page.wait_for_timeout(1000)
                        break

                    except TimeoutError:
                        print(f"Timeout ({attempt+1}/3) : {url}")

                        if attempt == 2:
                            raise
                        time.sleep (random.uniform(5, 10))
                    except Error as e:
                        print(f"Playwright error ({attempt+1}/3) : {e}")
						# Page died, recreate it
                        if page.is_closed():
                            page = context.new_page()

                        if attempt == 2:
                            raise
                        time.sleep (random.uniform(5, 10))

                html = page.content ()
                # Convert HTML to text
                soup = BeautifulSoup(html, "html.parser")
                text = soup.get_text("\n", strip=True)

                san = ""
                conclusion = ""
                # Get the resolution id
                m = re.search (r"Délibération\s+(SAN-\d{4}-\d{3})", text)
                if m:
                    san = m.group(1)

                # Get the company and fine
                m = re.search (r"PAR\s+CES\s+MOTIFS\s*(.*?)\s+Le Président", text, flags=re.DOTALL | re.IGNORECASE)
                if m:
                    conclusion = m.group(1).strip()

                if san != "" and conclusion != "":
                    output_file = OUTPUT_FOLDER + san + ".txt"

                    with open (output_file, "w", encoding="utf-8") as f:
                        f.write (f"Date: {r["date"]}\n")    
                        f.write (f"Summary: {r["decision_text"]}\n")    
                        f.write (f"Conclusion: \n {conclusion}")    

            finally:
            	# Close only the tab - not the browser
                if not page.is_closed():
                    page.close()
        # Disconnect Playwright only.
        # Do NOT browser.close() because Brave is external.


    # Optional: stop Brave when the crawl is finished
    brave_process.terminate()

def fetch(url, session, retries=3, timeout=20):
    for attempt in range(retries):
        try:
            r = session.get (url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text

        except Exception as e:
            print(f"HTTP error ({attempt+1}/{retries}): {e}")

            if attempt == retries - 1:
                raise

            time.sleep(1.5 * (attempt + 1))

"""
Parse the HTML from url being crawled, extracting data from tables
Note: column format changed in 2018 -> we use headers
"""
def parse_table(table):

    results = []
    headers = [
        clean(th.get_text()).lower()
        for th in table.find_all("th")
    ]

    # Detect from column headers
    old_format = ("thème" in headers)
    tbody = table.find("tbody")
    if tbody is None:
        return results

    prev_year = 0
    for row in tbody.find_all("tr", recursive=False):

        cells = row.find_all("td")
        if not cells:
            continue

        date_cell = cells[0]
        # Extract date

        date = clean (date_cell.get_text())
        m = re.search (r"(\d{4})$", date)
        if not m:
            continue

        year = int(m.group(1))
        if year != prev_year:
            print (f"Processing year: {year}")
            prev_year = year

        # Old format (< 2018)
        if old_format:
            if len(cells) < 5:
                continue

            decision_cell = cells[4]

        else:
          # New format > 2017
          # Must have 4 columns
            if len(cells) < 4:
                continue

            decision_cell = cells[3]


        # Sanction details are not available in this page but in
        # the link to Legifrance
        link = decision_cell.find("a")
        if link:
            decision_text = clean (link.get_text())
            decision_url = link.get ("href")
        else:
            decision_text = clean (decision_cell.get_text())
            decision_url = None

        results.append({
            "date": date,
            "decision_text": decision_text,
            "decision_url": decision_url

        })

    return results

"""
Launch Brave instance for Playwright with CDP protocol activated
Use a separate profile to avoid conflicts with the user's normal Brave.
"""
def start_brave():
    # Make sure only one Brave will be running
    subprocess.run (["pkill", "brave-browser"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    profile = "/tmp/brave-legifrance-profile"

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


def main():
    print("Running:", os.path.abspath(__file__))

    with open(YAML_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get the archive to be scraped
    data = config ["countries"]["FR"]
    archive = data ["archive"]
    authority = data ["authority"]

    session = requests.Session()
    print(f"Get {authority} resolutions ...")

    crawl (archive, session)
# ---------------------------------------------------------------------

if __name__ == "__main__":
    main()
