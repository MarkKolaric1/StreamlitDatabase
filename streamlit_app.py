import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path
from industry_mapping import industry_mapping
from translations import translations

# Set page configuration (must be the first Streamlit command)
st.set_page_config(page_title="ExportZilla", layout="wide")

# ---------- Configuration ----------
CONFIG_PATH = Path('config.json')

@st.cache_data(show_spinner=False)
def load_config():
    default = {
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

# Apply translations to column names
def translate_columns(df: pd.DataFrame, t: dict) -> pd.DataFrame:
    column_mapping = {
        'ID' : t['ID'],
        'Email': t['column_email'],
        'Phone number': t['column_phone'],
        'Websites' : t['column_websites'],
        'Address 1' :t['column_address_1'],
        'Address 2' :t['column_address_2'],
        'Address 3' :t['column_address_2'],
        'Country': t['column_country'],
        'Main Category' : t['column_main_category'],
        'Subcategory' :t['column_subcategory'],
    }
    return df.rename(columns=column_mapping)

# Translate categories and countries in the DataFrame
def translate_values(df: pd.DataFrame, t: dict) -> pd.DataFrame:
    # Ensure the DataFrame is not empty
    if df.empty:
        return df

    # Translate countries
    if t['column_country'] in df.columns:
        df[t['column_country']] = df[t['column_country']].apply(
            lambda x: t['countries'].get(str(x).strip(), x) if pd.notna(x) else x
        )
    
    # Translate main categories
    if t['column_main_category'] in df.columns:
        df[t['column_main_category']] = df[t['column_main_category']].apply(
            lambda x: t['categories'].get(str(x).strip(), x) if pd.notna(x) else x
        )
    
    # Translate subcategories
    if t['column_subcategory'] in df.columns:
        df[t['column_subcategory']] = df[t['column_subcategory']].apply(
            lambda x: t['subcategories'].get(str(x).strip(), x) if pd.notna(x) else x
        )
    
    return df

def clean_website_column(df: pd.DataFrame, website_col: str) -> pd.DataFrame:
    """
    Cleans the website column by removing trailing paths and normalizing the URL.
    Example: 'https://sirajpower.com/contact-us/' -> 'https://sirajpower.com/'
    """
    if website_col in df.columns:
        def normalize_url(url):
            if pd.notna(url) and '//' in url:
                # Extract the base URL (protocol + domain)
                parts = url.split('/')
                return f"{parts[0]}//{parts[2]}/" if len(parts) > 2 else url
            return url

        # Apply normalization to the website column
        df[website_col] = df[website_col].apply(normalize_url)
    else:
        st.warning(f"⚠️ Column '{website_col}' not found in the DataFrame.")
    return df

def clean_address_columns(df: pd.DataFrame, t: dict) -> pd.DataFrame:
    """
    If Address 1 is the same as Country, replace Address 1 with a combination of Address 2 and Address 3.
    If Address 1 is not the same as Country, append Address 2 and Address 3 to Address 1.
    Finally, remove Address 2 and Address 3 columns and rename Address 1 to "Address".
    """
    addr1 = t['column_address_1']
    addr2 = t['column_address_2']
    addr3 = t['column_address_3']
    country = t['column_country']

    # Debug: Print columns and a sample before cleaning


    if all(col in df.columns for col in [addr1, addr2, addr3, country]):
        def replace_address(row):
            if pd.notna(row[addr1]) and pd.notna(row[country]) and str(row[addr1]).strip() == str(row[country]).strip():
                a2 = str(row[addr2]).strip() if pd.notna(row[addr2]) else ""
                a3 = str(row[addr3]).strip() if pd.notna(row[addr3]) else ""
                combined = (a2 + " " + a3).strip()
                return combined
            else:
                a1 = str(row[addr1]).strip() if pd.notna(row[addr1]) else ""
                a2 = str(row[addr2]).strip() if pd.notna(row[addr2]) else ""
                a3 = str(row[addr3]).strip() if pd.notna(row[addr3]) else ""
                combined = (a1 + " " + a2 + " " + a3).strip()
                return combined

        # Apply the replacement logic row-wise and update the DataFrame
        df[addr1] = df.apply(replace_address, axis=1)

        # Remove Address 2 and Address 3 columns
        df.drop(columns=[addr2, addr3], inplace=True)

        # Rename Address 1 to "Address"
        df.rename(columns={addr1: "Address"}, inplace=True)

    else:
        st.warning(f"⚠️ One or more address/country columns are missing: {addr1}, {addr2}, {addr3}, {country}")
    return df
# Updated process_file function with industry mapping
@st.cache_data(show_spinner=False)
def process_file(file_bytes: bytes, cfg: dict, remove_empty_cols: bool,
                 remove_duplicates: bool,
                 filter_emails_step: bool, reset_index_step: bool) -> pd.DataFrame:
    df = pd.read_excel(BytesIO(file_bytes), engine='openpyxl')
    
    # Remove columns that are mostly empty (e.g., less than 3 non-NA entries)
    if remove_empty_cols:
        df = df.loc[:, df.notna().sum() >= 20]
    
    # Rename "Column_1" to "Phone number" if it exists
    if 'Column_1' in df.columns:
        df.rename(columns={'Column_1': "Phone number"}, inplace=True)
    else:
        st.error('⚠️ "Column_1" is not present in the DataFrame.')
        return df
    phone_cols = ["Phone number"]

    # Remove duplicate rows based on email and phone number
    email_cols = [c for c in df.columns if df[c].astype(str).str.contains('@', na=False).any()]
    if remove_duplicates and email_cols and phone_cols:
        df.drop_duplicates(subset=[email_cols[0], phone_cols[0]], inplace=True)

    # Detect country based on phone prefix
    if phone_cols:
        df['Country'] = detect_country(df[phone_cols[0]], cfg['phone_prefix_map'])
    
    # Filter emails based on blacklist
    if filter_emails_step:
        df = filter_emails(df, cfg['email_blacklist'])
    

    # Reset the index to ensure IDs are in correct order
    if reset_index_step:
        df.reset_index(drop=True, inplace=True)
        df.index += 1  # Start IDs from 1 instead of 0
        df.index.name = t['ID'] # Rename the index to 'ID'
    
    
    # Translate column names in the result DataFrame
    df = translate_columns(df, t)    

    # Translate values in the result DataFrame
    df = translate_values(df, t)

    return df

# ---------- Streamlit UI ----------

# Language selection
language = st.sidebar.selectbox('🌐 Select Language', ['English', 'Русский'])

# Get translations for the selected language
t = translations[language]

# Update UI with translations
st.title(t['title'])

# Load configuration
cfg = load_config()

# Sidebar configuration
st.sidebar.header(t['config_header'])
blacklist_input = st.sidebar.text_area(t['blacklist'], value=','.join(cfg['email_blacklist']))
pp_input = st.sidebar.text_area(
    t['phone_prefix'],
    value='\n'.join(f"{k}:{v}" for k, v in cfg['phone_prefix_map'].items()),
    height=200
)
if st.sidebar.button(t['save_settings']):
    new_bl = [b.strip() for b in blacklist_input.split(',') if b.strip()]
    new_map = {}
    for line in pp_input.splitlines():
        if ':' in line:
            p, c = line.split(':', 1)
            new_map[p.strip()] = c.strip()
    cfg = {'email_blacklist': new_bl, 'phone_prefix_map': new_map}
    save_config(cfg)
    st.sidebar.success(t['save_settings'])

# Function toggles
st.sidebar.divider()
st.sidebar.header(t['processing_steps'])
remove_empty_cols = st.sidebar.toggle(t['remove_empty_cols'], value=True)
remove_duplicates = st.sidebar.toggle(t['remove_duplicates'], value=True)
filter_emails_step = st.sidebar.toggle(t['filter_emails'], value=True)
reset_index_step = st.sidebar.toggle(t['reset_index'], value=True)

st.header(t['upload_header'])
uploaded = st.file_uploader(t['file_uploader'], type='xlsx')

if uploaded:
    # Pass the toggle states to the process_file function
    result_df = process_file(uploaded.read(), cfg, remove_empty_cols,
                             remove_duplicates,
                             filter_emails_step, reset_index_step)

    # Save initial row counts for Main Category and Subcategory at the start of the app
    if uploaded:
        # Initialize filtered_df with result_df
        filtered_df = result_df.copy()
        
        # Add Main Category and Subcategory columns to the filtered preview based on column 13
        if len(filtered_df.columns) > 13:
            industry_column = filtered_df.columns[13]  # Column at index 13

            def map_to_main_and_subcategory(value):
                for main_category, subcategories in industry_mapping.items():
                    if value in subcategories.keys():  # Check against the keys of subcategories
                        return main_category, value
                return "Other", value

            # Apply the mapping to create new columns
            filtered_df[[t['column_main_category'], t['column_subcategory']]] = filtered_df[industry_column].apply(
                lambda x: pd.Series(map_to_main_and_subcategory(x))
            )
        
        # Save initial row counts for Main Category and Subcategory
        initial_category_counts = filtered_df.groupby([t['column_main_category'], t['column_subcategory']]).size().reset_index(name='Count')
        # Debug: Check if the country column exists
        if t['column_country'] in filtered_df.columns:
            # Save initial row counts for countries
            initial_country_counts = filtered_df[t['column_country']].value_counts().reset_index(name='Count')
        else:
            st.warning(f"⚠️ The column '{t['column_country']}' does not exist in the DataFrame.")
            initial_country_counts = pd.DataFrame(columns=[t['column_country'], 'Count'])

    # Filtering Section
    #show_filters = st.toggle(t['show_filters'], value=True)  # Toggle for showing filters
    consolidate_rows = st.toggle(t['consolidate_rows_by_company'], value=False)#, disabled=True)  
    remove_columns_toggle = st.toggle(t['remove_unnecessary_columns'], value=True)
    rename_columns_toggle = st.toggle(t['rename_columns'], value=True)

    # Initialize filtered_df with result_df
    filtered_df = result_df.copy()

    if consolidate_rows:
        # Consolidate rows by company
        email_col = t['column_email']
        websites_col = t['column_websites']
        company_identifier_col = 'Company Identifier'

        # Ensure the email and website columns exist in the DataFrame
        email_exists = email_col in filtered_df.columns
        websites_exists = websites_col in filtered_df.columns

        if email_exists or websites_exists:
            # Extract company identifiers
            def extract_email_domain(email):
                if pd.notna(email) and '@' in email:
                    return email.split('@')[-1].lower()
                return None

            def normalize_url(url):
                if pd.notna(url):
                    # Remove paths and normalize the URL
                    return url.split('/')[2].lower() if '//' in url else url.lower()
                return None

            # Create a new column for company grouping
            filtered_df[company_identifier_col] = None
            if email_exists:
                filtered_df[company_identifier_col] = filtered_df[email_col].apply(extract_email_domain)
            if websites_exists:
                filtered_df[company_identifier_col] = filtered_df[company_identifier_col].fillna(
                    filtered_df[websites_col].apply(normalize_url)
                )

            # Drop rows where the company identifier is missing
            filtered_df = filtered_df.dropna(subset=[company_identifier_col])

            # Group by the company identifier
            company_group = filtered_df.groupby(company_identifier_col, as_index=False)

            def consolidate_column(series):
                unique_values = series.dropna().unique()
                return '; '.join(unique_values)

            # Consolidate emails, phone numbers, and websites
            if email_exists:
                filtered_df[email_col] = company_group[email_col].transform(consolidate_column)
            if t['column_phone'] in filtered_df.columns:
                filtered_df[t['column_phone']] = company_group[t['column_phone']].transform(consolidate_column)
            if websites_exists:
                filtered_df[websites_col] = company_group[websites_col].transform(consolidate_column)

            # Drop duplicate rows after consolidation
            filtered_df = filtered_df.drop_duplicates(subset=[company_identifier_col])

            # Drop the temporary 'Company Identifier' column
            filtered_df.drop(columns=[company_identifier_col], inplace=True)
        else:
            st.warning("⚠️ Neither email nor website columns are available for consolidation.")

    st.header(t['filter_preview'])

    # Filter: Number of rows
    max_rows = st.number_input(t['num_rows'], min_value=500, max_value=5000, value=500)

    # Filter: Country selection
    selected_countries = []
    if t['column_country'] in result_df.columns:
        available_countries = result_df[t['column_country']].dropna().unique().tolist()
        selected_countries = st.multiselect(t['filter_country'], available_countries)
    
    # Ensure Main Category and Subcategory columns are added
    if len(filtered_df.columns) > 13:
        industry_column = filtered_df.columns[13]  # Column at index 13

        def map_to_main_and_subcategory(value):
            for main_category, subcategories in industry_mapping.items():
                if value in subcategories.keys():  # Check against the keys of subcategories
                    return main_category, value
            return "Other", value

        # Apply the mapping to create new columns
        filtered_df[[t['column_main_category'], t['column_subcategory']]] = filtered_df[industry_column].apply(
            lambda x: pd.Series(map_to_main_and_subcategory(x))
        )
    
    # Filter: Main Category and Subcategory with counts
    if t['column_main_category'] in filtered_df.columns and t['column_subcategory'] in filtered_df.columns:
        # Get available main categories with counts
        main_category_counts = initial_category_counts.groupby(t['column_main_category'])['Count'].sum().to_dict()
        available_main_categories = filtered_df[t['column_main_category']].dropna().unique().tolist()
        selected_main_categories = []

        st.subheader(t['select_main_categories'])
        for category in available_main_categories:
            count = main_category_counts.get(category, 0)
            if st.checkbox(f"{category} ({count})", key=f"main_category_{category}"):
                selected_main_categories.append(category)

        selected_subcategories = []
        if selected_main_categories:
            for main_category in selected_main_categories:
                st.subheader(f"{t['subcategories_for']} {main_category}")
                # Get available subcategories for the selected main category with counts
                subcategory_counts = initial_category_counts[initial_category_counts[t['column_main_category']] == main_category].set_index(t['column_subcategory'])['Count'].to_dict()
                available_subcategories = filtered_df[filtered_df[t['column_main_category']] == main_category][t['column_subcategory']].dropna().unique().tolist()
                for subcategory in available_subcategories:
                    count = subcategory_counts.get(subcategory, 0)
                    if st.checkbox(f"{subcategory} ({count})", key=f"subcategory_{main_category}_{subcategory}"):
                        selected_subcategories.append(subcategory)
        else:
            selected_subcategories = None
    else:
        selected_main_categories = None
        selected_subcategories = None

    # Apply filters
    if selected_countries:
        filtered_df = filtered_df[filtered_df[t['column_country']].isin(selected_countries)]

    if selected_main_categories:
        filtered_df = filtered_df[filtered_df[t['column_main_category']].isin(selected_main_categories)]

    if selected_subcategories:
        filtered_df = filtered_df[filtered_df[t['column_subcategory']].isin(selected_subcategories)]

    # Limit the number of rows
    filtered_df = filtered_df.head(max_rows)

    # Remove unnecessary columns from the filtered DataFrame      
    if remove_columns_toggle:
        columns_to_drop = [col for col in filtered_df.columns if col in ["Status", "Column_2", "Column_4", "Column_5", "Column_6", "Column_7", "Column_8", "Column_12"]]
        filtered_df = filtered_df.drop(columns=columns_to_drop, axis=1)
    # Rename columns
    if rename_columns_toggle:
        filtered_df.rename(columns={
            col: t['column_websites'] for col in filtered_df.columns if 'Column_3' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_1'] for col in filtered_df.columns if 'Column_9' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_2'] for col in filtered_df.columns if 'Column_10' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_3'] for col in filtered_df.columns if 'Column_11' in col
        }, inplace=True)

    filtered_df = clean_address_columns(filtered_df, t)
    filtered_df = clean_website_column(filtered_df, t['column_websites'])
    
    print(filtered_df.columns)

    # Display filtered preview
    if filtered_df.empty:
        st.warning("No data available for the selected filters.")
    else:
        st.subheader(t['filtered_preview'])
        st.dataframe(filtered_df)
    
    # Add Main Category and Subcategory columns to the filtered preview based on column 13
    if len(filtered_df.columns) > 13:
        industry_column = filtered_df.columns[13]  # Column at index 13

        def map_to_main_and_subcategory(value):
            for main_category, subcategories in industry_mapping.items():
                if value in subcategories.keys():  # Check against the keys of subcategories
                    return main_category, value
            return "Other", value

        # Apply the mapping to create new columns
        filtered_df[[t['column_main_category'], t['column_subcategory']]] = filtered_df[industry_column].apply(
            lambda x: pd.Series(map_to_main_and_subcategory(x))
        )
    
    # Download filtered file
    buf = BytesIO()
    filtered_df.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    st.download_button(t['download_file'], buf,
                       'filtered_processed.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # Count rows per country
    show_country_counts = st.toggle(t['rows_per_country'], value=False)
    if show_country_counts and t['column_country'] in filtered_df.columns:

        # Display the counts
        st.subheader(t['rows_per_country'])
        st.dataframe(initial_country_counts)

    # Count rows per Main Category and Subcategory based on filtered preview
    show_category_counts = st.toggle(t['rows_per_category'], value=False)
    if show_category_counts and t['column_main_category'] in filtered_df.columns and t['column_subcategory'] in filtered_df.columns:

        # Display the counts
        st.subheader(t['rows_per_category'])
        st.dataframe(initial_category_counts)


