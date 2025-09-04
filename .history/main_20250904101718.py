import numpy as np
import pandas as pd
import streamlit as st
import os

# Try to import plotly with a clear, actionable error if missing
try:
    import plotly.graph_objects as go
except Exception as e:
    import sys, shutil, subprocess
    st.error(
        "Plotly is not installed in the Python environment running this app.\n\n"
        "Fix locally: Activate your venv and run: `python -m pip install plotly`\n"
        "Fix on Streamlit Cloud: Add `plotly` to requirements.txt and redeploy."
    )
    # Show quick environment diagnostics to help you match pip/python
    py = sys.executable
    which_streamlit = shutil.which("streamlit")
    st.info(
        f"Python: {py}\n\n"
        f"streamlit executable: {which_streamlit}\n\n"
        "Try: `python -m pip show plotly` and ensure it shows under this same Python path."
    )
    st.stop()

##############################
# App: Required Lump Sum by Allocation 
# Goal: For each allocation (LBM columns), compute the required single
#       upfront investment to reach a target (e.g., $1,000,000) with a
#       chosen confidence over N years using historical factor windows.
##############################

st.set_page_config(layout="wide")
st.title("Required Lump Sum by Allocation")
st.caption("Computes the one‑time contribution needed to reach your goal with the selected confidence using historical factor windows. This model assumes that the future goal is in 'Today's Dollars' which ajdusts for inflation.")

# ------------------------------
# Inputs
# ------------------------------
file_path = "lbm_factors.xlsx"
sheet_name = "allocation_factors"

col1, col2, col3 = st.columns(3)
with col1:
    data_choice = st.selectbox(
        "Data source",
        ["Global (LBM)", "S&P 500 (SPX)", "Both (LBM + SPX)"],
        index=0,
        help="Choose the factor set: LBM workbook (Excel), S&P 500 CSV (spx_factors.csv), or both.",
    )
    goal = st.number_input("Goal ($)", min_value=1, step=1000, value=1_000_000)
with col2:
    num_years = st.number_input("Years", min_value=1, max_value=60, value=30)
with col3:
    conf_pct = st.slider("Confidence (%)", min_value=50, max_value=100, value=90)
    confidence_level = conf_pct / 100.0
    fee_pct = st.slider(
        "Annual fee (%)",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.1,
        help="Applied once per 12-month factor: net = gross × (1 − fee).",
    )

# Fixed: data is monthly, so step 12 rows per simulated year
row_increment = 12

st.divider()

# ------------------------------
# Load factors (LBM Excel or SPX CSV)
# ------------------------------
if data_choice.startswith("Both"):
    src_kind = "BOTH"
elif data_choice.startswith("Global"):
    src_kind = "LBM"
else:
    src_kind = "SPX"

# Load one or both datasets
df_lbm, df_spx = None, None
if src_kind in ("LBM", "BOTH"):
    try:
        df_lbm = pd.read_excel(file_path, sheet_name=sheet_name)
        st.success("LBM worksheet loaded.")
    except Exception as e:
        st.error(f"Error loading LBM factors: {e}")
if src_kind in ("SPX", "BOTH"):
    try:
        df_spx = pd.read_csv("spx_factors.csv")
        st.success("SPX factors loaded.")
    except Exception as e:
        st.error(f"Error loading SPX factors: {e}")

# For single-source paths keep `df` for downstream compatibility; for BOTH we'll handle explicitly later
if src_kind == "LBM":
    df = df_lbm
elif src_kind == "SPX":
    df = df_spx
else:
    df = None

# ------------------------------
# Prepare columns (detect allocations, coerce numeric)
# ------------------------------
# Detect allocation columns per source
allocation_cols_lbm, allocation_cols_spx = [], []
if src_kind in ("LBM", "BOTH") and df_lbm is not None:
    df_lbm.columns = df_lbm.columns.astype(str).str.strip().str.replace("  ", " ")
    allocation_cols_lbm = [c for c in df_lbm.columns if c.upper().startswith("LBM ")]
    for c in allocation_cols_lbm:
        df_lbm[c] = pd.to_numeric(df_lbm[c], errors='coerce')
    if not allocation_cols_lbm and src_kind != "SPX":
        st.warning("No allocation columns found in LBM (expected headers starting with 'LBM ').")

if src_kind in ("SPX", "BOTH") and df_spx is not None:
    df_spx.columns = df_spx.columns.astype(str).str.strip().str.replace("  ", " ")
    allocation_cols_spx = [c for c in df_spx.columns if c.upper().startswith("SPX")]  # e.g., spx60e
    for c in allocation_cols_spx:
        df_spx[c] = pd.to_numeric(df_spx[c], errors='coerce')
    if not allocation_cols_spx and src_kind != "LBM":
        st.warning("No allocation columns found in SPX (expected headers like 'spx60e', 'spx40e', etc.).")

# Back-compat single list when not BOTH
if src_kind == "LBM":
    allocation_cols = allocation_cols_lbm
elif src_kind == "SPX":
    allocation_cols = allocation_cols_spx
else:
    allocation_cols = allocation_cols_lbm + allocation_cols_spx

# Apply annual fee to 12‑month factors (net = gross × (1 − fee))
fee = float(fee_pct) / 100.0  # convert percent to decimal (e.g., 0.2% -> 0.002)
if fee > 0:
    if src_kind in ("LBM", "BOTH") and df_lbm is not None and allocation_cols_lbm:
        df_lbm[allocation_cols_lbm] = df_lbm[allocation_cols_lbm] * (1.0 - fee)
    if src_kind in ("SPX", "BOTH") and df_spx is not None and allocation_cols_spx:
        df_spx[allocation_cols_spx] = df_spx[allocation_cols_spx] * (1.0 - fee)

# ------------------------------
# Core math (LUMP SUM)
# ------------------------------

def simulate_ending_values_lumpsum(factors: pd.Series, years: int, step: int) -> list:
    """For each possible start row, compute the ending value of $1 invested
    at the start and held for 'years' years, compounding by the factor at
    each step. Skips windows containing NaNs or non‑positive factors.

    Returns a list of ending values (one per valid start window).
    """
    vals = []
    n = len(factors)
    max_start = n - (step * (years - 1))
    if max_start <= 0:
        return vals
    for start in range(max_start):
        prod = 1.0
        valid = True
        for y in range(years):
            idx = start + y * step
            f = factors.iloc[idx]
            if pd.isna(f) or f <= 0:
                valid = False
                break
            prod *= float(f)
        if valid:
            vals.append(prod)
    return vals


def required_lumpsum_for_goal(ending_values: list, goal_amount: float, conf: float) -> float:
    """Given the distribution of ending values for $1 lump sum invested,
    compute the upfront amount needed to hit 'goal_amount' with the specified
    confidence. Uses the lower‑tail (1 − conf) quantile conservatively.
    """
    if not ending_values:
        return float('nan')
    arr = np.array(sorted(ending_values))
    q = (1.0 - conf)
    idx = int(np.floor(q * len(arr)))
    idx = max(0, min(idx, len(arr) - 1))
    ev = arr[idx]
    if ev <= 0:
        return float('inf')
    return goal_amount / ev

# ------------------------------
# Run
# ------------------------------
# Build results from one or both datasets
have_any = (
    (src_kind in ("LBM", "BOTH") and df_lbm is not None and allocation_cols_lbm) or
    (src_kind in ("SPX", "BOTH") and df_spx is not None and allocation_cols_spx)
)
if have_any:
    rows = []

    if src_kind in ("LBM", "BOTH") and df_lbm is not None:
        for col in allocation_cols_lbm:
            evs = simulate_ending_values_lumpsum(df_lbm[col], int(num_years), int(row_increment))
            if not evs:
                req = np.nan
                note = "No valid windows (NaNs or insufficient length)"
            else:
                req = required_lumpsum_for_goal(evs, float(goal), float(confidence_level))
                note = ""
            rows.append({
                "Allocation": col.strip(),
                "Required Lump Sum": np.nan if pd.isna(req) else float(req),
            })

    if src_kind in ("SPX", "BOTH") and df_spx is not None:
        for col in allocation_cols_spx:
            evs = simulate_ending_values_lumpsum(df_spx[col], int(num_years), int(row_increment))
            if not evs:
                req = np.nan
                note = "No valid windows (NaNs or insufficient length)"
            else:
                req = required_lumpsum_for_goal(evs, float(goal), float(confidence_level))
                note = ""
            rows.append({
                "Allocation": col.strip(),
                "Required Lump Sum": np.nan if pd.isna(req) else float(req),
            })

    results = pd.DataFrame(rows)

    # Order & pretty labels per source (or both)
    order_lbm = [
        'LBM 100E','LBM 90E','LBM 80E','LBM 70E','LBM 60E',
        'LBM 50E','LBM 40E','LBM 30E','LBM 20E','LBM 10E','LBM 100F'
    ]
    pretty_lbm = {
        'LBM 100E': '100% Equity','LBM 90E': '90% Equity','LBM 80E': '80% Equity','LBM 70E': '70% Equity',
        'LBM 60E': '60% Equity','LBM 50E': '50% Equity','LBM 40E': '40% Equity','LBM 30E': '30% Equity',
        'LBM 20E': '20% Equity','LBM 10E': '10% Equity','LBM 100F': '100% Fixed'
    }
    order_spx = [f"spx{p}e" for p in [100,90,80,70,60,50,40,30,20,10,0]]
    pretty_spx = {f"spx{p}e": f"{p}% Equity" for p in [100,90,80,70,60,50,40,30,20,10,0]}

    # Build 3‑column results: Allocation (generic), Global, SP500
    def _to_generic_label(a: str) -> str:
        # Map raw header to a generic label via the pretty maps
        lab = pretty_lbm.get(a, pretty_spx.get(a, a))
        # Normalize: treat any "0% Equity" as "100% Fixed" to align SPX 0e with LBM 100F
        if isinstance(lab, str) and lab.strip().startswith("0% Equity"):
            return "100% Fixed"
        return lab

    tmp = results.copy()
    tmp["Allocation"] = tmp["Allocation"].astype(str)

    # Derive source from the raw header prefix
    tmp["Source"] = np.where(
        tmp["Allocation"].str.upper().str.startswith("LBM "),
        "Global",
        np.where(tmp["Allocation"].str.lower().str.startswith("spx"), "SP500", None),
    )
    tmp["Generic"] = tmp["Allocation"].map(_to_generic_label)

    # Pivot to wide format with rows as generic allocation names
    wide = tmp.pivot_table(index="Generic", columns="Source", values="Required Lump Sum", aggfunc="first")

    # Order rows by common allocation sequence
    generic_order = [
        "100% Equity","90% Equity","80% Equity","70% Equity","60% Equity",
        "50% Equity","40% Equity","30% Equity","20% Equity","10% Equity","100% Fixed"
    ]
    present_generic = [g for g in generic_order if g in wide.index]
    wide = wide.reindex(present_generic)

    # Reset index and ensure both columns exist
    wide = wide.rename_axis(None, axis=1).reset_index().rename(columns={"Generic": "Allocation"})
    for col in ["Global", "SP500"]:
        if col not in wide.columns:
            wide[col] = np.nan

    # Currency formatting for display
    display_results = wide.copy()
    for col in ["Global", "SP500"]:
        if col in display_results.columns:
            display_results[col] = display_results[col].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "")

    # Reorder to the three requested columns
    display_results = display_results[["Allocation", "Global", "SP500"]]

    st.subheader("Results")
    st.write(display_results)

    # Grouped bar chart using the wide (numeric) table
    chart_df = wide.copy()
    if not chart_df.empty:
        fig = go.Figure()
        if "Global" in chart_df.columns:
            fig.add_bar(name="Global", x=chart_df["Allocation"], y=chart_df["Global"])
        if "SP500" in chart_df.columns:
            fig.add_bar(name="SP500", x=chart_df["Allocation"], y=chart_df["SP500"])
        fig.update_layout(
            title="Required Lump Sum by Allocation",
            xaxis_title="Allocation",
            yaxis_title="Required Lump Sum ($)",
            barmode="group",
            yaxis=dict(tickformat=",.0f", tickprefix="$"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Download (CSV with raw numeric values)
    csv = display_results.to_csv(index=False)
    st.download_button("Download CSV", data=csv, file_name="required_lumpsum_by_allocation.csv", mime="text/csv")

    st.divider()
    st.subheader("Disclosures")
    # Try common locations for the disclosures PDF
    pdf_candidates = [
        "DataSource LBM Portfolios.pdf",
        os.path.join("..", "DataSource LBM Portfolios.pdf"),
        "disclosures.pdf",  # fallback name
    ]
    pdf_path = next((p for p in pdf_candidates if os.path.exists(p)), None)

    if pdf_path:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        file_label = os.path.basename(pdf_path)
        # Force download only (no in-browser open/link)
        st.download_button(
            "Download Disclosures (PDF)",
            data=pdf_bytes,
            file_name=file_label,
            mime="application/pdf",
        )
    else:
        st.info("Add `DataSource LBM Portfolios.pdf` to this app folder (or parent) to enable the download.")


# ------------------------------
        
