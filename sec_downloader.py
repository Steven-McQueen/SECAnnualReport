"""
sec_downloader.py

Backend module for downloading SEC annual reports (10-K, 20-F, 40-F)
for a list of tickers and a given fiscal year.

Typical usage from another script or Streamlit app:

    import pandas as pd
    from pathlib import Path
    from sec_downloader import download_annuals

    tickers_df = pd.DataFrame({"Ticker": ["AAPL", "MSFT", "BRK.B"]})
    manifest = download_annuals(
        tickers_df,
        year=2023,
        download_root=Path("downloads"),
        create_pdfs=True,
    )

Requirements:
    - requests
    - pandas
    - wkhtmltopdf installed on your machine (only if create_pdfs=True)
"""

import json
import time
import pathlib
import subprocess
from typing import Dict, Tuple, Optional, Iterable, Callable

import pandas as pd
import requests

# -------- CONFIG (you can edit these) --------

# Forms considered "annual reports" for your use case
FORMS = {"10-K", "20-F", "40-F"}

# Root directory where downloads will be stored.
# Final files will be saved under: download_root / f"fy{year}"
DEFAULT_DOWNLOAD_ROOT = pathlib.Path("downloads")

# User-Agent string to use for SEC requests (per SEC guidelines, include your email)
USER_AGENT = "Jane Doe fy-report-downloader/1.0 (johndoe@gmail.com)"

# SEC expects reasonable rate limiting (< 10 requests/second).
REQUESTS_PER_SECOND = 3
SLEEP = 1.0 / REQUESTS_PER_SECOND

# Path to wkhtmltopdf executable (adapt to your machine)
WKHTMLTOPDF = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

# Local cache of the ticker/CIK mapping file
TICKER_CIK_JSON = pathlib.Path("company_tickers.json")

# ---------- END CONFIG ----------


# ---------- HTTP session ----------

session = requests.Session()
session.headers.update(
    {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
)


# ---------- Helper functions ----------

def wkhtmltopdf_available() -> bool:
    """Check whether wkhtmltopdf exists at the configured path."""
    return pathlib.Path(WKHTMLTOPDF).is_file()


def html_to_pdf(url: str, out_pdf: pathlib.Path) -> None:
    """
    Convert an HTML URL to PDF using wkhtmltopdf.

    Raises RuntimeError on failure.
    """
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        WKHTMLTOPDF,
        "--quiet",
        "--print-media-type",
        "--margin-top",
        "12mm",
        "--margin-right",
        "12mm",
        "--margin-bottom",
        "12mm",
        "--margin-left",
        "12mm",
        "--custom-header",
        "User-Agent",
        USER_AGENT,
        url,
        str(out_pdf),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0 or not out_pdf.exists():
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        msg = stderr or stdout or "wkhtmltopdf failed without message"
        raise RuntimeError(f"wkhtmltopdf failed ({result.returncode}): {msg}")


def year_from(date_str: Optional[str]) -> Optional[int]:
    """
    Extract the year (first 4 digits) from a YYYY-MM-DD-like string.
    Returns None if not parseable.
    """
    if not date_str:
        return None
    s = str(date_str)
    if len(s) < 4 or not s[:4].isdigit():
        return None
    return int(s[:4])


# ---------- Ticker / CIK mapping ----------

def _download_ticker_cik_map() -> Dict[str, dict]:
    """
    Download SEC's company_tickers.json file and return its raw JSON dict.

    This will also store the file locally so later runs don't have to download again.
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = session.get(url)
    resp.raise_for_status()
    data = resp.json()
    TICKER_CIK_JSON.write_text(json.dumps(data), encoding="utf-8")
    return data


def load_ticker_cik_map() -> Tuple[Dict[str, str], pd.DataFrame]:
    """
    Return:
        ticker_to_cik: dict mapping uppercase TICKER -> zero-padded 10-digit CIK
        df: DataFrame with columns [CIK, Ticker, Name]

    Uses a local JSON cache (company_tickers.json) if available, otherwise
    downloads from the SEC.
    """
    if TICKER_CIK_JSON.is_file():
        data = json.loads(TICKER_CIK_JSON.read_text(encoding="utf-8"))
    else:
        data = _download_ticker_cik_map()

    rows = []
    for entry in data.values():
        cik_str = str(entry["cik_str"]).zfill(10)
        ticker = str(entry["ticker"]).upper()
        title = entry.get("title", "")
        rows.append({"CIK": cik_str, "Ticker": ticker, "Name": title})

    df = pd.DataFrame(rows)
    ticker_to_cik = {row["Ticker"]: row["CIK"] for _, row in df.iterrows()}
    return ticker_to_cik, df


# ---------- SEC submissions ----------

def get_company_subs(cik10: str) -> dict:
    """
    Download the SEC submissions JSON for a given 10-digit CIK.
    Example URL:
        https://data.sec.gov/submissions/CIK0000320193.json
    """
    cik10 = str(cik10).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    resp = session.get(url)
    resp.raise_for_status()
    time.sleep(SLEEP)  # be nice to SEC
    return resp.json()


def find_fy_annual(
    subs: dict,
    target_year: int,
    forms: Iterable[str] = FORMS,
) -> Optional[dict]:
    """
    Given the submissions JSON for a company, find the relevant annual filing
    (10-K / 20-F / 40-F) for the specified fiscal year.

    Logic:
      - Look at `filings.recent`
      - Filter to rows where `form` is one of FORMS
      - For each such row, pick the year from `reportDate` or `periodOfReport`
      - Keep only rows where year == target_year
      - Pick the one with the latest `filingDate`

    Returns:
        dict with fields:
            index, form, accessionNumber, primaryDocument,
            filingDate, reportDate, periodOfReport
        or None if not found.
    """
    if not subs:
        return None

    filings = subs.get("filings", {})
    recent = filings.get("recent", {})

    forms_list = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    prims = recent.get("primaryDocument", [])
    fdates = recent.get("filingDate", [])
    rdates = recent.get("reportDate", [])
    pdates = recent.get("periodOfReport", [])

    n = max(
        len(forms_list),
        len(accs),
        len(prims),
        len(fdates),
        len(rdates),
        len(pdates),
    )

    candidates = []

    for i in range(n):
        form = forms_list[i] if i < len(forms_list) else None
        if form not in forms:
            continue

        report_date = rdates[i] if i < len(rdates) else None
        period_date = pdates[i] if i < len(pdates) else None

        rd_year = year_from(report_date)
        pd_year = year_from(period_date)
        year = rd_year or pd_year

        if year != target_year:
            continue

        filing_date = fdates[i] if i < len(fdates) else None
        accession_no = accs[i] if i < len(accs) else None
        primary_doc = prims[i] if i < len(prims) else None

        candidates.append(
            {
                "index": i,
                "form": form,
                "accessionNumber": accession_no,
                "primaryDocument": primary_doc,
                "filingDate": filing_date,
                "reportDate": report_date,
                "periodOfReport": period_date,
            }
        )

    if not candidates:
        return None

    # Sort by filingDate descending (newest first)
    def sort_key(x):
        # None-safe: None -> ""
        return (x.get("filingDate") or "")

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def build_filing_url(cik10: str, accession_no: str, primary_doc: str) -> str:
    """
    Build the URL to the primary document of the filing.
    Example:
    https://www.sec.gov/Archives/edgar/data/320193/000032019323000066/a10-k20239232023.htm
    """
    cik_no_zeros = str(int(cik10))  # remove leading zeros
    acc_nodash = accession_no.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{acc_nodash}/{primary_doc}"


# ---------- Main download function ----------

def download_annuals(
    tickers_df: pd.DataFrame,
    year: int,
    download_root: pathlib.Path = DEFAULT_DOWNLOAD_ROOT,
    forms: Iterable[str] = FORMS,
    create_pdfs: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> pd.DataFrame:
    """
    Download annual SEC filings (10-K / 20-F / 40-F) for each ticker in `tickers_df`
    for the given fiscal `year`.

    Args:
        tickers_df: DataFrame with at least one column 'Ticker'
        year: fiscal year to target (e.g., 2023)
        download_root: root directory for downloads
        forms: iterable of form types to consider
        create_pdfs: if False, no PDFs are created; only URLs are resolved
        progress_callback: optional function (done, total, ticker) -> None,
                           called after each ticker is processed.

    Returns:
        manifest_df: DataFrame with one row per ticker and columns:
            Ticker, CIK, Status, Form, ReportDate, FilingDate,
            URL, SavedTo, Note
    """
    # Prepare directory & check wkhtmltopdf only if we actually need PDFs
    year_int = int(year)
    fy_dir = download_root / f"fy{year_int}"
    fy_dir.mkdir(parents=True, exist_ok=True)

    if create_pdfs and not wkhtmltopdf_available():
        raise FileNotFoundError(
            f"wkhtmltopdf not found at '{WKHTMLTOPDF}'. "
            "Install it and/or update WKHTMLTOPDF path in sec_downloader.py, "
            "or set create_pdfs=False."
        )

    # Load ticker -> CIK map
    ticker_to_cik, _ = load_ticker_cik_map()

    # Clean tickers
    if "Ticker" not in tickers_df.columns:
        raise KeyError("tickers_df must contain a 'Ticker' column.")

    tickers = (
        tickers_df["Ticker"]
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
    )

    total = len(tickers)
    results = []

    for idx, t in enumerate(tickers, start=1):
        t_upper = t.upper()
        cik10 = ticker_to_cik.get(t_upper)

        if not cik10:
            results.append(
                {
                    "Ticker": t_upper,
                    "CIK": None,
                    "Status": "NO_CIK",
                    "Form": None,
                    "ReportDate": None,
                    "FilingDate": None,
                    "URL": None,
                    "SavedTo": None,
                    "Note": "CIK not found in company_tickers.json",
                }
            )
            if progress_callback:
                progress_callback(idx, total, t_upper)
            continue

        try:
            subs = get_company_subs(cik10)
        except Exception as e:
            results.append(
                {
                    "Ticker": t_upper,
                    "CIK": cik10,
                    "Status": "SUBMISSIONS_ERROR",
                    "Form": None,
                    "ReportDate": None,
                    "FilingDate": None,
                    "URL": None,
                    "SavedTo": None,
                    "Note": f"Error fetching submissions: {e}",
                }
            )
            if progress_callback:
                progress_callback(idx, total, t_upper)
            continue

        try:
            fy_filing = find_fy_annual(subs, target_year=year_int, forms=forms)
            if not fy_filing:
                results.append(
                    {
                        "Ticker": t_upper,
                        "CIK": cik10,
                        "Status": "NO_FY_FILING",
                        "Form": None,
                        "ReportDate": None,
                        "FilingDate": None,
                        "URL": None,
                        "SavedTo": None,
                        "Note": f"No FY {year_int} {tuple(forms)} filing found",
                    }
                )
                if progress_callback:
                    progress_callback(idx, total, t_upper)
                continue

            url = build_filing_url(
                cik10,
                fy_filing["accessionNumber"],
                fy_filing["primaryDocument"],
            )

            saved_path = None
            if create_pdfs:
                out_pdf = fy_dir / f"{t_upper}_FY{year_int}_{fy_filing['form']}.pdf"
                html_to_pdf(url, out_pdf)
                saved_path = str(out_pdf)

            results.append(
                {
                    "Ticker": t_upper,
                    "CIK": cik10,
                    "Status": "OK",
                    "Form": fy_filing["form"],
                    "ReportDate": fy_filing.get("reportDate"),
                    "FilingDate": fy_filing.get("filingDate"),
                    "URL": url,
                    "SavedTo": saved_path,
                    "Note": "" if create_pdfs else "PDF not created (URL-only mode)",
                }
            )

            time.sleep(SLEEP)

        except Exception as e:
            results.append(
                {
                    "Ticker": t_upper,
                    "CIK": cik10,
                    "Status": "ERROR",
                    "Form": None,
                    "ReportDate": None,
                    "FilingDate": None,
                    "URL": None,
                    "SavedTo": None,
                    "Note": str(e),
                }
            )

        if progress_callback:
            progress_callback(idx, total, t_upper)

    manifest_df = pd.DataFrame(results)
    return manifest_df


# ---------- Optional: simple CLI entry point ----------

if __name__ == "__main__":
    # Example usage when running this file directly:
    #   python sec_downloader.py
    example_tickers = pd.DataFrame({"Ticker": ["AAPL", "MSFT"]})
    year = 2023
    print(f"Downloading FY {year} filings for example tickers...")
    df_manifest = download_annuals(example_tickers, year=year, create_pdfs=False)
    print(df_manifest)
