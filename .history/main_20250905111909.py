import numpy as np
import pandas as pd
import streamlit as st
import os
from textwrap import dedent

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
st.title("Required Lump Sum by Allocation Using Global & S&P 500 Historical Returns")
st.caption("This Model Computes the one‑time contribution needed to reach your goal with the selected confidence using historical factor windows. This model assumes that the future goal is in 'Today's Dollars' which ajdusts for inflation.")

# Hover help near the top (compact tooltip)
st.markdown(dedent("""
<style>
.iris-tip { position: relative; display: inline-block; margin-left: 8px; }
.iris-tip .iris-bubble {
    visibility: hidden; opacity: 0; transition: opacity 0.15s ease-in-out;
    position: absolute; z-index: 9999; top: 22px; left: 0;
    width: min(780px, 90vw); padding: 12px 14px; line-height: 1.45;
    background: #334155 !important; color: #fff !important; border-radius: 6px; box-shadow: 0 6px 18px rgba(0,0,0,0.25);
}
.iris-tip:hover .iris-bubble { visibility: visible; opacity: 1; }
.iris-tip .iris-title { font-weight: 600; margin-bottom: 6px; }
.iris-tip ul { margin: 6px 0 10px 18px; }
.iris-tip code { background: rgba(255,255,255,0.08); padding: 0 4px; border-radius: 3px; }
.iris-tip .muted { opacity: 0.85; }
.iris-tip > span { color: #1D4ED8 !important; cursor: help; }
</style>
<div class="iris-tip">
  <span>🛈 <strong>Hover here to find out How this comparison works</strong></span>
  <div class="iris-bubble">
    <div class="iris-title">Why compare Global vs. S&amp;P 500?</div>
    <div class="muted">
      The S&amp;P 500 is only U.S. large companies. A <strong>global</strong> portfolio owns thousands of companies across countries and sectors. This tool is an <em>historical audit</em>—it looks at real rolling periods and shows the one-time amount needed to reach your goal.
    </div>
    <ul>
      <li><strong>Allocation</strong>: stock/bond mix (e.g., 60% Equity)</li>
      <li><strong>Global vs. SP500</strong>: up‑front amount needed under historical windows</li>
      <li><strong>Confidence</strong>: 100% = worst historical window; 95% = conservative percentile</li>
      <li><strong>Fees</strong>: applied annually to factors</li>
    </ul>
    <div class="iris-title">Why dollar differences can look large</div>
    <div class="muted">
      Small annual gaps compound. Required lump sum is the <em>inverse</em> of growth.
      Example (illustrative): over 25 years, 5%/yr grows \$1 → <strong>\$3.4</strong>; 2%/yr grows \$1 → <strong>\$1.6</strong>.
      To reach \$1,000,000: ~\$1,000,000/3.4 ≈ <strong>\$295,000</strong> vs ~\$1,000,000/1.6 ≈ <strong>\$625,000</strong>.
    </div>
    <div class="muted" style="margin-top:6px;"><em>Educational use only. Past performance does not guarantee future results.</em></div>
  </div>
</div>
"""), unsafe_allow_html=True)

# ------------------------------
# Inputs
# ------------------------------
file_path = "lbm_factors.xlsx"
sheet_name = "allocation_factors"

col1, col2, col3 = st.columns(3)
with col1:
    data_choice = st.selectbox(
        "Data source",
        ["Global", "S&P 500", "Both (Global & SPX)"],
        index=0,
        help="Choose the returns set: Global, S&P 500 or both.",
    )
    goal = st.number_input(
        "Goal ($)",
        min_value=1,
        step=50000,
        value=1_000_000,
        help=dedent(
            "“Today’s dollars” means the same buying power as money today (inflation‑adjusted). "
            "Example: a goal of \\$1,000,000 in 25 years means the amount that buys what \\$1,000,000 buys now."
        ),
        format="%i",
    )
with col2:
    num_years = st.number_input("Years", min_value=1, max_value=60, value=30)
with col3:
    conf_pct = st.slider(
        "Confidence (%)",
        min_value=50, step=10, max_value=100, value=90,
        help='For example, 90% means you want to invest enough to hit your goal in 90% of the simulations (10% chance you will not meet the goal).'
    )
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
    except Exception as e:
        st.error(f"Error loading LBM factors: {e}")
if src_kind in ("SPX", "BOTH"):
    try:
        df_spx = pd.read_csv("spx_factors.csv")
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

    # Reset index
    wide = wide.rename_axis(None, axis=1).reset_index().rename(columns={"Generic": "Allocation"})

    # Compute implied worst-window CAGR for each source:
    # CAGR = (goal / required_lump_sum) ** (1/years) - 1
    # Guard against NaNs/zeros.
    years_float = float(num_years) if num_years else 1.0
    if "Global" in wide.columns:
        with np.errstate(invalid="ignore", divide="ignore"):
            wide["Global CAGR"] = np.where(
                (wide["Global"].notna()) & (wide["Global"] > 0),
                (goal / wide["Global"]) ** (1.0 / years_float) - 1.0,
                np.nan,
            )
    if "SP500" in wide.columns:
        with np.errstate(invalid="ignore", divide="ignore"):
            wide["SP500 CAGR"] = np.where(
                (wide["SP500"].notna()) & (wide["SP500"] > 0),
                (goal / wide["SP500"]) ** (1.0 / years_float) - 1.0,
                np.nan,
            )

    # Currency formatting for display
    display_results = wide.copy()
    for col in ["Global", "SP500"]:
        if col in display_results.columns:
            display_results[col] = display_results[col].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else "")

    # Format CAGRs as percentages
    for col in ["Global CAGR", "SP500 CAGR"]:
        if col in display_results.columns:
            display_results[col] = display_results[col].apply(lambda r: f"{r:.2%}" if pd.notna(r) else "")

    # Reorder columns dynamically based on selected data source
    cols = ["Allocation"]
    if "Global" in display_results.columns:
        cols.extend(["Global"] + (["Global CAGR"] if "Global CAGR" in display_results.columns else []))
    if "SP500" in display_results.columns:
        cols.extend(["SP500"] + (["SP500 CAGR"] if "SP500 CAGR" in display_results.columns else []))
    display_results = display_results[cols]

    st.subheader("Results")
    st.caption("The Global CAGR and SP500 CAGR columns show the the compounded annual return in real terms (net of fees and inflation).")
    # Determine which Allocation has the minimum required lump sum for each source
    global_alloc = None
    spx_alloc = None
    if "Global" in wide.columns and wide["Global"].notna().any():
      gidx = wide["Global"].idxmin()
      global_alloc = wide.loc[gidx, "Allocation"]
    if "SP500" in wide.columns and wide["SP500"].notna().any():
      sidx = wide["SP500"].idxmin()
      spx_alloc = wide.loc[sidx, "Allocation"]

    # Styling function to highlight minimum cells only
    def _highlight_min_cells(df: pd.DataFrame) -> pd.DataFrame:
      styles = pd.DataFrame("", index=df.index, columns=df.columns)
      if global_alloc is not None and "Global" in df.columns:
          styles.loc[df["Allocation"] == global_alloc, "Global"] = "background-color:#e6f7e6;font-weight:600;"
      if spx_alloc is not None and "SP500" in df.columns:
          styles.loc[df["Allocation"] == spx_alloc, "SP500"] = "background-color:#fff2e6;font-weight:600;"
      return styles

    styled = display_results.style.apply(_highlight_min_cells, axis=None)
    st.dataframe(styled, use_container_width=True)


    # ------------------------------------------------------------
    # Failure Distribution panel (per source, for the CHEAPEST allocation)
    # ------------------------------------------------------------
    st.markdown("#### Failure Distribution (when investing the Required Lump Sum)")
    failure_rows = []
    
    # Build maps from generic label -> raw column for each source
    inv_lbm = {v: k for k, v in pretty_lbm.items()}    # e.g., "60% Equity" -> "LBM 60E"
    inv_spx = {v: k for k, v in pretty_spx.items()}    # e.g., "60% Equity" -> "spx60e"
    # Normalize: generic "100% Fixed" maps to LBM 100F and spx0e where applicable
    if "100% Fixed" not in inv_lbm and "LBM 100F" in pretty_lbm:
        inv_lbm["100% Fixed"] = "LBM 100F"
    if "100% Fixed" not in inv_spx and "spx0e" in pretty_spx:
        inv_spx["100% Fixed"] = "spx0e"
    
    # Helper to compute failure distribution for one source/allocation
    def _failure_stats(df_src, raw_col, required_amt, label_source):
        evs = simulate_ending_values_lumpsum(df_src[raw_col], int(num_years), int(row_increment))
        if not evs:
            return
        arr = np.array(evs, dtype=float) * float(required_amt)  # ending values in currency when investing Required Lump Sum
        total = int(arr.size)
        fails = arr < float(goal)
        num_fail = int(fails.sum())
        if num_fail == 0:
            failure_rows.append({
                "Source": label_source,
                "Allocation": raw_col,
                "Windows": total,
                "Failures": 0,
                "Failure Rate": "0.0%",
                "Worst": "",
                "P25": "",
                "Median": "",
                "P75": ""
            })
            return
        failed = arr[fails]
        # Compute quartiles of the failures
        p25 = np.percentile(failed, 25)
        p50 = np.percentile(failed, 50)
        p75 = np.percentile(failed, 75)
        worst = failed.min()
        failure_rows.append({
            "Source": label_source,
            "Allocation": raw_col,
            "Windows": total,
            "Failures": num_fail,
            "Failure Rate": f"{(num_fail/total):.1%}",
            "Worst": f"${worst:,.0f}",
            "P25": f"${p25:,.0f}",
            "Median": f"${p50:,.0f}",
            "P75": f"${p75:,.0f}",
        })
    
    # Identify cheapest (min required lump sum) allocation for each source and compute failures
    # Global
    if "Global" in wide.columns and wide["Global"].notna().any():
        gidx = wide["Global"].idxmin()
        generic_g = wide.loc[gidx, "Allocation"]
        raw_g = inv_lbm.get(generic_g)
        req_amt_g = wide.loc[gidx, "Global"]
        if raw_g and (src_kind in ("LBM", "BOTH")) and df_lbm is not None:
            _failure_stats(df_lbm, raw_g, req_amt_g, "Global")
    # SP500
    if "SP500" in wide.columns and wide["SP500"].notna().any():
        sidx = wide["SP500"].idxmin()
        generic_s = wide.loc[sidx, "Allocation"]
        raw_s = inv_spx.get(generic_s)
        req_amt_s = wide.loc[sidx, "SP500"]
        if raw_s and (src_kind in ("SPX", "BOTH")) and df_spx is not None:
            _failure_stats(df_spx, raw_s, req_amt_s, "SP500")
    
    if failure_rows:
        fail_df = pd.DataFrame(failure_rows)
        # Friendlier allocation label (generic instead of raw code) in output
        def _friendly_alloc(raw_name, source):
            if source == "Global":
                return pretty_lbm.get(raw_name, raw_name)
            else:
                return pretty_spx.get(raw_name, raw_name)
        fail_df["Allocation"] = fail_df.apply(lambda r: _friendly_alloc(r["Allocation"], r["Source"]), axis=1)
        st.data_editor(
            fail_df,
            hide_index=True,
            disabled=True,
            use_container_width=True,
            column_config={
                "Source": st.column_config.TextColumn("Source", help="Data source used."),
                "Allocation": st.column_config.TextColumn("Allocation", help="Cheapest allocation at current settings."),
                "Windows": st.column_config.NumberColumn("Windows", help="Number of valid rolling windows."),
                "Failures": st.column_config.NumberColumn("Failures", help="Count of windows that ended below Goal."),
                "Failure Rate": st.column_config.TextColumn("Failure Rate", help="Failures / Windows."),
                "Worst": st.column_config.TextColumn("Worst", help="Worst ending value among failures."),
                "P25": st.column_config.TextColumn("P25", help="25th percentile of failure endings."),
                "Median": st.column_config.TextColumn("Median", help="Median failure ending value."),
                "P75": st.column_config.TextColumn("P75", help="75th percentile (less-bad failure)."),
            }
        )
    else:
        st.info("No failures at the selected confidence for the cheapest allocation(s).")


    # ------------------------------------------------------------
    # Success Distribution panel (per source, for the CHEAPEST allocation)
    # ------------------------------------------------------------
    st.markdown("#### Success Distribution (when investing the Required Lump Sum)")
    success_rows = []

    def _success_stats(df_src, raw_col, required_amt, label_source):
        evs = simulate_ending_values_lumpsum(df_src[raw_col], int(num_years), int(row_increment))
        if not evs:
            return
        arr = np.array(evs, dtype=float) * float(required_amt)  # ending values ($) when investing Required Lump Sum
        total = int(arr.size)
        succ_mask = arr >= float(goal)
        num_succ = int(succ_mask.sum())
        if num_succ == 0:
            success_rows.append({
                "Source": label_source,
                "Allocation": raw_col,
                "Windows": total,
                "Successes": 0,
                "Success Rate": "0.0%",
                "P25": "",
                "Median": "",
                "P75": "",
                "Best": ""
            })
            return
        succ = arr[succ_mask]
        p25 = np.percentile(succ, 25)
        p50 = np.percentile(succ, 50)
        p75 = np.percentile(succ, 75)
        best = succ.max()
        success_rows.append({
            "Source": label_source,
            "Allocation": raw_col,
            "Windows": total,
            "Successes": num_succ,
            "Success Rate": f"{(num_succ/total):.1%}",
            "P25": f"${p25:,.0f}",
            "Median": f"${p50:,.0f}",
            "P75": f"${p75:,.0f}",
            "Best": f"${best:,.0f}",
        })

    # Compute success stats for the same cheapest allocations
    if "Global" in wide.columns and wide["Global"].notna().any():
        gidx = wide["Global"].idxmin()
        generic_g = wide.loc[gidx, "Allocation"]
        raw_g = inv_lbm.get(generic_g)
        req_amt_g = wide.loc[gidx, "Global"]
        if raw_g and (src_kind in ("LBM", "BOTH")) and df_lbm is not None:
            _success_stats(df_lbm, raw_g, req_amt_g, "Global")
    if "SP500" in wide.columns and wide["SP500"].notna().any():
        sidx = wide["SP500"].idxmin()
        generic_s = wide.loc[sidx, "Allocation"]
        raw_s = inv_spx.get(generic_s)
        req_amt_s = wide.loc[sidx, "SP500"]
        if raw_s and (src_kind in ("SPX", "BOTH")) and df_spx is not None:
            _success_stats(df_spx, raw_s, req_amt_s, "SP500")

    if success_rows:
        succ_df = pd.DataFrame(success_rows)
        # Friendly allocation label
        def _friendly_alloc2(raw_name, source):
            if source == "Global":
                return pretty_lbm.get(raw_name, raw_name)
            else:
                return pretty_spx.get(raw_name, raw_name)
        succ_df["Allocation"] = succ_df.apply(lambda r: _friendly_alloc2(r["Allocation"], r["Source"]), axis=1)
        st.data_editor(
            succ_df,
            hide_index=True,
            disabled=True,
            use_container_width=True,
            column_config={
                "Source": st.column_config.TextColumn("Source", help="Data source used."),
                "Allocation": st.column_config.TextColumn("Allocation", help="Cheapest allocation at current settings."),
                "Windows": st.column_config.NumberColumn("Windows", help="Number of valid rolling windows."),
                "Successes": st.column_config.NumberColumn("Successes", help="Count of windows that ended at/above Goal."),
                "Success Rate": st.column_config.TextColumn("Success Rate", help="Successes / Windows."),
                "P25": st.column_config.TextColumn("P25", help="25th percentile of successful endings."),
                "Median": st.column_config.TextColumn("Median", help="Median successful ending value."),
                "P75": st.column_config.TextColumn("P75", help="75th percentile of successful endings."),
                "Best": st.column_config.TextColumn("Best", help="Best ending value among successes."),
            }
        )
    else:
        st.info("No successes found (this would occur only at very high fees or extreme settings).")


    # Separate charts for Global and SP500, each with min highlight
    chart_df = wide.copy()
    if not chart_df.empty:
        n = len(chart_df)

        # ---- Global chart ----
        if "Global" in chart_df.columns and chart_df["Global"].notna().any():
            g_vals = chart_df["Global"]
            g_colors = ["#9ecae1"] * n  # light blue base for Global
            g_min_pos = g_vals[g_vals.notna()].idxmin()
            try:
                g_i = chart_df.index.get_loc(g_min_pos)
            except Exception:
                g_i = int(g_min_pos) if isinstance(g_min_pos, (int, np.integer)) else None
            if g_i is not None and 0 <= g_i < n:
                g_colors[g_i] = "#2ca02c"  # green highlight for lowest Global
            fig_g = go.Figure()
            fig_g.add_bar(name="Global", x=chart_df["Allocation"], y=g_vals, marker_color=g_colors)
            fig_g.update_layout(
                title="Required Lump Sum — Global",
                xaxis_title="Allocation",
                yaxis_title="Required Lump Sum ($)",
                yaxis=dict(tickformat=",.0f", tickprefix="$"),
                showlegend=False,
            )
            st.plotly_chart(fig_g, use_container_width=True)

        # ---- SP500 chart ----
        if "SP500" in chart_df.columns and chart_df["SP500"].notna().any():
            s_vals = chart_df["SP500"]
            s_colors = ["#3182bd"] * n  # darker blue base for SP500
            s_min_pos = s_vals[s_vals.notna()].idxmin()
            try:
                s_i = chart_df.index.get_loc(s_min_pos)
            except Exception:
                s_i = int(s_min_pos) if isinstance(s_min_pos, (int, np.integer)) else None
            if s_i is not None and 0 <= s_i < n:
                s_colors[s_i] = "#D95F02"  # orange highlight for lowest SP500
            fig_s = go.Figure()
            fig_s.add_bar(name="SP500", x=chart_df["Allocation"], y=s_vals, marker_color=s_colors)
            fig_s.update_layout(
                title="Required Lump Sum — SP500",
                xaxis_title="Allocation",
                yaxis_title="Required Lump Sum ($)",
                yaxis=dict(tickformat=",.0f", tickprefix="$"),
                showlegend=False,
            )
            st.plotly_chart(fig_s, use_container_width=True)

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
        
