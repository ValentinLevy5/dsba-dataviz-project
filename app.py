import streamlit as st
import pandas as pd
import altair as alt
import numpy as np

alt.data_transformers.disable_max_rows()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Media Lens – US Political News Coverage",
    page_icon="📰",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Hero */
    .hero-title {
        font-size: 2.8rem;
        font-weight: 800;
        line-height: 1.15;
        margin-bottom: 0.2rem;
    }
    .hero-subtitle {
        font-size: 1.25rem;
        color: #555;
        margin-bottom: 1.5rem;
    }
    /* Section headers */
    .section-header {
        font-size: 1.6rem;
        font-weight: 700;
        margin-top: 2rem;
        margin-bottom: 0.3rem;
    }
    .section-desc {
        color: #555;
        margin-bottom: 1rem;
        font-size: 1.05rem;
    }
    /* Metric cards */
    .metric-row {
        display: flex;
        gap: 1.2rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        flex: 1;
        background: #f8f9fb;
        border-radius: 12px;
        padding: 1.2rem 1.4rem;
        text-align: center;
    }
    .metric-card .num {
        font-size: 2rem;
        font-weight: 800;
    }
    .metric-card .label {
        font-size: 0.9rem;
        color: #777;
    }
    /* Insight boxes */
    .insight-box {
        background: #eef3ff;
        border-left: 4px solid #4a7cff;
        border-radius: 6px;
        padding: 1rem 1.2rem;
        margin: 1rem 0;
        font-size: 0.98rem;
    }
    /* Footer */
    .footer {
        text-align: center;
        color: #aaa;
        font-size: 0.85rem;
        margin-top: 3rem;
        padding: 1rem 0;
        border-top: 1px solid #eee;
    }
    div[data-testid="stSidebar"] {
        background: #f8f9fb;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Colour palette (consistent across charts)
# ---------------------------------------------------------------------------
OUTLET_COLORS = {
    "NYTimes": "#1f77b4",
    "FoxNews": "#d62728",
    "CNN": "#ff7f0e",
    "WashingtonPost": "#2ca02c",
    "NBCNews": "#9467bd",
    "Politico": "#8c564b",
    "WSJ": "#e377c2",
}

TOPIC_COLORS = {
    "Elections": "#4a7cff",
    "Government": "#ff6b6b",
    "Immigration": "#ffa94d",
    "ForeignPolicy": "#51cf66",
    "Economy": "#845ef7",
    "Political Figures": "#f06595",
}

# ---------------------------------------------------------------------------
# Data loading & cleaning (cached)
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    tone_vol = pd.read_csv("gdelt_us_politics_tone_and_topics_long.csv")
    topic_share = pd.read_csv("gdelt_us_politics_topic_share.csv")

    # 1. Parse dates
    tone_vol["date"] = pd.to_datetime(tone_vol["date"], format="%Y%m%dT%H%M%SZ")
    topic_share["date"] = pd.to_datetime(topic_share["date"], format="%Y%m%dT%H%M%SZ")

    # 2. Remove 2026 data (only 1 incomplete day)
    tone_vol = tone_vol[tone_vol["year"] != 2026].copy()
    topic_share = topic_share[topic_share["year"] != 2026].copy()

    # 3. Null-out missing data: when volume == 0 the outlet had no articles,
    #    so the corresponding tone value is meaningless and must also be null.
    #    Build a set of (date, outlet, topic) keys where volume is zero.
    vol_mask = (tone_vol["metric"] == "volume") & (tone_vol["value"] == 0)
    missing_keys = tone_vol.loc[vol_mask, ["date", "outlet", "topic"]]

    #    Mark volume == 0 rows as NaN
    tone_vol.loc[vol_mask, "value"] = pd.NA

    #    Also mark the matching tone rows as NaN
    tone_idx = tone_vol[tone_vol["metric"] == "tone"].merge(
        missing_keys, on=["date", "outlet", "topic"], how="inner"
    ).index
    # Use merge indicator to find tone rows whose (date, outlet, topic) is in missing_keys
    tone_rows = tone_vol[tone_vol["metric"] == "tone"].copy()
    tone_rows["_drop"] = False
    merged = tone_rows[["date", "outlet", "topic"]].reset_index().merge(
        missing_keys, on=["date", "outlet", "topic"], how="inner"
    )
    tone_vol.loc[merged["index"], "value"] = pd.NA

    #    Drop all NaN value rows
    tone_vol = tone_vol.dropna(subset=["value"]).copy()

    topic_share.loc[topic_share["value"] == 0, "value"] = pd.NA
    topic_share = topic_share.dropna(subset=["value"]).copy()
    # Also drop rows where topic_share is NaN (caused by total_volume == 0)
    topic_share = topic_share.dropna(subset=["topic_share"]).copy()

    # 4. Cap extreme tone outliers at +/- 10 (artifacts from very low article counts)
    tone_vol.loc[tone_vol["metric"] == "tone", "value"] = tone_vol.loc[
        tone_vol["metric"] == "tone", "value"
    ].clip(lower=-10, upper=10)

    # 5. Remove total blackout date (2025-12-06 – GDELT ingestion failure)
    blackout = pd.Timestamp("2025-12-06")
    tone_vol = tone_vol[tone_vol["date"] != blackout]
    topic_share = topic_share[topic_share["date"] != blackout]

    # 6. Flag outlet reliability – mark outlets with >50% zero-days in a month
    #    as unreliable for that period. We handle this by simply keeping cleaned data;
    #    the sidebar lets users filter outlets in/out as needed.

    return tone_vol, topic_share


tone_vol, topic_share = load_data()

# Split tone and volume
tone_df = tone_vol[tone_vol["metric"] == "tone"].copy()
volume_df = tone_vol[tone_vol["metric"] == "volume"].copy()

OUTLETS = sorted(tone_df["outlet"].unique())
TOPICS = sorted(tone_df["topic"].unique())
YEARS = sorted(tone_df["year"].unique())

# ---------------------------------------------------------------------------
# Sidebar – Global filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Filters")
    year_range = st.slider(
        "Year range",
        min_value=int(min(YEARS)),
        max_value=int(max(YEARS)),
        value=(2017, 2025),
    )
    selected_outlets = st.multiselect(
        "Outlets",
        OUTLETS,
        default=OUTLETS,
    )
    selected_topics = st.multiselect(
        "Topics",
        TOPICS,
        default=TOPICS,
    )
    smoothing = st.select_slider(
        "Smoothing window (days)",
        options=[1, 7, 14, 30, 60, 90],
        value=30,
    )
    st.markdown("---")
    st.markdown("### Data Quality")
    st.markdown(
        "<small>"
        "**Cleaning applied:** removed 2026 (incomplete), replaced zero-value "
        "gaps with NaN, capped tone outliers at +/-10, dropped the 2025-12-06 "
        "blackout date.<br><br>"
        "**Note:** WSJ data degrades from Feb 2024; Politico & WashingtonPost "
        "drop out from Sep 2024. NYTimes is partially degraded from late 2024. "
        "Consider narrowing the year range or deselecting these outlets for "
        "the most recent period."
        "</small>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown(
        "<small>Data from the <b>GDELT Project</b> (2017-2025). "
        "Tone values represent average sentiment; volume is the "
        "normalized share of total news output.</small>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------
def apply_filters(df):
    mask = (
        (df["year"] >= year_range[0])
        & (df["year"] <= year_range[1])
        & (df["outlet"].isin(selected_outlets))
        & (df["topic"].isin(selected_topics))
    )
    return df[mask].copy()


tone_f = apply_filters(tone_df)
volume_f = apply_filters(volume_df)
topic_share_f = apply_filters(topic_share)

# Helper: rolling smooth
def smooth(df, value_col="value", window=30):
    if window <= 1:
        return df
    df = df.sort_values("date")
    df[value_col] = (
        df.groupby(["outlet", "topic"])[value_col]
        .transform(lambda x: x.rolling(window, min_periods=1).mean())
    )
    return df


tone_smooth = smooth(tone_f.copy(), "value", smoothing)
volume_smooth = smooth(volume_f.copy(), "value", smoothing)

# ═══════════════════════════════════════════════════════════════════════════
# HERO SECTION
# ═══════════════════════════════════════════════════════════════════════════
st.markdown('<p class="hero-title">Media Lens</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-subtitle">'
    "Exploring how America's top news outlets cover politics — "
    "what they talk about, and the tone they use."
    "</p>",
    unsafe_allow_html=True,
)

st.markdown(
    "Political news shapes public opinion, yet different outlets can paint "
    "vastly different pictures of the same events. This tool lets you explore "
    "**9 years** of coverage data from **7 major US news outlets** across "
    "**6 key political topics**, powered by the GDELT Project's global news "
    "monitoring database."
)

# Key metrics
n_articles_proxy = len(volume_f)
st.markdown(f"""
<div class="metric-row">
    <div class="metric-card">
        <div class="num">7</div>
        <div class="label">News Outlets</div>
    </div>
    <div class="metric-card">
        <div class="num">6</div>
        <div class="label">Political Topics</div>
    </div>
    <div class="metric-card">
        <div class="num">9</div>
        <div class="label">Years of Data</div>
    </div>
    <div class="metric-card">
        <div class="num">270K+</div>
        <div class="label">Daily Measurements</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: Topic Evolution Heatmap  ★ MAIN VISUALIZATION ★
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">1 &middot; Topic Evolution Heatmap</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "How has the tone for each political topic changed over the decade? "
    "Darker reds signal more negative coverage. Click a cell to drill down."
    "</p>",
    unsafe_allow_html=True,
)

TOPIC_ORDER = [
    "Elections", "Government", "Immigration",
    "ForeignPolicy", "Economy", "Political Figures",
]

# --- Aggregate: mean tone per topic × year (across selected outlets) ---
topic_year_tone = (
    tone_f.groupby(["year", "topic"])["value"]
    .mean()
    .reset_index()
)

# Also compute per-outlet breakdown for the detail tooltip
topic_year_outlet = (
    tone_f.groupby(["year", "topic", "outlet"])["value"]
    .mean()
    .reset_index()
)
# Compute std-dev and data-point count per cell for richer tooltips
topic_year_stats = (
    tone_f.groupby(["year", "topic"])
    .agg(
        avg_tone=("value", "mean"),
        std_tone=("value", "std"),
        n_days=("value", "count"),
    )
    .reset_index()
)
topic_year_stats["std_tone"] = topic_year_stats["std_tone"].fillna(0)

# Compute min/max outlet per cell
outlet_extremes = (
    topic_year_outlet.groupby(["year", "topic"])
    .apply(
        lambda g: pd.Series({
            "most_negative_outlet": g.loc[g["value"].idxmin(), "outlet"],
            "most_negative_val": g["value"].min(),
            "most_positive_outlet": g.loc[g["value"].idxmax(), "outlet"],
            "most_positive_val": g["value"].max(),
        }),
        include_groups=False,
    )
    .reset_index()
)

topic_year_rich = topic_year_stats.merge(outlet_extremes, on=["year", "topic"])

# Also compute year-over-year change
topic_year_rich = topic_year_rich.sort_values(["topic", "year"])
topic_year_rich["prev_tone"] = topic_year_rich.groupby("topic")["avg_tone"].shift(1)
topic_year_rich["yoy_change"] = topic_year_rich["avg_tone"] - topic_year_rich["prev_tone"]
topic_year_rich["yoy_change"] = topic_year_rich["yoy_change"].fillna(0)
topic_year_rich["yoy_label"] = topic_year_rich["yoy_change"].apply(
    lambda x: f"+{x:.2f}" if x > 0 else f"{x:.2f}"
)

# --- Interactive click selection ---
click_sel = alt.selection_point(fields=["topic", "year"])

heatmap_rects = (
    alt.Chart(topic_year_rich)
    .mark_rect(cornerRadius=6, stroke="#fff", strokeWidth=2.5)
    .encode(
        x=alt.X(
            "year:O",
            title="Year",
            axis=alt.Axis(labelAngle=0, labelFontSize=14, titleFontSize=14),
        ),
        y=alt.Y(
            "topic:N",
            title=None,
            sort=TOPIC_ORDER,
            axis=alt.Axis(labelFontSize=14),
        ),
        color=alt.Color(
            "avg_tone:Q",
            title="Avg Tone",
            scale=alt.Scale(
                scheme="redyellowgreen",
                domainMid=0,
            ),
            legend=alt.Legend(
                title="Very Negative ← Tone → Positive",
                orient="bottom",
                direction="horizontal",
                gradientLength=350,
                titleFontSize=11,
            ),
        ),
        strokeWidth=alt.condition(click_sel, alt.value(3), alt.value(0)),
        stroke=alt.condition(click_sel, alt.value("#222"), alt.value("#fff")),
        tooltip=[
            alt.Tooltip("topic:N", title="Topic"),
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("avg_tone:Q", format=".2f", title="Avg Tone"),
            alt.Tooltip("std_tone:Q", format=".2f", title="Std Dev"),
            alt.Tooltip("n_days:Q", title="Data Points"),
            alt.Tooltip("yoy_label:N", title="Year-over-Year"),
            alt.Tooltip("most_negative_outlet:N", title="Most Negative Outlet"),
            alt.Tooltip("most_negative_val:Q", format=".2f", title="Its Tone"),
            alt.Tooltip("most_positive_outlet:N", title="Most Positive Outlet"),
            alt.Tooltip("most_positive_val:Q", format=".2f", title="Its Tone"),
        ],
    )
    .add_params(click_sel)
)

heatmap_text = (
    alt.Chart(topic_year_rich)
    .mark_text(fontSize=15, fontWeight="bold")
    .encode(
        x=alt.X("year:O"),
        y=alt.Y("topic:N", sort=TOPIC_ORDER),
        text=alt.Text("avg_tone:Q", format=".1f"),
        color=alt.condition(
            alt.datum.avg_tone > -1.0,
            alt.value("#1a1a1a"),
            alt.value("white"),
        ),
    )
)

st.altair_chart(
    (heatmap_rects + heatmap_text).properties(
        height=420,
        title=alt.Title(
            text="How tone for each topic changed over the decade",
            subtitle="2020 & 2024 show darker colors (election years = more negative coverage)",
            fontSize=16,
            subtitleFontSize=12,
            subtitleColor="#777",
            anchor="middle",
        ),
    ),
    use_container_width=True,
)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> 2020 and 2024 (election years) show the darkest colors across "
    "nearly every topic — political coverage becomes measurably more negative during "
    "campaign cycles. Immigration consistently carries the most negative tone. "
    "Hover over any cell for a detailed breakdown including which outlet was most/least negative."
    "</div>",
    unsafe_allow_html=True,
)

# --- Drill-down: per-outlet bar chart for selected cell ---
st.markdown(
    '<p class="section-desc">'
    "Click any cell above to see the outlet-by-outlet breakdown below."
    "</p>",
    unsafe_allow_html=True,
)

drill_bars = (
    alt.Chart(topic_year_outlet)
    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X(
            "outlet:N",
            title="Outlet",
            sort=alt.EncodingSortField(field="value", order="ascending"),
            axis=alt.Axis(labelAngle=-30, labelFontSize=12),
        ),
        y=alt.Y("value:Q", title="Avg Tone", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("topic:N", title="Topic"),
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("value:Q", format=".2f", title="Avg Tone"),
        ],
    )
    .transform_filter(click_sel)
    .properties(height=280, title="Outlet Breakdown (click a heatmap cell)")
)

drill_zero = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(strokeDash=[4, 4], color="gray")
    .encode(y="y:Q")
)

st.altair_chart(drill_bars + drill_zero, use_container_width=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: Brush & Zoom Cross-Filter
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">2 &middot; Brush &amp; Explore: Tone Over Time</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "Drag to select a time range on the top chart — the bar chart below instantly "
    "updates to show average outlet tone for that period. Click the legend to isolate outlets."
    "</p>",
    unsafe_allow_html=True,
)

# Monthly aggregation for the line chart (keeps data manageable)
tone_monthly = tone_f.copy()
tone_monthly["month"] = tone_monthly["date"].dt.to_period("M").dt.to_timestamp()
tone_monthly_agg = (
    tone_monthly.groupby(["month", "outlet"])["value"]
    .mean()
    .reset_index()
)

# Shared brush selection
brush = alt.selection_interval(encodings=["x"])
legend_sel = alt.selection_point(fields=["outlet"], bind="legend")

# Top chart: line with brush
brush_line = (
    alt.Chart(tone_monthly_agg)
    .mark_line(strokeWidth=2)
    .encode(
        x=alt.X("month:T", title="Date"),
        y=alt.Y("value:Q", title="Avg Tone", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        opacity=alt.condition(legend_sel, alt.value(1), alt.value(0.1)),
        tooltip=["month:T", "outlet:N", alt.Tooltip("value:Q", format=".2f", title="Tone")],
    )
    .properties(height=300)
    .add_params(brush, legend_sel)
)

brush_zero = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(strokeDash=[4, 4], color="gray")
    .encode(y="y:Q")
)

# Bottom chart: bar filtered by brush
brush_bars = (
    alt.Chart(tone_monthly_agg)
    .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
    .encode(
        x=alt.X(
            "outlet:N",
            title="Outlet",
            sort=alt.EncodingSortField(field="value", order="ascending"),
            axis=alt.Axis(labelAngle=-30),
        ),
        y=alt.Y("mean(value):Q", title="Avg Tone (selected period)", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "outlet:N",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("mean(value):Q", format=".2f", title="Avg Tone"),
        ],
    )
    .transform_filter(brush)
    .properties(height=250, title="Outlet tone for brushed period")
)

brush_bar_zero = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(strokeDash=[4, 4], color="gray")
    .encode(y="y:Q")
)

cross_filter = alt.vconcat(
    brush_line + brush_zero,
    brush_bars + brush_bar_zero,
).resolve_legend(color="independent")

st.altair_chart(cross_filter, use_container_width=True)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> Drag across any time window to compare outlets. Notice how "
    "during election periods (e.g. late 2019–2020), all outlets become more negative, "
    "but the gap between them widens — revealing divergent editorial stances."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: Topic share over time
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">3 &middot; What Topics Dominate the News?</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "See how the share of coverage across political topics shifts over time for each outlet."
    "</p>",
    unsafe_allow_html=True,
)

topic_outlet_pick = st.selectbox(
    "Select an outlet to explore its topic breakdown:",
    selected_outlets,
    index=0,
)

ts_outlet = topic_share_f[topic_share_f["outlet"] == topic_outlet_pick].copy()

# Monthly aggregation for cleaner stacked area
ts_outlet["month"] = ts_outlet["date"].dt.to_period("M").dt.to_timestamp()
ts_monthly = (
    ts_outlet.groupby(["month", "topic"])["topic_share"]
    .mean()
    .reset_index()
)

topic_selection = alt.selection_point(fields=["topic"], bind="legend")

stacked_area = (
    alt.Chart(ts_monthly)
    .mark_area()
    .encode(
        x=alt.X("month:T", title="Date"),
        y=alt.Y(
            "topic_share:Q",
            title="Share of Coverage",
            stack="normalize",
            axis=alt.Axis(format="%"),
        ),
        color=alt.Color(
            "topic:N",
            title="Topic",
            scale=alt.Scale(
                domain=list(TOPIC_COLORS.keys()),
                range=list(TOPIC_COLORS.values()),
            ),
        ),
        opacity=alt.condition(topic_selection, alt.value(1), alt.value(0.2)),
        tooltip=[
            "month:T",
            "topic:N",
            alt.Tooltip("topic_share:Q", format=".1%", title="Share"),
        ],
    )
    .add_params(topic_selection)
    .properties(height=400)
    .interactive()
)

st.altair_chart(stacked_area, use_container_width=True)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> Government and Elections tend to dominate coverage across all outlets, "
    "but their relative share shifts dramatically around election years. Immigration coverage "
    "spikes during policy debates and border crises."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: Tone Distribution Box Plots
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">4 &middot; Tone Distribution by Outlet</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "Averages can hide a lot. These box plots show the full spread of monthly "
    "tone values — revealing which outlets are volatile and which are consistent."
    "</p>",
    unsafe_allow_html=True,
)

# Monthly tone per outlet for distribution
tone_box = tone_f.copy()
tone_box["month"] = tone_box["date"].dt.to_period("M").dt.to_timestamp()
tone_box_monthly = (
    tone_box.groupby(["month", "outlet"])["value"]
    .mean()
    .reset_index()
)

box_plot = (
    alt.Chart(tone_box_monthly)
    .mark_boxplot(extent="min-max", size=40)
    .encode(
        x=alt.X(
            "outlet:N",
            title="Outlet",
            sort=alt.EncodingSortField(field="value", op="median", order="ascending"),
            axis=alt.Axis(labelAngle=-30, labelFontSize=12),
        ),
        y=alt.Y("value:Q", title="Monthly Avg Tone", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
            legend=None,
        ),
    )
    .properties(height=380)
)

# Overlay strip/jitter for individual months
strip = (
    alt.Chart(tone_box_monthly)
    .mark_circle(size=20, opacity=0.3)
    .encode(
        x=alt.X("outlet:N", sort=alt.EncodingSortField(field="value", op="median", order="ascending")),
        y=alt.Y("value:Q"),
        color=alt.Color(
            "outlet:N",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("month:T", title="Month"),
            alt.Tooltip("value:Q", format=".2f", title="Tone"),
        ],
    )
)

st.altair_chart(box_plot + strip, use_container_width=True)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> Some outlets (like WSJ) show a much wider spread in tone, meaning their "
    "coverage varies greatly month to month. Others are more consistently negative. "
    "The individual dots let you spot the extreme months."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: Diverging Bars – Deviation from Average
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">5 &middot; How Each Outlet Deviates from the Average</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "For each topic, how does each outlet compare to the overall average? "
    "Bars extending left are more negative than average; bars extending right are less negative."
    "</p>",
    unsafe_allow_html=True,
)

# Compute per-outlet, per-topic avg tone and deviation from topic mean
outlet_topic_tone = (
    tone_f.groupby(["outlet", "topic"])["value"]
    .mean()
    .reset_index()
    .rename(columns={"value": "outlet_tone"})
)
topic_avg = (
    tone_f.groupby("topic")["value"]
    .mean()
    .reset_index()
    .rename(columns={"value": "topic_avg"})
)
deviation_df = outlet_topic_tone.merge(topic_avg, on="topic")
deviation_df["deviation"] = deviation_df["outlet_tone"] - deviation_df["topic_avg"]
deviation_df["direction"] = np.where(
    deviation_df["deviation"] >= 0, "Less negative", "More negative"
)

diverging = (
    alt.Chart(deviation_df)
    .mark_bar(cornerRadius=3)
    .encode(
        y=alt.Y(
            "outlet:N",
            title=None,
            sort=alt.EncodingSortField(field="deviation", order="ascending"),
            axis=alt.Axis(labelFontSize=11),
        ),
        x=alt.X(
            "deviation:Q",
            title="Deviation from topic average",
            axis=alt.Axis(format=".2f"),
        ),
        color=alt.Color(
            "direction:N",
            title="Relative tone",
            scale=alt.Scale(
                domain=["More negative", "Less negative"],
                range=["#d62728", "#2ca02c"],
            ),
            legend=alt.Legend(orient="bottom"),
        ),
        row=alt.Row(
            "topic:N",
            title=None,
            sort=TOPIC_ORDER,
            header=alt.Header(labelFontSize=13, labelFontWeight="bold"),
        ),
        tooltip=[
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("topic:N", title="Topic"),
            alt.Tooltip("outlet_tone:Q", format=".2f", title="Outlet Tone"),
            alt.Tooltip("topic_avg:Q", format=".2f", title="Topic Avg"),
            alt.Tooltip("deviation:Q", format=".2f", title="Deviation"),
        ],
    )
    .properties(height=80, width=500)
)

# Zero reference line
div_zero = (
    alt.Chart(pd.DataFrame({"x": [0]}))
    .mark_rule(strokeDash=[4, 4], color="#666")
    .encode(x="x:Q")
)

st.altair_chart(diverging + div_zero, use_container_width=True)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> Fox News tends to be more negative than average on Immigration "
    "and Foreign Policy, while Economy coverage shows the smallest outlet-to-outlet divergence. "
    "This reveals which topics drive the most editorial disagreement."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6: Topic deep-dive – pick a topic, compare outlets
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">6 &middot; Deep Dive: Compare Outlets on a Topic</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "Select a topic to see how different outlets' tone and volume compare side-by-side."
    "</p>",
    unsafe_allow_html=True,
)

deep_topic = st.selectbox("Choose a topic:", selected_topics, index=0, key="deep_topic")

# --- Tone comparison ---
deep_tone = tone_smooth[tone_smooth["topic"] == deep_topic].copy()
deep_tone_agg = deep_tone.groupby(["date", "outlet"])["value"].mean().reset_index()

outlet_sel2 = alt.selection_point(fields=["outlet"], bind="legend")

deep_tone_chart = (
    alt.Chart(deep_tone_agg)
    .mark_line(strokeWidth=2)
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("value:Q", title="Tone", scale=alt.Scale(zero=False)),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        opacity=alt.condition(outlet_sel2, alt.value(1), alt.value(0.1)),
        tooltip=["date:T", "outlet:N", alt.Tooltip("value:Q", format=".2f")],
    )
    .add_params(outlet_sel2)
    .properties(height=350, title=f"Tone over Time – {deep_topic}")
    .interactive()
)

zero_line2 = (
    alt.Chart(pd.DataFrame({"y": [0]}))
    .mark_rule(strokeDash=[4, 4], color="gray")
    .encode(y="y:Q")
)

st.altair_chart(deep_tone_chart + zero_line2, use_container_width=True)

# --- Volume comparison (bar chart by year) ---
deep_vol = volume_f[volume_f["topic"] == deep_topic].copy()
deep_vol_year = deep_vol.groupby(["year", "outlet"])["value"].mean().reset_index()

vol_bar = (
    alt.Chart(deep_vol_year)
    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
    .encode(
        x=alt.X("year:O", title="Year"),
        y=alt.Y("value:Q", title="Avg Volume (normalized)"),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        xOffset="outlet:N",
        tooltip=["year:O", "outlet:N", alt.Tooltip("value:Q", format=".4f", title="Volume")],
    )
    .properties(height=350, title=f"Average Coverage Volume by Year – {deep_topic}")
    .interactive()
)

st.altair_chart(vol_bar, use_container_width=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7: Outlet Sentiment Ranking – Bump Chart
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">7 &middot; Outlet Sentiment Rankings Over Time</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="section-desc">'
    "Which outlet is the most negative each year? This bump chart ranks outlets from "
    "most negative (rank 1, top) to least negative. Watch the lines cross as rankings shift."
    "</p>",
    unsafe_allow_html=True,
)

# Compute yearly avg tone per outlet, then rank
yearly_tone = (
    tone_f.groupby(["year", "outlet"])["value"]
    .mean()
    .reset_index()
)
yearly_tone["rank"] = yearly_tone.groupby("year")["value"].rank(method="min").astype(int)

outlet_sel3 = alt.selection_point(fields=["outlet"], bind="legend")

bump_lines = (
    alt.Chart(yearly_tone)
    .mark_line(strokeWidth=3)
    .encode(
        x=alt.X("year:O", title="Year", axis=alt.Axis(labelAngle=0, labelFontSize=13)),
        y=alt.Y(
            "rank:O",
            title="Rank (1 = most negative)",
            sort="ascending",
            axis=alt.Axis(labelFontSize=13),
        ),
        color=alt.Color(
            "outlet:N",
            title="Outlet",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        opacity=alt.condition(outlet_sel3, alt.value(1), alt.value(0.15)),
        tooltip=[
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("rank:Q", title="Rank"),
            alt.Tooltip("value:Q", format=".2f", title="Avg Tone"),
        ],
    )
    .add_params(outlet_sel3)
)

bump_points = (
    alt.Chart(yearly_tone)
    .mark_circle(size=100)
    .encode(
        x=alt.X("year:O"),
        y=alt.Y("rank:O", sort="ascending"),
        color=alt.Color(
            "outlet:N",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        opacity=alt.condition(outlet_sel3, alt.value(1), alt.value(0.15)),
        tooltip=[
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("outlet:N", title="Outlet"),
            alt.Tooltip("rank:Q", title="Rank"),
            alt.Tooltip("value:Q", format=".2f", title="Avg Tone"),
        ],
    )
)

# Labels on the right side (last year)
max_year = yearly_tone["year"].max()
bump_labels = (
    alt.Chart(yearly_tone[yearly_tone["year"] == max_year])
    .mark_text(align="left", dx=8, fontSize=12, fontWeight="bold")
    .encode(
        x=alt.X("year:O"),
        y=alt.Y("rank:O", sort="ascending"),
        text=alt.Text("outlet:N"),
        color=alt.Color(
            "outlet:N",
            scale=alt.Scale(
                domain=list(OUTLET_COLORS.keys()),
                range=list(OUTLET_COLORS.values()),
            ),
        ),
        opacity=alt.condition(outlet_sel3, alt.value(1), alt.value(0.15)),
    )
)

st.altair_chart(
    (bump_lines + bump_points + bump_labels).properties(height=400),
    use_container_width=True,
)

st.markdown(
    '<div class="insight-box">'
    "<b>Key insight:</b> Rankings are not static — outlets swap positions frequently. "
    "An outlet that was the most negative one year can become moderate the next, "
    "suggesting tone is driven by editorial choices around specific events rather than "
    "a fixed institutional bias."
    "</div>",
    unsafe_allow_html=True,
)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# KEY TAKEAWAYS
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<p class="section-header">Key Takeaways</p>',
    unsafe_allow_html=True,
)

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    **Negativity dominates political coverage.** Across all 7 outlets and 6 topics,
    the average tone of political reporting is consistently negative. This reflects
    a well-documented pattern in media studies, but seeing it quantified across
    outlets makes the scale clear.

    **Coverage priorities differ.** While Government and Elections dominate everywhere,
    the relative attention given to Immigration, Economy, and Foreign Policy varies
    meaningfully between outlets — reflecting different editorial priorities and
    audience expectations.
    """)

with col2:
    st.markdown("""
    **Election years amplify negativity.** Sentiment dips are most pronounced around
    election cycles (2018, 2020, 2024), suggesting that political campaign coverage
    drives more negative framing.

    **No outlet is truly "neutral".** Every outlet in this dataset shows a measurable
    negative bias in political tone, though the degree varies. This matters for media
    literacy — understanding that all sources carry some sentiment framing helps
    students consume news more critically.
    """)

# ═══════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════
st.markdown(
    '<div class="footer">'
    "Media Lens &middot; DSBA Data Visualization Project 2026 &middot; "
    "Data from the GDELT Project &middot; Built with Streamlit & Altair"
    "</div>",
    unsafe_allow_html=True,
)
