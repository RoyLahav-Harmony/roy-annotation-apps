import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io

st.set_page_config(page_title="EDA Tool", layout="wide")
st.title("Exploratory Data Analysis Tool")

uploaded_file = st.file_uploader(
    "Upload a data file", type=["csv", "xlsx", "xls", "json", "parquet"]
)

if uploaded_file is None:
    st.info("Upload a CSV, Excel, JSON, or Parquet file to begin.")
    st.stop()

@st.cache_data
def load_data(file):
    name = file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(file)
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)
    elif name.endswith(".json"):
        return pd.read_json(file)
    elif name.endswith(".parquet"):
        return pd.read_parquet(file)
    raise ValueError(f"Unsupported file type: {file.name}")

try:
    df = load_data(uploaded_file)
except Exception as e:
    st.error(f"Could not load file: {e}")
    st.stop()

numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()

# ── Overview ──────────────────────────────────────────────────────────────────
st.header("Overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Rows", f"{df.shape[0]:,}")
col2.metric("Columns", df.shape[1])
col3.metric("Numeric cols", len(numeric_cols))
col4.metric("Categorical cols", len(categorical_cols))

with st.expander("Column types & memory usage"):
    buf = io.StringIO()
    df.info(buf=buf)
    st.text(buf.getvalue())

st.subheader("Sample data")
st.dataframe(df.head(20), use_container_width=True)

# ── Missing values ─────────────────────────────────────────────────────────────
st.header("Missing Values")
missing = df.isnull().sum()
missing = missing[missing > 0].sort_values(ascending=False)
if missing.empty:
    st.success("No missing values found.")
else:
    miss_df = pd.DataFrame({
        "Missing": missing,
        "% of rows": (missing / len(df) * 100).round(2),
    })
    st.dataframe(miss_df, use_container_width=True)

    fig, ax = plt.subplots(figsize=(10, max(3, len(missing) * 0.4)))
    miss_df["% of rows"].sort_values().plot.barh(ax=ax, color="salmon")
    ax.set_xlabel("% missing")
    ax.set_title("Missing values by column")
    st.pyplot(fig)
    plt.close(fig)

# ── Numeric analysis ───────────────────────────────────────────────────────────
if numeric_cols:
    st.header("Numeric Columns")
    st.dataframe(df[numeric_cols].describe().T.round(4), use_container_width=True)

    st.subheader("Distributions")
    n_cols = 3
    n_rows = int(np.ceil(len(numeric_cols) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, n_rows * 3))
    axes = np.array(axes).flatten()
    for i, col in enumerate(numeric_cols):
        axes[i].hist(df[col].dropna(), bins=30, edgecolor="white", color="steelblue")
        axes[i].set_title(col, fontsize=10)
        axes[i].set_xlabel("")
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    if len(numeric_cols) > 1:
        st.subheader("Correlation Heatmap")
        corr = df[numeric_cols].corr()
        fig, ax = plt.subplots(figsize=(max(6, len(numeric_cols)), max(5, len(numeric_cols) * 0.8)))
        sns.heatmap(corr, annot=len(numeric_cols) <= 20, fmt=".2f", cmap="coolwarm",
                    center=0, ax=ax, linewidths=0.5)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

# ── Categorical analysis ───────────────────────────────────────────────────────
if categorical_cols:
    st.header("Categorical Columns")
    for col in categorical_cols:
        try:
            n_unique = df[col].nunique()
            vc = df[col].value_counts().head(20)
        except TypeError:
            # Column contains unhashable types (dicts, lists, etc.) — stringify first
            s = df[col].astype(str)
            n_unique = s.nunique()
            vc = s.value_counts().head(20)

        with st.expander(f"{col}  —  {n_unique} unique values"):
            col_left, col_right = st.columns([1, 2])
            col_left.dataframe(vc.rename("count").reset_index(), use_container_width=True)
            fig, ax = plt.subplots(figsize=(8, max(2, len(vc) * 0.35)))
            vc.sort_values().plot.barh(ax=ax, color="mediumseagreen")
            ax.set_title(f"Top values — {col}")
            plt.tight_layout()
            col_right.pyplot(fig)
            plt.close(fig)

# ── Outlier summary ────────────────────────────────────────────────────────────
if numeric_cols:
    st.header("Outlier Summary (IQR method)")
    outlier_rows = []
    for col in numeric_cols:
        q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
        iqr = q3 - q1
        n_out = ((df[col] < q1 - 1.5 * iqr) | (df[col] > q3 + 1.5 * iqr)).sum()
        outlier_rows.append({"column": col, "outliers": int(n_out),
                              "% of rows": round(n_out / len(df) * 100, 2)})
    out_df = pd.DataFrame(outlier_rows).sort_values("outliers", ascending=False)
    st.dataframe(out_df, use_container_width=True)
