📄 SEC Annual Report Downloader

A Streamlit application for retrieving annual SEC filings (10-K, 20-F, 40-F) for a list of ticker symbols.
The app downloads the documents as PDFs or returns URLs only, and produces a manifest CSV summarizing results.

## ✅ 1. Installation Guide
------------------------------------
### 1.1 Install Python

You must have Python 3.10 or newer installed.

Download Python from:
🔗 https://www.python.org/downloads/

During installation, ensure you check:
    Add Python to PATH

### 1.2 Install required Python packages

Open Command Prompt or PowerShell, then run:

pip install streamlit pandas requests


These packages are required for:

User interface (Streamlit)

HTTP requests to the SEC (requests)

Data handling and manifest files (pandas)

### 1.3 Install wkhtmltopdf (Required only if you download PDFs)

This tool converts SEC HTML filings into PDF format.

#### Step A — Download wkhtmltopdf

Visit:

🔗 https://wkhtmltopdf.org/downloads.html

Download the Windows 64-bit installer.

#### Step B — Install

Run the installer and keep the default installation options.

Step C — Confirm it is installed at:
C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe


This is the path used by the application.
If it differs on your system, update the path in sec_downloader.py:

WKHTMLTOPDF = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

### 1.4. Set your SEC User-Agent (Mandatory)
The SEC requires all automated scripts to identify themselves.

In sec_downloader.py, update this line:
SER_AGENT = "Your Name fy-report-downloader/1.0 (youremail@example.com)" 

------------------------------------


## 📁 2. Folder Structure

Your project folder should look like:

your_project/
├── app.py
├── sec_downloader.py
└── README.md


The app will automatically create:

downloads/
    fy2023/
        <pdf files if enabled>
        manifest_fy2023.csv
## ▶️ 3. How to Run the Application
Open Command Prompt or PowerShell
Navigate to your project directory:

-> cd path\to\your_project


Start the Streamlit application:

-> streamlit run app.py


## 🧭 4. How to Use the App
### Step 1 — Provide tickers

#### A Upload a CSV or Excel
- Must contain a column named Ticker
- If not, the first column is used
#### B. Type or paste tickers manually
- Both methods can be combined — tickers are cleaned and deduplicated automatically.

### Step 2 — Configure Settings
- In the sidebar, choose:
- Fiscal year (e.g., 2023)
- Form types (10-K, 20-F, 40-F)
- Download root folder
- Download PDFs (checkbox)

ON → create PDFs using wkhtmltopdf
OFF → return URLs only (no PDF generation)

### Step 3 — Download filings

Click: 🚀 Download filings

The app shows:
- A progress bar
- Current ticker being processed
- Number completed vs. total

## Step 4 — View results

The app displays:
📊 Manifest table
- Ticker
- CIK
- Status (OK, NO_CIK, NO_FY_FILING, ERROR, etc.)
- Form type
- Report & Filing dates
- URL to the filing
- Saved PDF path (if enabled)
⬇️ Manifest CSV download button

## 📄 5. Output Files
Inside your configured download directory:
downloads/
    fy<year>/
        manifest_fy<year>.csv
        AAPL_FY2023_10-K.pdf        (if PDF mode)
        MSFT_FY2023_10-K.pdf        (if PDF mode)
        ...

-> If PDF mode is OFF, nothing is created except the folder

## 🛠 6. Troubleshooting
### ❌ wkhtmltopdf not found
If Download PDFs is ON and wkhtmltopdf is missing or the path is incorrect, you’ll see an error:
    wkhtmltopdf not found…

Fix by updating the path in sec_downloader.py:
    WKHTMLTOPDF = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

Or toggle Download PDFs off.

❌ SEC rate limiting issues

If you hit SEC rate limits, you can reduce request frequency:

REQUESTS_PER_SECOND = 2

❌ No filing found

Some companies may not have submitted the requested form for that year.

Check:
- Status column
- Notes column



