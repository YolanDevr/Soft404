import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import os
import re
import time
from io import BytesIO
import zipfile
from selenium.webdriver.support.ui import WebDriverWait
from urllib.parse import urlparse

# --- Streamlit UI setup ---
st.set_page_config(page_title="Broken Page Checker", layout="wide")
st.title("🔍 Broken Page & Soft 404 Checker")

uploaded_file = st.file_uploader("Upload hier je lijst met URL's (CSV of Excel)", type=["csv", "xlsx"])

# --- Parameters ---
TEXT_LENGTH_THRESHOLD = 200
HERO_IMAGE_SIZE_THRESHOLD = 500 * 1024  # 500 KB
os.makedirs("screenshots", exist_ok=True)

# --- Hulpfuncties ---
def slugify(text):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)

def suggest_redirect(url):
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) > 1:
        new_path = "/".join(path_parts[:-1])
        return f"{parsed.scheme}://{parsed.netloc}/{new_path}/"
    else:
        return f"{parsed.scheme}://{parsed.netloc}/"

def setup_browser():
    chrome_options = Options()
    chrome_options.binary_location = "/usr/lib/chromium/chromium"  # ✅ Correct pad op Streamlit Cloud
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')

    return webdriver.Chrome(options=chrome_options)


# --- Check functies ---
def has_large_images(soup):
    images = soup.find_all("img")
    for img in images:
        src = img.get("src") or ""
        if any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return True
    return False

def contains_soft_404_indicators(text):
    indicators = [
        "page not found", "not found", "404", "error 404", "could not find", "no longer exists",
        "pagina niet gevonden", "bestaat niet meer", "niet beschikbaar", "niet gevonden", "oops",
        "sorry er ging iets mis", "deze pagina heeft pootjes gekregen", "page n'existe plus", "cette page est introuvable"
    ]
    return any(indicator in text.lower() for indicator in indicators)

def check_url(driver, url):
    try:
        driver.get(url)
        WebDriverWait(driver, 5).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        body_text = soup.get_text(separator=" ", strip=True)
        text_length = len(body_text)
        has_h1 = bool(soup.find("h1"))
        has_footer = bool(soup.find("footer"))

        if text_length > 500 and has_large_images(soup):
            return {
                "url": url,
                "status": "200",
                "text_length": text_length,
                "reason": "Grote hero-afbeelding gedetecteerd, uitgesloten van check",
                "has_h1": has_h1,
                "has_footer": has_footer,
                "screenshot": "",
                "advice": "👍 Pagina bevat grote afbeelding, wordt als OK beschouwd."
            }

        if text_length < TEXT_LENGTH_THRESHOLD:
            reason = f"Zeer weinig inhoud ({text_length} tekens)"
        elif contains_soft_404_indicators(body_text):
            reason = "Melding dat pagina niet werd gevonden (404-achtig)"
        elif not has_footer and not has_h1:
            reason = "Pagina lijkt onvolledig (geen H1 of footer)"
        else:
            reason = "OK"

        if reason != "OK":
            screenshot = f"screenshots/{slugify(url)}.png"
            driver.save_screenshot(screenshot)
        else:
            screenshot = ""

        if reason != "OK":
            if text_length < 100:
                advice = "💡 Voeg inhoud toe of redirect naar relevante pagina."
            elif not has_h1:
                advice = "💡 Voeg een H1-titel toe voor structuur en SEO."
            elif not has_footer:
                advice = "💡 Controleer of de pagina correct laadt (footer ontbreekt)."
            else:
                advice = "⚠️ Controleer de technische staat van de pagina."
            redirect_suggestion = suggest_redirect(url)
            advice += f"\n🔁 Suggestie: redirect permanent (301) naar {redirect_suggestion}"
        else:
            advice = "👍 Alles lijkt in orde."

        return {
            "url": url,
            "status": "200?",
            "text_length": text_length,
            "reason": reason,
            "has_h1": has_h1,
            "has_footer": has_footer,
            "screenshot": screenshot,
            "advice": advice
        }

    except Exception as e:
        return {
            "url": url,
            "status": "error",
            "reason": str(e),
            "text_length": 0,
            "has_h1": False,
            "has_footer": False,
            "screenshot": "",
            "advice": "Fout bij laden van pagina.\n🔁 Suggestie: redirect permanent (301) naar homepage"
        }

# --- Main run ---
if uploaded_file:
    if uploaded_file.name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    else:
        excel_file = pd.ExcelFile(uploaded_file)
        sheet_found = False
        for sheet in excel_file.sheet_names:
            temp_df = excel_file.parse(sheet)
            for col in temp_df.columns:
                if any(kw in col.lower() for kw in ["url", "pagina", "toppagina", "link"]):
                    df = temp_df
                    sheet_found = True
                    break
            if sheet_found:
                break
        if not sheet_found:
            st.error("Kon geen sheet vinden met een kolom die URL's bevat.")
            st.stop()

    url_col = None
    for col in df.columns:
        if any(kw in col.lower() for kw in ["url", "pagina", "toppagina", "link"]):
            url_col = col
            break

    if not url_col:
        st.error("Geen kolom met URL's gevonden.")
    else:
        st.success(f"URL-kolom gevonden: {url_col}")
        urls = df[url_col].dropna().unique().tolist()

        browser = setup_browser()
        results = []

        start_time = time.time()
        progress_bar = st.progress(0)
        status_placeholder = st.empty()

        for i, url in enumerate(urls):
            result = check_url(browser, url)
            results.append(result)
            progress_bar.progress((i + 1) / len(urls))
            status_placeholder.text(f"{i + 1}/{len(urls)} verwerkt... Tijd: {round(time.time() - start_time, 1)}s")

        browser.quit()

        result_df = pd.DataFrame(results)
        st.dataframe(result_df, use_container_width=True)

        csv = result_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download resultaat als CSV", data=csv, file_name="broken_pages_check.csv", mime="text/csv")

        st.markdown("### 🖼️ Screenshots van foutieve of lege pagina's")
        for i, row in result_df.iterrows():
            if row["reason"] != "OK" and row["screenshot"]:
                st.image(row["screenshot"], caption=row["url"], use_column_width=True)

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for i, row in result_df.iterrows():
                if row["screenshot"] and os.path.exists(row["screenshot"]):
                    zip_file.write(row["screenshot"], arcname=os.path.basename(row["screenshot"]))
        zip_buffer.seek(0)
        st.download_button("📦 Download alle screenshots als ZIP", data=zip_buffer, file_name="screenshots.zip", mime="application/zip")
