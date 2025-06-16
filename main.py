import json
import math
import re
import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
import requests
import sqlite3

# Constants
COOKIE_FILE = Path("cookiefile.json")
XSRF_FILE = Path("xsrf_token.txt")
DB_PATH = "jobs_data.db"
job_title = "head of engineering"
TARGET_PAGE = (
    "https://europa.eu/eures/portal/jv-se/search?"
    "page=1&resultsPerPage=10&orderBy=BEST_MATCH"
    "&locationCodes=be,dk,fi,mt,nl,no,se,ch,ee"
    f"&keywordsEverywhere={job_title.replace(' ', '%20')}"
    "&positionScheduleCodes=fulltime"
    "&sector=NS,j,k"
    "&positionOfferingCodes=NS,directhire"
    "&publicationPeriod=LAST_WEEK"
    "&escoIsco=C11,C12,C133,C242,C243,C25,C35"
    "&requiredLanguages=en(C2)&lang=en"
)

# Database setup
def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            creationDate TEXT,
            lastModificationDate TEXT,
            title TEXT,
            description TEXT,
            numberOfPosts INTEGER,
            locationMap TEXT,
            euresFlag TEXT,
            jobCategoriesCodes TEXT,
            positionScheduleCodes TEXT,
            positionOfferingCode TEXT,
            employer TEXT,
            availableLanguages TEXT,
            score REAL,
            details TEXT
        )
    """)
    conn.commit()
    return conn

# Cookie management
def load_stored_cookie() -> str | None:
    if COOKIE_FILE.exists():
        try:
            return json.load(COOKIE_FILE.open("r", encoding="utf-8")).get("Cookie")
        except Exception:
            return None
    return None

def save_cookie(cookie_value: str, xsrf_token: str):
    cookie_value += f"; XSRF-TOKEN={xsrf_token}"
    json.dump({"Cookie": cookie_value}, COOKIE_FILE.open("w", encoding="utf-8"), indent=2)

def load_xsrf_token() -> str | None:
    if XSRF_FILE.exists():
        try:
            return XSRF_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return None

def save_xsrf_token(token: str):
    XSRF_FILE.write_text(token.strip(), encoding="utf-8")

def extract_cookies_from_logs(logs: list[dict]) -> tuple[str, str]:
    session_id = xsrf_token = None
    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg.get("method") != "Network.responseReceivedExtraInfo":
                continue

            headers = msg.get("params", {}).get("headers", {})
            set_cookie = headers.get("Set-Cookie")
            if not set_cookie:
                continue

            cookies = set_cookie.split("\n") if isinstance(set_cookie, str) else set_cookie
            for c in cookies:
                if "EURES_JVSE_SESSIONID=" in c:
                    session_id = re.search(r"EURES_JVSE_SESSIONID=([^;]+)", c).group(1)
                if "XSRF-TOKEN=" in c:
                    xsrf_token = re.search(r"XSRF-TOKEN=([^;]+)", c).group(1)

            if session_id and xsrf_token:
                break
        except Exception:
            continue

    if not session_id or not xsrf_token:
        raise RuntimeError("Required cookies not found")

    return f"EURES_JVSE_SESSIONID={session_id}", xsrf_token

def obtain_cookies_via_selenium() -> tuple[str, str]:
    chrome_opts = Options()
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-gpu")
    chrome_opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(service=ChromeService(), options=chrome_opts)
    try:
        driver.get(TARGET_PAGE)
        time.sleep(7)
        logs = driver.get_log("performance")
        return extract_cookies_from_logs(logs)
    finally:
        driver.quit()

def reload_cookie() -> tuple[str, str]:
    cookie_header, xsrf_token = obtain_cookies_via_selenium()
    save_cookie(cookie_header, xsrf_token)
    save_xsrf_token(xsrf_token)
    return cookie_header, xsrf_token

# API handling
def make_api_request(cookie: str, xsrf_token: str, page: int = 1) -> tuple[dict, str, str]:
    url = "https://europa.eu/eures/eures-apps/searchengine/page/jv-search/search"
    payload = json.dumps({
        "resultsPerPage": 50,
        "page": page,
        "sortSearch": "BEST_MATCH",
        "keywords": [{"keyword": job_title, "specificSearchCode": "EVERYWHERE"}],
        "publicationPeriod": "LAST_WEEK",
        "occupationUris": [f"http://data.europa.eu/esco/isco/{code}" for code in ["C11", "C12", "C133", "C242", "C243", "C25", "C35"]],
        "positionScheduleCodes": ["fulltime"],
        "sectorCodes": ["NS", "j", "k"],
        "positionOfferingCodes": ["NS", "directhire"],
        "locationCodes": ["be", "ch", "dk", "fi", "mt", "nl", "no", "se"],
        "requiredLanguages": [{"isoCode": "en", "level": "C2"}]
    })

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": xsrf_token,
        "Origin": "https://europa.eu",
        "Referer": TARGET_PAGE,
        "Cookie": cookie
    }

    response = requests.post(url, headers=headers, data=payload)

    if response.status_code == 403:
        print("⚠️ Token expired. Reloading cookies...")
        cookie, xsrf_token = reload_cookie()
        return make_api_request(cookie, xsrf_token, page)

    return response.json(), cookie, xsrf_token

def get_job_details(job_id: str, cookie: str, xsrf_token: str) -> dict | None:
    url = f"https://europa.eu/eures/eures-apps/searchengine/page/jv/id/{job_id}?lang=en"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "X-XSRF-TOKEN": xsrf_token,
        "Referer": f"https://europa.eu/eures/portal/jv-se/jv-details/{job_id}?lang=en",
        "Cookie": cookie
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 403:
        print(f"⚠️ Access denied for job ID {job_id}. Retrying with refreshed cookie...")
        cookie, xsrf_token = reload_cookie()
        return get_job_details(job_id, cookie, xsrf_token)

    return response.json() if response.ok else None

# Core function
def handle_pagination(cookie: str, xsrf_token: str, conn):
    results = []
    page = 1

    response, cookie, xsrf_token = make_api_request(cookie, xsrf_token, page)
    total = response.get("numberRecords", 0)
    total_pages = (total + 49) // 50
    print(f"📄 Total records: {total} across {total_pages} pages.\n")

    cursor = conn.cursor()

    for page in range(1, total_pages + 1):
        print(f"➡️ Fetching page {page}...")
        response, cookie, xsrf_token = make_api_request(cookie, xsrf_token, page)
        jobs = response.get("jvs", [])

        for job in jobs:
            job_data = {
                "id": job.get("id"),
                "creationDate": job.get("creationDate"),
                "lastModificationDate": job.get("lastModificationDate"),
                "title": job.get("title"),
                "description": job.get("description"),
                "numberOfPosts": job.get("numberOfPosts"),
                "locationMap": json.dumps(job.get("locationMap")),
                "euresFlag": job.get("euresFlag"),
                "jobCategoriesCodes": json.dumps(job.get("jobCategoriesCodes")),
                "positionScheduleCodes": json.dumps(job.get("positionScheduleCodes")),
                "positionOfferingCode": job.get("positionOfferingCode"),
                "employer": json.dumps(job.get("employer")),
                "availableLanguages": json.dumps(job.get("availableLanguages")),
                "score": job.get("score"),
                "details": json.dumps(get_job_details(job.get("id"), cookie, xsrf_token))
            }

            cursor.execute("""
                INSERT OR REPLACE INTO jobs (
                    id, creationDate, lastModificationDate, title, description,
                    numberOfPosts, locationMap, euresFlag, jobCategoriesCodes,
                    positionScheduleCodes, positionOfferingCode, employer,
                    availableLanguages, score, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tuple(job_data.values()))

        conn.commit()
        results.extend(jobs)
        time.sleep(1)

    return results

# Entry point
def main():
    conn = setup_database()
    cookie = load_stored_cookie()
    xsrf_token = load_xsrf_token()

    if not cookie or not xsrf_token:
        print("🔄 Cookie not found. Fetching new one...")
        cookie, xsrf_token = reload_cookie()

    jobs = handle_pagination(cookie, xsrf_token, conn)
    print(f"\n✅ Fetched and saved {len(jobs)} job entries.")
    conn.close()

if __name__ == "__main__":
    main()
