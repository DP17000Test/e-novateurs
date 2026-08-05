#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import re
import yaml
import time
import json
import os
from bs4 import BeautifulSoup
from typing import Dict, Any

"""
Extraction of DPC resolutions -> json file

Note: the DPC resolutions (fines) are directy available on the url.
"""

# ----- CONFIGURATION -----
HEADERS = {"User-Agent": "Mozilla/5.0"}
YAML_FILE = "../sources.yaml"
OUTPUT_FOLDER = "extracts/"

def clean(text):
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def crawl (url, session, authority, country):
    # Open URL containing table of DPC sanctions in pure HTML
    html = fetch (url, session)

    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    results = []


    for tr in table.find_all("tr")[1:]:      # skip header
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) == 5:
            results.append({
            "source": authority,
            "country": country,
            "resolution": cells[2],
            "company": cells[1],
            "amount": parse_fine (cells[3]),
            "currency": "euros",
            "date": cells[0],
            "status": cells[4]
        })

    return results


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

def parse_fine(text):
    text = text.strip()

    m = re.search(r'€\s*([\d,]+)', text)
    if not m:
        return None

    return int(m.group(1).replace(",", ""))

def main():
    print("Running:", os.path.abspath(__file__))

    with open(YAML_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get the archive to be scraped
    data = config ["countries"]["IE"]
    archive = data ["archive"]
    authority = data ["authority"]
    country = data["country"]
    json_file = authority.lower() + ".json"

    session = requests.Session()
    print(f"Get {authority} resolutions ...")

    results = crawl (archive, session, authority, country)
    if results:
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
# ---------------------------------------------------------------------

if __name__ == "__main__":
    main()
