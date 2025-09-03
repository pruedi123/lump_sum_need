

import numpy as np
import pandas as pd
import streamlit as st

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
# App: Required Lump Sum by Allocation (Worksheet‑Driven)
# Goal: For each allocation (LBM columns), compute the required single
#       upfront investment to reach a target (e.g., $1,000,000) with a
#       chosen confidence over N years using historical factor windows.
##############################

st.set_page_config(layout="wide")
st.title("Required Lump Sum by Allocation (Worksheet‑Driven)")
st.caption("Computes the one‑time contribution needed to reach your goal with the selected confidence using historical factor windows.")

# ------------------------------
# Inputs
# ------------------------------
file_path = st.text_input("Excel file path", value="all_portfolio_annual_factor_20_bps.xlsx")
sheet_name = st.text_input("Worksheet name", value="allocation_factors")

col1, col2, col3 = st.columns(3)
with col1:
    goal = st.number_input("Goal ($)", min_value=1, step=1000, value=1_000_000)
with col2:
    num_years = st.number_input("Years", min_value=1, max_value=60, value=30)
with col3:
    conf_pct = st.slider("Confidence (%)", min_value=50, max_value=100, value=90)
    confidence_level = conf_pct / 100.0

# Fixed: data is monthly, so step 12 rows per simulated year
row_increment = 12

st.divider()

# ------------------------------
# Load worksheet
# ------------------------------
df = None
try:
    df = pd.read_excel(file_path, sheet_name=sheet_name)
    st.success("Worksheet loaded.")
except Exception as e:
    st.error(f"Error loading file/sheet: {e}")

# ------------------------------
# Prepare columns (detect allocations, coerce numeric)
# ------------------------------
allocation_cols = []
if df is not None:
    df.columns = df.columns.astype(str).str.strip().str.replace("  ", " ")
    allocation_cols = [c for c in df.columns if c.upper().startswith("LBM ")]
    for c in allocation_cols:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    if not allocation_cols:
        st.warning("No allocation columns found (expected headers starting with 'LBM ').")

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
if st.button("Compute required lump sum"):
    if df is None or not allocation_cols:
        st.error("Load a worksheet with allocation columns first.")
    else:
        rows = []
        for col in allocation_cols:
            evs = simulate_ending_values_lumpsum(df[col], int(num_years), int(row_increment))
            if not evs:
                req = np.nan
                note = "No valid windows (NaNs or insufficient length)"
            else:
                req = required_lumpsum_for_goal(evs, float(goal), float(confidence_level))
                note = ""
            rows.append({
                "Allocation": col.strip(),
                "Required Lump Sum": np.nan if pd.isna(req) else float(req),
                "Valid Windows": len(evs),
                "Note": note,
            })
        results = pd.DataFrame(rows)

        # Order & pretty labels
        order = [
            'LBM 100E','LBM 90E','LBM 80E','LBM 70E','LBM 60E',
            'LBM 50E','LBM 40E','LBM 30E','LBM 20E','LBM 10E','LBM 100F'
        ]
        pretty = {
            'LBM 100E': '100% Equity','LBM 90E': '90% Equity','LBM 80E': '80% Equity','LBM 70E': '70% Equity',
            'LBM 60E': '60% Equity','LBM 50E': '50% Equity','LBM 40E': '40% Equity','LBM 30E': '30% Equity',
            'LBM 20E': '20% Equity','LBM 10E': '10% Equity','LBM 100F': '100% Fixed'
        }
        results["_key"] = pd.Categorical(results["Allocation"], categories=order, ordered=True)
        results = results.sort_values("_key").drop(columns=["_key"]).copy()
        results["Allocation"] = results["Allocation"].map(pretty).fillna(results["Allocation"])  # fallback

        # Prepare a copy for display with currency formatting
        display_results = results.copy()
        if "Required Lump Sum" in display_results.columns:
            display_results["Required Lump Sum"] = display_results["Required Lump Sum"].apply(
                lambda x: f"${x:,.0f}" if pd.notna(x) else ""
            )

        st.subheader("Results")
        st.write(display_results)

        # Bar chart
        plot_df = results.dropna(subset=["Required Lump Sum"]).copy()
        if not plot_df.empty:
            min_val = plot_df["Required Lump Sum"].min()
            colors = ["green" if v == min_val else "blue" for v in plot_df["Required Lump Sum"]]
            fig = go.Figure(data=[go.Bar(
                x=plot_df['Allocation'],
                y=plot_df['Required Lump Sum'],
                marker_color=colors,
                text=[f"${v:,.0f}" for v in plot_df['Required Lump Sum']],
                textposition='outside'
            )])
            fig.update_layout(
                title="Required Lump Sum by Allocation",
                xaxis_title="Allocation",
                yaxis_title="Required Lump Sum ($)",
                uniformtext_minsize=8,
                uniformtext_mode='hide',
                yaxis=dict(tickformat=",.0f", tickprefix="$")
            )
            st.plotly_chart(fig, use_container_width=True)

        # Download (CSV with raw numeric values)
        csv = results.to_csv(index=False)
        st.download_button("Download CSV", data=csv, file_name="required_lumpsum_by_allocation.csv", mime="text/csv")





# ------------------------------
        
st.write("""
---
## Important Disclosures & Disclaimers

**Affiliation & Sponsorship**
- While **Paul Ruedi** is the CEO of **Ruedi Wealth Management, Inc.**, this website and the educational calculators/tools provided here were **created by Paul Ruedi in his personal capacity**. **Ruedi Wealth Management, Inc. is not affiliated with this website or with these educational tools**, and no content on this site should be interpreted as reflecting the views, advice, or services of Ruedi Wealth Management, Inc.

**Educational Use Only (Not Advice)**
- These tools are **for educational and informational purposes only** and are intended to help users explore financial concepts and the impact of different assumptions.
- **Nothing here constitutes financial, investment, tax, accounting, or legal advice**, nor a recommendation or solicitation to buy, sell, or hold any security or strategy.
- Using this site **does not create an advisor-client relationship** or any fiduciary obligation.

**Data Sources, Accuracy & Third-Party Relationships**
- Data used in these tools is **believed to be accurate but is not guaranteed**. Errors, omissions, or delays may occur; calculations and outputs may contain mistakes.
- The return series used by some tools are **based in part on the Dimensional Fund Advisors (“Dimensional”) Returns Program**. **Dimensional Fund Advisors has no affiliation with this website or the tools**, does not review or endorse the content, and assumes no responsibility for its use or accuracy.
- Data, assumptions, and methodologies may be updated without notice.

**Methodology & Limitations**
- Projections, scenarios, and illustrations may include **hypothetical, backtested, or simulated results**. These **do not represent actual trading** and **may under- or over-state** the impact of market conditions, liquidity, transaction costs, taxes, cash flows, and investor behavior.
- Outputs may rely on **historical windows** and simplified models that **cannot account for future market conditions** or all real-world frictions.
- “Confidence” or “probability” figures (when shown) generally reflect the **share of historical periods** in which a result was achieved under the stated assumptions and **are not a prediction** of your personal outcome.

**Indexes & Benchmarks**
- **Indexes are unmanaged and do not incur fees or expenses. You cannot invest directly in an index.** Index performance **does not** represent the performance of any actual, investable product and may differ significantly from investor experience.
- Benchmarks may not be appropriate comparisons for your specific situation.

**Fees, Expenses, Taxes & Other Frictions**
- **Unless explicitly stated otherwise, results are shown **_before_** investment expenses**, advisory fees, trading costs, bid-ask spreads, platform fees, taxes, and other frictions. **Incorporating these costs would reduce returns and may materially change outcomes**.
- Tax considerations are **highly individualized** and **not modeled** unless expressly noted.

**No Guarantee; Past Performance**
- **Past performance is not a guarantee (or reliable indicator) of future results.** No result, output, or scenario here **guarantees** that any objective will be achieved.
- Markets are uncertain and outcomes can differ **significantly** from illustrations.

**No Warranty; Limitation of Liability**
- The tools, data, and outputs are provided **“as is” and “as available,” without warranties of any kind**, express or implied.
- **You are solely responsible** for any decisions you make using these tools. The creator(s) and any associated parties **disclaim liability** for losses or damages arising from use or reliance on the content or outputs.

**Jurisdiction & Eligibility**
- Content is intended for general U.S. audiences and may not be appropriate in all jurisdictions. Use where lawful and appropriate.

**Talk to a Professional**
- Before acting on any information, **consider your personal circumstances** and **consult a qualified financial advisor, tax professional, or attorney**.

---
**Bottom line:** These tools are designed to **help you learn**, not to provide personalized financial advice or predict future outcomes.
""")




# ------------------------------

