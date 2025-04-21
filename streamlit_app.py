import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path
from io import BytesIO

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
    df = pd.read_excel(BytesIO(file_bytes), engine='openpyxl')
    
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

# Language selection
language = st.sidebar.selectbox('🌐 Select Language', ['English', 'Русский'])

# Translation dictionary
translations = {
    'English': {
        'title': '📊 Excel Phone & Email Processor',
        'config_header': '⚙️ Configuration',
        'blacklist': 'Blacklist (comma-separated)',
        'phone_prefix': 'Phone Prefix → Country (prefix:country per line)',
        'save_settings': '💾 Save Settings',
        'processing_steps': '🔧 Processing Steps',
        'remove_empty_cols': 'Remove Empty Columns',
        'rename_column': 'Rename "Column_1" to "Phone number"',
        'remove_duplicates': 'Remove Duplicate Rows (Email & Phone)',
        'detect_country': 'Detect Country Based on Phone Prefix',
        'filter_emails': 'Filter Emails Based on Blacklist',
        'reset_index': 'Reset Index and Generate Sequential IDs',
        'upload_header': '📥 Upload & Process Excel',
        'file_uploader': 'Select an .xlsx file',
        'show_filters': '🔧 Show Filters',
        'filter_preview': '🔍 Filter Preview and Processed File',
        'num_rows': 'Number of rows to display (1-5000)',
        'filter_country': 'Filter by Country',
        'filter_sphere': 'Filter by Business Sphere/Industry',
        'filtered_preview': '🔍 Filtered Preview',
        'download_file': '📥 Download Filtered File',
        'rows_per_country': '📊 Rows Per Country',
        'rows_per_sphere': '📊 Rows Per Business Sphere/Industry',
    },
    'Русский': {
        'title': '📊 Обработчик Excel для телефонов и электронной почты',
        'config_header': '⚙️ Конфигурация',
        'blacklist': 'Черный список (через запятую)',
        'phone_prefix': 'Префикс телефона → Страна (префикс:страна в строке)',
        'save_settings': '💾 Сохранить настройки',
        'processing_steps': '🔧 Этапы обработки',
        'remove_empty_cols': 'Удалить пустые столбцы',
        'rename_column': 'Переименовать "Column_1" в "Номер телефона"',
        'remove_duplicates': 'Удалить дублирующиеся строки (Email & Телефон)',
        'detect_country': 'Определить страну по телефонному префиксу',
        'filter_emails': 'Фильтровать электронные письма по черному списку',
        'reset_index': 'Сбросить индекс и создать последовательные ID',
        'upload_header': '📥 Загрузить и обработать Excel',
        'file_uploader': 'Выберите файл .xlsx',
        'show_filters': '🔧 Показать фильтры',
        'filter_preview': '🔍 Предварительный просмотр и обработанный файл',
        'num_rows': 'Количество строк для отображения (1-5000)',
        'filter_country': 'Фильтр по стране',
        'filter_sphere': 'Фильтр по сфере бизнеса/индустрии',
        'filtered_preview': '🔍 Предварительный просмотр',
        'download_file': '📥 Скачать обработанный файл',
        'rows_per_country': '📊 Строки по странам',
        'rows_per_sphere': '📊 Строки по сфере бизнеса/индустрии',
    }
}

# Get translations for the selected language
t = translations[language]

# Update UI with translations
#st.set_page_config(page_title=t['title'], layout='wide')
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
rename_column = st.sidebar.toggle(t['rename_column'], value=True)
remove_duplicates = st.sidebar.toggle(t['remove_duplicates'], value=True)
detect_country_step = st.sidebar.toggle(t['detect_country'], value=True)
filter_emails_step = st.sidebar.toggle(t['filter_emails'], value=True)
reset_index_step = st.sidebar.toggle(t['reset_index'], value=True)

st.write('---')
st.header(t['upload_header'])
uploaded = st.file_uploader(t['file_uploader'], type='xlsx')

if uploaded:
    # Pass the toggle states to the process_file function
    result_df = process_file(uploaded.read(), cfg, remove_empty_cols, rename_column,
                             remove_duplicates, detect_country_step,
                             filter_emails_step, reset_index_step)

    # Filtering Section
    st.write('---')
    show_filters = st.toggle(t['show_filters'], value=True)  # Toggle for showing filters
    if show_filters:
        st.header(t['filter_preview'])

        # Filter: Number of rows
        max_rows = st.number_input(t['num_rows'], min_value=1, max_value=5000, value=300)

        # Filter: Country selection
        if 'Country' in result_df.columns:
            available_countries = result_df['Country'].dropna().unique().tolist()
            selected_countries = st.multiselect(t['filter_country'], available_countries)

        # Filter: Business sphere/industry (Column 12)
        if len(result_df.columns) >= 14:
            available_spheres = result_df.iloc[:, 13].dropna().unique().tolist()
            selected_spheres = st.multiselect(t['filter_sphere'], available_spheres)

        # Apply filters
        filtered_df = result_df.copy()
        if 'Country' in filtered_df.columns and selected_countries:
            filtered_df = filtered_df[filtered_df['Country'].isin(selected_countries)]
        if len(filtered_df.columns) >= 12 and selected_spheres:
            filtered_df = filtered_df[filtered_df.iloc[:, 13].isin(selected_spheres)]
        filtered_df = filtered_df.head(max_rows)

    else:
        # If filters are not shown, use the unfiltered DataFrame
        filtered_df = result_df.copy()

    # Display filtered preview
    st.subheader(t['filtered_preview'])
    st.dataframe(filtered_df)

    # Download filtered file
    buf = BytesIO()
    filtered_df.to_excel(buf, index=False, engine='openpyxl')
    buf.seek(0)
    st.download_button(t['download_file'], buf,
                       'filtered_processed.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # Count rows per country
    show_country_counts = st.toggle(t['rows_per_country'], value=True)
    if show_country_counts and 'Country' in filtered_df.columns:
        country_counts = filtered_df['Country'].value_counts().reset_index()
        country_counts.columns = ['Country', 'Count']
        st.subheader(t['rows_per_country'])
        st.dataframe(country_counts)

    # Count rows per business sphere/industry
    show_sphere_counts = st.toggle(t['rows_per_sphere'], value=True)
    if show_sphere_counts and len(filtered_df.columns) >= 14:
        sphere_counts = filtered_df.iloc[:, 13].value_counts().reset_index()
        sphere_counts.columns = ['Business Sphere/Industry', 'Count']
        st.subheader(t['rows_per_sphere'])
        st.dataframe(sphere_counts)