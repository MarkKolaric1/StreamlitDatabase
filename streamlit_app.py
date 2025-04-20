import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path

# ---------- Configuration ----------
CONFIG_PATH = Path('config.json')

@st.cache_data(show_spinner=False)
def load_config():
    default = {
        'email_whitelist': ['info', 'contact', 'support'],
        'email_blacklist': ['pr', 'hr', 'press'],
        'phone_prefix_map': {'+1': 'United States/Canada', '+44': 'United Kingdom'}
    }
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            st.warning('⚠️ config.json is invalid; using defaults!')
    return default

def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    load_config.clear()  # clear cache so new config is loaded
    return cfg

# ---------- Data Processing ----------

def detect_country(series: pd.Series, prefix_map: dict) -> pd.Series:
    prefixes = sorted(prefix_map.keys(), key=len, reverse=True)
    country = pd.Series('Unknown/No phone', index=series.index)
    s = series.fillna('').astype(str)
    for pre in prefixes:
        mask = s.str.startswith(pre)
        country.loc[mask] = prefix_map[pre]
    return country

# Email filtering function

def filter_emails(df: pd.DataFrame, blacklist: list) -> pd.DataFrame:
    email_cols = [c for c in df.columns if df[c].astype(str).str.contains('@', na=False).any()]
    if not email_cols:
        return df
    for col in email_cols:
        vals = df[col].astype(str).str.lower()
        bad = vals.apply(lambda e: any(b in e for b in blacklist))
        df = df[~bad]  # Remove rows where any blacklist word is found
    return df

# Updated process_file function with toggles
@st.cache_data(show_spinner=False)
def process_file(file_bytes: bytes, cfg: dict, remove_empty_cols: bool, rename_column: bool,
                 remove_duplicates: bool, detect_country_step: bool,
                 filter_emails_step: bool, reset_index_step: bool) -> pd.DataFrame:
    df = pd.read_excel(file_bytes)
    
    # Remove columns that are completely empty
    if remove_empty_cols:
        df.dropna(axis=1, how='all', inplace=True)
    
    phone_cols = [c for c in df.columns if 'phone' in c.lower()]
    
    # If no phone column is found, rename "Column_1" to "Phone number"
    if rename_column and not phone_cols:
        if "Column_1" in df.columns:
            df.rename(columns={"Column_1": "Phone number"}, inplace=True)
            phone_cols = ["Phone number"]
        else:
            st.error('⚠️ No phone column found and "Column_1" is not present.')
            return df

    # Remove duplicate rows based on email and phone number
    email_cols = [c for c in df.columns if df[c].astype(str).str.contains('@', na=False).any()]
    if remove_duplicates and email_cols and phone_cols:
        df.drop_duplicates(subset=[email_cols[0], phone_cols[0]], inplace=True)

    # Detect country based on phone prefix
    if detect_country_step and phone_cols:
        df['Country'] = detect_country(df[phone_cols[0]], cfg['phone_prefix_map'])
    
    # Filter emails based on blacklist
    if filter_emails_step:
        df = filter_emails(df, cfg['email_blacklist'])
    
    # Reset the index to ensure IDs are in correct order
    if reset_index_step:
        df.reset_index(drop=True, inplace=True)
        df.index += 1  # Start IDs from 1 instead of 0
        df.index.name = 'ID'  # Rename the index to 'ID'

    return df

# ---------- Streamlit UI ----------

st.set_page_config(page_title='Excel Processor', layout='wide')
st.title('📊 Excel Phone & Email Processor')

# Load configuration
cfg = load_config()

# Sidebar configuration
st.sidebar.header('⚙️ Configuration')
blacklist_input = st.sidebar.text_area('Blacklist (comma-separated)', value=','.join(cfg['email_blacklist']))
pp_input = st.sidebar.text_area(
    'Phone Prefix → Country (prefix:country per line)',
    value='\n'.join(f"{k}:{v}" for k, v in cfg['phone_prefix_map'].items())
)
if st.sidebar.button('💾 Save Settings'):
    new_bl = [b.strip() for b in blacklist_input.split(',') if b.strip()]
    new_map = {}
    for line in pp_input.splitlines():
        if ':' in line:
            p, c = line.split(':', 1)
            new_map[p.strip()] = c.strip()
    cfg = {'email_blacklist': new_bl, 'phone_prefix_map': new_map}
    save_config(cfg)
    st.sidebar.success('Configuration saved!')

# Function toggles
st.sidebar.header('🔧 Processing Steps')
remove_empty_cols = st.sidebar.toggle('Remove Empty Columns', value=False)
rename_column = st.sidebar.toggle('Rename "Column_1" to "Phone number"', value=False)
remove_duplicates = st.sidebar.toggle('Remove Duplicate Rows (Email & Phone)', value=False)
detect_country_step = st.sidebar.toggle('Detect Country Based on Phone Prefix', value=False)
filter_emails_step = st.sidebar.toggle('Filter Emails Based on Blacklist', value=False)
reset_index_step = st.sidebar.toggle('Reset Index and Generate Sequential IDs', value=False)

st.write('---')
st.header('📥 Upload & Process Excel')
uploaded = st.file_uploader('Select an .xlsx file', type='xlsx')

if uploaded:
    # Pass the toggle states to the process_file function
    result_df = process_file(uploaded.read(), cfg, remove_empty_cols, rename_column,
                             remove_duplicates, detect_country_step,
                             filter_emails_step, reset_index_step)

    # Filtering Section
    st.write('---')
    st.header('🔍 Filter Preview and Processed File')

    # Filter: Number of rows
    max_rows = st.number_input('Number of rows to display (1-5000)', min_value=1, max_value=5000, value=100)

    # Filter: Country selection
    if 'Country' in result_df.columns:
        available_countries = result_df['Country'].dropna().unique().tolist()
        selected_countries = st.multiselect('Filter by Country', available_countries)

    # Filter: Business sphere/industry (Column 12)
    if len(result_df.columns) >= 14:
        available_spheres = result_df.iloc[:, 13].dropna().unique().tolist()
        selected_spheres = st.multiselect('Filter by Business Sphere/Industry', available_spheres)

    # Apply filters
    filtered_df = result_df.copy()
    if 'Country' in filtered_df.columns and selected_countries:
        filtered_df = filtered_df[filtered_df['Country'].isin(selected_countries)]
    if len(filtered_df.columns) >= 12 and selected_spheres:
        filtered_df = filtered_df[filtered_df.iloc[:, 13].isin(selected_spheres)]
    filtered_df = filtered_df.head(max_rows)

    # Display filtered preview
    st.subheader('🔍 Filtered Preview')
    st.dataframe(filtered_df)

    # Download filtered file
    buf = BytesIO()
    filtered_df.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    st.download_button('📥 Download Filtered File', buf,
                       'filtered_processed.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')