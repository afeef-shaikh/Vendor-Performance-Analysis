import streamlit as st
import pandas as pd
import plotly.express as px

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Executive Vendor Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. THEME & CSS ENGINE ---
with st.sidebar:
    st.header("Appearance")
    theme_mode = st.toggle("Dark Mode", value=True)

if theme_mode:
    main_bg = "#0e1117"
    card_bg = "#1f2937" # Darker blue-grey
    text_color = "#f9fafb"
    sub_text_color = "#9ca3af"
    border_color = "#374151"
    chart_template = "plotly_dark"
    accent_gradient = "linear-gradient(90deg, #3B82F6 0%, #8B5CF6 100%)"
else:
    main_bg = "#f3f4f6"
    card_bg = "#ffffff"
    text_color = "#111827"
    sub_text_color = "#6b7280"
    border_color = "#e5e7eb"
    chart_template = "plotly_white"
    accent_gradient = "linear-gradient(90deg, #2563EB 0%, #7C3AED 100%)"

# CUSTOM CSS FOR "CRAZY" UI
st.markdown(f"""
    <style>
    /* Main Background */
    .stApp {{
        background-color: {main_bg};
        color: {text_color};
    }}
    
    /* Card Styling */
    div.css-1r6slb0, div.stDataFrame, div[data-testid="stMetric"] {{
        background-color: {card_bg};
        border: 1px solid {border_color};
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }}
    
    /* Headings */
    h1, h2, h3 {{
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        letter-spacing: -0.025em;
    }}
    h1 {{
        background: {accent_gradient};
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem !important;
        padding-bottom: 10px;
    }}
    
    /* Metrics Tweaks */
    label[data-testid="stMetricLabel"] {{
        color: {sub_text_color};
        font-size: 0.9rem;
        font-weight: 500;
    }}
    div[data-testid="stMetricDelta"] {{
        color: {sub_text_color} !important;
    }}
    div[data-testid="stMetricValue"] {{
        font-size: 1.8rem;
        font-weight: 700;
        color: {text_color};
    }}
    
    /* Remove default Streamlit whitespace */
    .block-container {{
        padding-top: 2rem;
        padding-bottom: 3rem;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATA LOADING ---
SLOW_MOVING_TURNOVER = 0.8  # sold less than 80% of the units bought in the period

@st.cache_data
def load_data():
    try:
        df = pd.read_csv('vendor_sales_summary.csv')
    except FileNotFoundError:
        st.error("Data file not found. Run get_vendor_summary.py first.")
        st.stop()

    # Thresholds use brands that sold something; margin is undefined otherwise
    sold = df[df['TotalSalesDollars'] > 0]
    low_sales = sold['TotalSalesDollars'].quantile(0.15)
    high_margin = sold['ProfitMargin'].quantile(0.85)

    def tag(row):
        if row['TotalSalesQuantity'] == 0:
            return "Never Sold"
        elif row['GrossProfit'] < 0:
            return "Below Cost"
        elif row['TotalSalesDollars'] < low_sales and row['ProfitMargin'] > high_margin:
            return "Hidden Gem"  # High margin, low sales
        elif row['StockTurnover'] < SLOW_MOVING_TURNOVER:
            return "Slow-Moving"
        else:
            return "Standard"

    df['Status'] = df.apply(tag, axis=1)
    return df, low_sales, high_margin

df, low_sales, high_margin = load_data()

# --- 4. SIDEBAR FILTERS ---
with st.sidebar:
    st.markdown("---")
    st.subheader("Filters")
    vendors = st.multiselect("Vendor", options=sorted(df['VendorName'].unique()))
    if vendors:
        df = df[df['VendorName'].isin(vendors)]

# --- 5. HEADER ---
st.title("Executive Vendor Dashboard")
st.markdown(f"<p style='color:{sub_text_color}; font-size: 1.1rem;'>Real-time supply chain analytics and profitability monitoring.</p>", unsafe_allow_html=True)
st.markdown("---")

# --- 6. KPI ROW ---
sales = df['TotalSalesDollars'].sum()
profit = df['GrossProfit'].sum()
margin = profit / sales * 100 if sales else 0  # revenue-weighted, not a mean of brand margins
freight = df['FreightCost'].sum()
purchases = df['TotalPurchaseDollars'].sum()
slow_capital = df.loc[df['StockTurnover'] < SLOW_MOVING_TURNOVER, 'UnsoldInventoryValue'].sum()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Revenue", f"${sales/1e6:,.2f}M")
c2.metric("Gross Profit", f"${profit/1e6:,.2f}M")
c3.metric("Gross Margin", f"{margin:.1f}%")
c4.metric("Freight Cost", f"${freight/1e6:,.2f}M", f"{freight/purchases*100:.2f}% of purchases" if purchases else None, delta_color="off", delta_arrow="off")
c5.metric("Slow-Moving Stock", f"${slow_capital/1e6:,.2f}M", "at cost", delta_color="off", delta_arrow="off")

st.markdown("##") # Spacer

# --- 7. VISUALIZATIONS ---
def show_chart(fig):
    '''Match chart backgrounds to the selected theme.'''
    fig.update_layout(paper_bgcolor=card_bg, plot_bgcolor=card_bg, font_color=text_color)
    st.plotly_chart(fig, width='stretch', theme=None)

# ROW 1: THE BIG TREEMAP (Replaces Sunburst)
st.subheader("Market Hierarchy")
st.markdown(f"<p style='color:{sub_text_color}'>Size represents Sales Volume. Color represents Profit Margin. Drill down from Vendor to Brand.</p>", unsafe_allow_html=True)

# We aggregate to prevent UI lag
tree_df = df[df['TotalSalesDollars'] > 0].groupby(['VendorName', 'Description']).agg({
    'TotalSalesDollars': 'sum',
    'GrossProfit': 'sum'
}).reset_index()
tree_df['ProfitMargin'] = tree_df['GrossProfit'] / tree_df['TotalSalesDollars'] * 100

# Top 30 vendors for readability
top_vendors = tree_df.groupby('VendorName')['TotalSalesDollars'].sum().nlargest(30).index
tree_df = tree_df[tree_df['VendorName'].isin(top_vendors)]

fig_tree = px.treemap(
    tree_df,
    path=['VendorName', 'Description'],
    values='TotalSalesDollars',
    color='ProfitMargin',
    color_continuous_scale='Viridis', # Very bright/modern
    range_color=[15, 45],  # most brands sit at 25-40%; a few deep losses would flatten the scale
    template=chart_template,
    height=600 # Make it TALL
)
fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0))
show_chart(fig_tree)


# ROW 2: SCATTER + BAR
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Opportunity Matrix")
    # Custom color map for tags
    color_map = {"Hidden Gem": "#10B981", "Slow-Moving": "#F59E0B", "Below Cost": "#EF4444", "Never Sold": "#9CA3AF", "Standard": "#6366F1"}
    
    # Zoom in
    scatter_df = df[(df['TotalSalesDollars'] > 0) & (df['TotalSalesDollars'] < 25000)]
    
    fig_scatter = px.scatter(
        scatter_df,
        x='TotalSalesDollars',
        y='ProfitMargin',
        color='Status',
        size='TotalPurchaseQuantity',
        color_discrete_map=color_map,
        template=chart_template,
        height=450,
        hover_data=['Description'],
        title="Identifying High-Value Targets (Sales < $25k)"
    )
    # Add subtle quadrants
    fig_scatter.update_yaxes(range=[-25, 100])
    fig_scatter.add_hline(y=high_margin, line_width=1, line_dash="dash", line_color=sub_text_color)
    fig_scatter.add_vline(x=low_sales, line_width=1, line_dash="dash", line_color=sub_text_color)
    
    show_chart(fig_scatter)

with col_right:
    st.subheader("Slow-Moving Stock by Vendor")
    # Cost of units bought but not sold, for brands that sold under 80% of what was bought
    slow_df = (df[df['StockTurnover'] < SLOW_MOVING_TURNOVER]
               .groupby('VendorName')['UnsoldInventoryValue'].sum()
               .nlargest(10).reset_index())

    fig_bar = px.bar(
        slow_df,
        x='UnsoldInventoryValue',
        y='VendorName',
        orientation='h',
        color_discrete_sequence=["#F59E0B"],
        template=chart_template,
        height=450,
        labels={'UnsoldInventoryValue': 'Unsold stock at cost ($)', 'VendorName': ''},
        title="Top 10 vendors by capital tied up"
    )
    fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, margin=dict(l=0, r=0, b=0, t=30))
    show_chart(fig_bar)

    freight_pct = df.groupby('VendorNumber').apply(
        lambda g: g['FreightCost'].sum() / g['TotalPurchaseDollars'].sum() * 100, include_groups=False)
    st.caption(f"Freight runs {freight_pct.min():.2f}%–{freight_pct.max():.2f}% of purchase cost across all vendors, "
               "so it does not separate vendors.")

# ROW 3: INVENTORY HEALTH
st.subheader("Inventory Turnover Distribution")
fig_hist = px.histogram(
    df[df['StockTurnover'] <= 3],  # long right tail clipped for readability
    x='StockTurnover',
    nbins=60,
    color='Status',
    color_discrete_map=color_map,
    template=chart_template,
    height=300
)
fig_hist.update_layout(bargap=0.1)
show_chart(fig_hist)

# --- 8. DETAILED DATA ---
with st.expander("Detailed Data View"):
    st.dataframe(
        df[['VendorName', 'Description', 'Status', 'TotalSalesDollars', 'ProfitMargin', 'FreightCost', 'UnsoldInventoryValue']]
        .sort_values('TotalSalesDollars', ascending=False)
        .style.background_gradient(cmap="viridis", subset=['TotalSalesDollars', 'ProfitMargin'])
        .format({"TotalSalesDollars": "${:,.2f}", "ProfitMargin": "{:.1f}%", "FreightCost": "${:,.2f}", "UnsoldInventoryValue": "${:,.2f}"}, na_rep="–"),
        width='stretch'
    )