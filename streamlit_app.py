import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path
from industry_mapping import industry_mapping
from translations import translations
import psycopg2
from psycopg2 import sql
import os
from dotenv import load_dotenv
from os.path import join, dirname

# Set page configuration (must be the first Streamlit command)
st.set_page_config(page_title="ExportZilla", layout="wide")

# ---------- Configuration ----------
CONFIG_PATH = Path('config.json')

@st.cache_data(show_spinner=True)
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
    s = series.fillna('').astype(str).str.replace(' ', '').str.replace('-', '')
    country = pd.Series('Unknown/No phone', index=series.index)

    # Kazakhstan: +76 or +77 (no spaces)
    mask_kz = s.str.startswith('+76') | s.str.startswith('+77') | s.str.startswith('+7 6') | s.str.startswith('+7 7')
    country[mask_kz] = 'Kazakhstan'

    # Russia: +7 but not +76/+77
    mask_ru = s.str.startswith('+7') & ~mask_kz
    country[mask_ru] = 'Russian Federation'

    # Other prefixes
    prefixes = sorted([k for k in prefix_map if not k.startswith('+7')], key=len, reverse=True)
    for pre in prefixes:
        mask = s.str.startswith(pre.replace(' ', '').replace('-', ''))
        country[mask] = prefix_map[pre]

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
    # Only map columns present in the DataFrame, and always map to the selected language's output names
    # Define source columns for both languages
    english_source = {
        'ID': t['ID'],
        'Email': t['column_email'],
        'Phone number': t['column_phone'],
        'Websites': t['column_websites'],
        'Address 1': t['column_address_1'],
        'Address 2': t['column_address_2'],
        'Address 3': t['column_address_3'],
        'Country': t['column_country'],
        'Main Category': t['column_main_category'],
        'Subcategory': t['column_subcategory'],
    }
    russian_source = {
        'Электронная почта': t['column_email'],
        'Телефон': t['column_phone'],
        'Веб-сайты': t['column_websites'],
        'Адрес 1': t['column_address_1'],
        'Адрес 2': t['column_address_2'],
        'Адрес 3': t['column_address_3'],
        'Страна': t['column_country'],
        'Основная категория': t['column_main_category'],
        'Подкатегория': t['column_subcategory'],
        'Имя': t['ID'],
        'Категория': t['column_main_category'],
        'Значение': t['column_email'],
        'Город': t['column_address_2'],
        'Индекс': t['column_address_3'],
        'Источник': t['column_websites'],
    }
    # Build mapping only for columns present in df
    mapping = {}
    for src, tgt in english_source.items():
        if src in df.columns:
            mapping[src] = tgt
    for src, tgt in russian_source.items():
        if src in df.columns:
            mapping[src] = tgt
    # Remove duplicate columns before renaming
    df = df.loc[:, ~df.columns.duplicated(keep='first')]
    renamed_df = df.rename(columns=mapping)
    return renamed_df

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

    #Translate subcategories
    if t['column_subcategory'] in df.columns:
        # Try to translate using both the subcategory and the main category context
        def translate_subcat(row):
            subcat = str(row[t['column_subcategory']]).strip() if pd.notna(row[t['column_subcategory']]) else ""
            maincat = str(row[t['column_main_category']]).strip() if pd.notna(row[t['column_main_category']]) else ""
            # Try subcategory translation first
            if subcat in t['subcategories']:
                return t['subcategories'][subcat]
            # Try translation as "MainCat > SubCat" if such keys exist in your translations
            key_combo = f"{maincat} > {subcat}"
            if key_combo in t['subcategories']:
                return t['subcategories'][key_combo]
            return subcat

        df[t['column_subcategory']] = df.apply(translate_subcat, axis=1)
    return df

def clean_website_column(df: pd.DataFrame, website_col: str) -> pd.DataFrame:
    # Vectorized normalization of website column
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

        # Rename Address 1 to the translated "Address"
        df.rename(columns={addr1: t['column_address']}, inplace=True)

    else:
        st.warning(f"⚠️ One or more address/country columns are missing")
    return df
# Updated process_file function with industry mapping
@st.cache_data(show_spinner=False)
def process_file(file_bytes: bytes, cfg: dict, remove_empty_cols: bool,
                 remove_duplicates: bool,
                 filter_emails_step: bool, reset_index_step: bool) -> pd.DataFrame:
    df = pd.read_excel(BytesIO(file_bytes), engine='openpyxl')

    # 1. Remove mostly empty columns early
    if remove_empty_cols:
        df = df.loc[:, df.notna().sum() >= 100]

    # 2. Rename phone column (vectorized, no .apply)
    if 'Column_1' in df.columns:
        df.rename(columns={'Column_1': t["column_phone"]}, inplace=True)
        phone_col = t["column_phone"]
    elif 'Телефон2' in df.columns:
        df.rename(columns={'Телефон2': t["column_phone"]}, inplace=True)
        phone_col = t["column_phone"]
    else:
        st.error('⚠️ "Column_1" is not present in the DataFrame.')
        return df
    phone_cols = [t["column_phone"]]

    # 3. Remove duplicate rows based on email and phone number (vectorized)
    email_cols = [c for c in df.columns if df[c].astype(str).str.contains('@', na=False).any()]
    if remove_duplicates and email_cols:
        df.drop_duplicates(subset=[email_cols[0], phone_col], inplace=True)

    # 4. Normalize phone numbers (vectorized)
    def fix_phone_number(val):
        val = str(val).strip()
        if val and val.replace('+', '').isdigit() and not val.startswith('+'):
            return '+' + val
        return val
    df[phone_col] = df[phone_col].astype(str).str.strip().apply(fix_phone_number)

    # 5. Detect country (vectorized)
    df[t['column_country']] = detect_country(df[phone_col], cfg['phone_prefix_map'])

    # 6. Filter emails (vectorized)
    if filter_emails_step and email_cols:
        vals = df[email_cols[0]].astype(str).str.lower()
        bad = vals.apply(lambda e: any(b in e for b in cfg['email_blacklist']))
        df = df[~bad]

    # 7. Reset index (vectorized)
    if reset_index_step:
        df.reset_index(drop=True, inplace=True)
        df.index += 1
        df.index.name = 'ID'

    # 8. Translate columns and values (vectorized)
    #df = translate_columns(df, t)
    #df = translate_values(df, t)

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
        
        # Ensure Main Category and Subcategory columns are added
        industry_column = None
        if "Column_12" in filtered_df.columns:
            industry_column = "Column_12"
        elif "Категория" in filtered_df.columns:
            industry_column = "Категория"
        elif len(filtered_df.columns) > 13:
            industry_column = filtered_df.columns[13]
        else:
            st.error('Column_12 not found in the DataFrame1.')

        # Only apply mapping if industry_column is set and columns are missing
        if industry_column and (t['column_main_category'] not in filtered_df.columns or t['column_subcategory'] not in filtered_df.columns):
            def map_to_main_and_subcategory(value):
                for main_category, subcategories in industry_mapping.items():
                    if value in subcategories.keys():
                        return main_category, value
                return "Other", value

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
    
    remove_columns_toggle = st.toggle(t['remove_unnecessary_columns'], value=True)
    rename_columns_toggle = st.toggle(t['rename_columns'], value=True)
    consolidate_rows = st.toggle(t['consolidate_rows_by_company'], value=False) 

    # Initialize filtered_df with result_df
    filtered_df = result_df.copy()

    
    st.header(t['filter_preview'])

    # Filter: Number of rows
    max_rows = st.number_input(t['num_rows'], min_value=500, max_value=500000, value=500000)

    # Filter: Country selection
    selected_countries = []
    if t['column_country'] in result_df.columns:
        available_countries = result_df[t['column_country']].dropna().unique().tolist()
        selected_countries = st.multiselect(t['filter_country'], available_countries)
    

    # Ensure Main Category and Subcategory columns are added
    industry_column = None
    if "Column_12" in filtered_df.columns:
        industry_column = "Column_12"
    elif "Категория" in filtered_df.columns:
        industry_column = "Категория"
    else:
        st.error('Column_12 not found in the DataFrame2.')

    # Only apply mapping if industry_column is set and columns are missing
    if industry_column and (t['column_main_category'] not in filtered_df.columns or t['column_subcategory'] not in filtered_df.columns):
        def map_to_main_and_subcategory(value):
            for main_category, subcategories in industry_mapping.items():
                if value in subcategories.keys():
                    return main_category, value
            return "Other", value

        filtered_df[[t['column_main_category'], t['column_subcategory']]] = filtered_df[industry_column].apply(
            lambda x: pd.Series(map_to_main_and_subcategory(x))
        )

    # Print all unique subcategories that fall under the "Other" main category
    if t['column_main_category'] in filtered_df.columns and t['column_subcategory'] in filtered_df.columns:
        other_subcats = filtered_df.loc[
            filtered_df[t['column_main_category']] == "Other", t['column_subcategory']
        ].dropna().unique().tolist()
        print("Unique subcategories under 'Other':", other_subcats)
    
    # Filter: Main Category and Subcategory with counts
    if t['column_main_category'] in filtered_df.columns and t['column_subcategory'] in filtered_df.columns:
        # Get available main categories with counts
        main_category_counts = initial_category_counts.groupby(t['column_main_category'])['Count'].sum().to_dict()
        available_main_categories = filtered_df[t['column_main_category']].dropna().unique().tolist()
        selected_main_categories = []

        st.subheader(t['select_main_categories'])
        for category in available_main_categories:
            count = main_category_counts.get(category, 0)
            # Translate the category for display
            display_category = t['categories'].get(category, category)
            if st.checkbox(f"{display_category} ({count})", key=f"main_category_{category}"):
                selected_main_categories.append(category)

        selected_subcategories = []
        if selected_main_categories:
            for main_category in selected_main_categories:
                # Translate the main category for display
                display_main_category = t['categories'].get(main_category, main_category)
                st.subheader(f"{t['subcategories_for']} {display_main_category}")
                # Get available subcategories for the selected main category with counts
                subcategory_counts = initial_category_counts[initial_category_counts[t['column_main_category']] == main_category].set_index(t['column_subcategory'])['Count'].to_dict()
                available_subcategories = filtered_df[filtered_df[t['column_main_category']] == main_category][t['column_subcategory']].dropna().unique().tolist()
                for subcategory in available_subcategories:
                    count = subcategory_counts.get(subcategory, 0)
                    # Translate the subcategory for display
                    display_subcategory = t['subcategories'].get(subcategory, subcategory)
                    if st.checkbox(f"{display_subcategory} ({count})", key=f"subcategory_{main_category}_{subcategory}"):
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
        columns_to_drop = [col for col in filtered_df.columns if col in [
            "Status", "Column_2", "Column_4", "Column_5", "Column_6", "Column_7", "Column_8", "Column_12", 
            "Имя", "Ключевые слова", "Заголовок", "META Description", "META Keywords", "Домен", "PHONES", "Категория", "Имя пользователя"
            ]]
        filtered_df = filtered_df.drop(columns=columns_to_drop, axis=1)
    # Rename columns
    if rename_columns_toggle:
        filtered_df.rename(columns={
            col: t['column_websites'] for col in filtered_df.columns if 'Column_3' in col or 'Источник' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_1'] for col in filtered_df.columns if 'Column_9' in col #or 'Страна' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_2'] for col in filtered_df.columns if 'Column_10' in col or 'Город' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_address_3'] for col in filtered_df.columns if 'Column_11' in col or 'Индекс' in col # 'Адрес' in col
        }, inplace=True)
        filtered_df.rename(columns={
            col: t['column_email'] for col in filtered_df.columns if 'Email' in col or 'Значение' in col
        }, inplace=True)

    filtered_df = clean_address_columns(filtered_df, t)
    filtered_df = clean_website_column(filtered_df, t['column_websites'])

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

            # List of common/free email domains
            free_email_domains = {
                "gmail.com", "hotmail.com", "yahoo.com", "outlook.com", "aol.com", "icloud.com", "mail.ru", "yandex.ru",
                "protonmail.com", "zoho.com", "gmx.com", "mail.com", "bk.ru", "inbox.ru", "list.ru", "rambler.ru"
            }

            def extract_company_identifier(row):
                email = row[email_col] if email_exists else None
                website = row[websites_col] if websites_exists else None
                # Use website domain if available
                if pd.notna(website):
                    return normalize_url(website)
                # Use email domain only if not a free domain
                if pd.notna(email) and '@' in email:
                    domain = email.split('@')[-1].lower()
                    if domain not in free_email_domains:
                        return domain
                return None

            # Create a new column for company grouping
            filtered_df[company_identifier_col] = filtered_df.apply(extract_company_identifier, axis=1)

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


    # Display filtered preview
    if filtered_df.empty:
        st.warning("No data available for the selected filters.")
    else:
        st.subheader(t['filtered_preview'])
        st.dataframe(filtered_df)
    
    # Translate main categories and subcategories in filtered_df for preview (after all filtering and mapping)
    if t['column_main_category'] in filtered_df.columns:
        filtered_df[t['column_main_category']] = filtered_df[t['column_main_category']].apply(
            lambda x: t['categories'].get(str(x).strip(), x) if pd.notna(x) else x
        )
    if t['column_subcategory'] in filtered_df.columns:
        filtered_df[t['column_subcategory']] = filtered_df[t['column_subcategory']].apply(
            lambda x: t['subcategories'].get(str(x).strip(), x) if pd.notna(x) else x
        )
    # Download filtered file
    buf = BytesIO()
    filtered_df.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    st.download_button(t['download_file'], buf,
                       'filtered_processed.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # --- Add to Database without Dialog Confirmation ---
    def upload_to_postgres(df, table_name="filtered_data"):
        # Connect to PostgreSQL using environment variables
        dotenv_path = join(dirname(__file__), "Creds.env")
        load_dotenv(dotenv_path)
        conn = psycopg2.connect(
            host=os.getenv("PG_HOST"),
            port=int(os.getenv("PG_PORT")),
            database=os.getenv("PG_DATABASE"),
            user=os.getenv("PG_USER"),
            password=os.getenv("PG_PASSWORD")
        )
        cur = conn.cursor()

        # Create table if not exists (all columns as text for simplicity)
        columns = [sql.Identifier(col) for col in df.columns]
        col_defs = [sql.SQL("{} TEXT").format(col) for col in columns]
        create_table = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({});").format(
            sql.Identifier(table_name),
            sql.SQL(', ').join(col_defs)
        )
        cur.execute(create_table)

        # Insert data (append)
        for _, row in df.iterrows():
            insert = sql.SQL("INSERT INTO {} ({}) VALUES ({});").format(
                sql.Identifier(table_name),
                sql.SQL(', ').join(columns),
                sql.SQL(', ').join(sql.Placeholder() * len(columns))
            )
            cur.execute(insert, [str(x) if x is not None else None for x in row])
        conn.commit()
        cur.close()
        conn.close()

    @st.dialog(t['confirm_upload_title'])
    def confirm_upload():
        st.write(t['confirm_upload_message'])
        col1, col2 = st.columns(2)
        if col1.button(t['yes_upload'], key="upload_db_confirm_dialog"):
            try:
                upload_to_postgres(filtered_df)
                st.success(t['upload_success'])
            except Exception as e:
                st.error(t['upload_failed'].format(e=e))
        if col2.button(t['no_cancel'], key="upload_db_cancel_dialog"):
            st.info(t['upload_cancelled'])
            st.rerun()

    if st.button(t["add_to_database"]):
        confirm_upload()

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

        # Download button for category counts
        cat_buf = BytesIO()
        initial_category_counts.to_excel(cat_buf, index=False, engine='openpyxl')
        cat_buf.seek(0)
        st.download_button(
            label="Download Category Counts",
            data=cat_buf,
            file_name="category_counts.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    

    # After all renaming steps, drop duplicate columns and warn if any were found
    duplicate_cols = filtered_df.columns[filtered_df.columns.duplicated(keep=False)]
    if len(duplicate_cols) > 0:
        st.error(f"Duplicate column names found in preview after renaming: {list(duplicate_cols)}. Only the first occurrence will be kept.")
        filtered_df = filtered_df.loc[:, ~filtered_df.columns.duplicated(keep='first')]

