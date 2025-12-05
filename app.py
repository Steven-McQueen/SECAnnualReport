# app.py
from pathlib import Path

import pandas as pd
import streamlit as st

from sec_downloader import download_annuals, FORMS, DEFAULT_DOWNLOAD_ROOT


# ------------- Page config -------------
st.set_page_config(
    page_title="SEC Annual Report Downloader",
    layout="wide",
)

st.title("📄 SEC Annual Report Downloader")
st.markdown(
    """
Download **annual SEC filings** (10-K / 20-F / 40-F) as PDFs  
for any list of tickers and fiscal year.

- Upload a file with tickers **or** type them in manually  
- Choose **fiscal year** and **form types**  
- Decide whether to **download PDFs** or just get **filing URLs**
"""
)

# ------------- Sidebar settings -------------
st.sidebar.header("⚙️ Settings")

# Fiscal year
year = st.sidebar.number_input(
    "Fiscal year",
    min_value=1995,
    max_value=2100,
    value=2023,
    step=1,
)

# Download root directory
download_root_str = st.sidebar.text_input(
    "Download root directory",
    value=str(DEFAULT_DOWNLOAD_ROOT),
    help="Folder where PDFs and manifest will be stored. A subfolder `fy<year>` is created automatically.",
)
download_root = Path(download_root_str).expanduser().resolve()

# Toggle: create PDFs or not
create_pdfs = st.sidebar.checkbox(
    "Download PDFs (using wkhtmltopdf)",
    value=True,
    help="If unchecked, the app only resolves URLs and creates a manifest (no PDFs).",
)

# Form types to include
form_options = sorted(list(FORMS))
selected_forms = st.sidebar.multiselect(
    "Form types to include",
    options=form_options,
    default=form_options,
    help="Annual report forms to search for each ticker.",
)

if not selected_forms:
    st.sidebar.warning("Select at least one form type (e.g. 10-K).")

# ------------- Ticker input -------------
st.subheader("1️⃣ Provide tickers")

col1, col2 = st.columns(2)

with col1:
    uploaded_file = st.file_uploader(
        "Upload file with tickers (CSV or Excel)",
        type=["csv", "xlsx"],
        help="Must contain a column named 'Ticker'. If not, the first column will be treated as tickers.",
    )

with col2:
    manual_tickers_text = st.text_area(
        "Or paste / type tickers manually",
        placeholder="Example:\nAAPL\nMSFT\nMETA\nTSLA",
        height=180,
    )

tickers_df = None
errors = []


# --- From file upload ---
if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df_file = pd.read_csv(uploaded_file)
        else:
            df_file = pd.read_excel(uploaded_file)

        if "Ticker" in df_file.columns:
            tickers_df = df_file[["Ticker"]].copy()
        else:
            first_col = df_file.columns[0]
            tickers_df = df_file[[first_col]].rename(columns={first_col: "Ticker"})
    except Exception as e:
        errors.append(f"Error reading uploaded file: {e}")


# --- From manual text ---
if manual_tickers_text.strip():
    manual_list = []
    for line in manual_tickers_text.splitlines():
        # Split by comma or whitespace
        parts = line.replace(",", " ").split()
        manual_list.extend([p.strip() for p in parts if p.strip()])

    if manual_list:
        manual_df = pd.DataFrame({"Ticker": manual_list})
        if tickers_df is not None:
            tickers_df = pd.concat([tickers_df, manual_df], ignore_index=True)
        else:
            tickers_df = manual_df


# --- Clean and display tickers ---
if tickers_df is not None and not tickers_df.empty:
    tickers_df["Ticker"] = (
        tickers_df["Ticker"].astype(str).str.strip()
    )
    tickers_df = tickers_df.replace("", pd.NA).dropna()
    tickers_df = tickers_df.drop_duplicates()

    if tickers_df.empty:
        st.info("No valid tickers after cleaning input.")
    else:
        st.write(f"✅ **{len(tickers_df)}** unique tickers detected:")
        st.dataframe(tickers_df, width='stretch', height=250)
else:
    st.info("Upload a file or enter tickers manually to continue.")


# Show any parsing errors
for msg in errors:
    st.error(msg)

# ------------- Run downloader -------------
st.subheader("2️⃣ Download annual filings")

run_button = st.button("🚀 Download filings")

if run_button:
    if errors:
        st.error("Fix the errors above before running.")
    elif tickers_df is None or tickers_df.empty:
        st.error("No valid tickers found. Please upload or enter at least one ticker.")
    elif not selected_forms:
        st.error("Please select at least one form type (e.g. 10-K).")
    else:
        # Progress UI
        total = len(tickers_df.index)
        progress_bar = st.progress(0.0)
        status_area = st.empty()

        def progress_callback(done: int, total_count: int, ticker: str):
            # Clamp to [0, 1] just in case
            fraction = min(max(done / max(total_count, 1), 0.0), 1.0)
            progress_bar.progress(fraction)
            status_area.write(f"Processing **{ticker}** ({done}/{total_count})...")

        try:
            with st.spinner(f"Downloading filings for fiscal year {int(year)}..."):
                manifest_df = download_annuals(
                    tickers_df=tickers_df,
                    year=int(year),
                    download_root=download_root,
                    forms=selected_forms,
                    create_pdfs=create_pdfs,
                    progress_callback=progress_callback,
                )

            progress_bar.progress(1.0)
            status_area.write("✅ All tickers processed.")

            st.success("✅ Download complete!")

            st.markdown("### 📊 Manifest")
            st.dataframe(manifest_df, width='stretch', height=400)

            # CSV download
            csv_bytes = manifest_df.to_csv(index=False).encode("utf-8")

            download_clicked = st.download_button(
                label="⬇️ Download manifest as CSV",
                data=csv_bytes,
                file_name=f"manifest_fy{int(year)}.csv",
                mime="text/csv",
            )

            if download_clicked:
                fy_dir = download_root / f"fy{int(year)}"
                fy_dir.mkdir(parents=True, exist_ok=True)

                manifest_path = fy_dir / f"manifest_fy{int(year)}.csv"
                with open(manifest_path, "wb") as f:
                    f.write(csv_bytes)

                st.success(f"Manifest saved to: `{manifest_path}`")


            fy_dir = download_root / f"fy{int(year)}"
            if create_pdfs:
                st.markdown(
                    f"📂 PDF files are saved locally under:\n\n`{fy_dir}`"
                )
            else:
                st.markdown(
                    f"ℹ️ URL-only mode enabled: no PDFs were created.\n\n"
                    f"A manifest CSV has been saved under:\n\n`{fy_dir}`"
                )

        except FileNotFoundError as e:
            # Typically wkhtmltopdf missing / wrong path
            st.error(str(e))
        except Exception as e:
            st.error("An unexpected error occurred while downloading filings.")
            st.exception(e)
