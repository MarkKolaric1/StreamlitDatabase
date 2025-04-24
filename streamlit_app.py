import streamlit as st
import pandas as pd
import json
from io import BytesIO
from pathlib import Path

# Set page configuration (must be the first Streamlit command)
st.set_page_config(page_title="📊 Excel Phone & Email Processor", layout="wide")

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

# ---------- Industry Mapping ----------
# Updated Industry Mapping with Main Categories and Subcategories
industry_mapping = {
    "Agriculture & Food": {
        "Crop farm": "Crop farm",
        "Livestock farm": "Livestock farm",
        "Fishery": "Fishery",
        "Agricultural machinery supplier": "Agricultural machinery supplier",
        "Food processing company": "Food processing company",
        "Dairy producer": "Dairy producer",
        "Meat processing plant": "Meat processing plant",
        "Bakery": "Bakery",
        "Beverage company": "Beverage company",
        "Fertilizer manufacturer": "Fertilizer manufacturer"
    },
    "Business Services": {
        "Corporate office": "Corporate office",
        "Business center": "Business center",
        "Consulting firm": "Consulting firm",
        "Law firm": "Law firm",
        "Accounting firm": "Accounting firm",
        "Marketing agency": "Marketing agency",
        "Recruitment agency": "Recruitment agency",
        "Non-profit organization": "Non-profit organization",
        "Research institute": "Research institute",
        "Bank": "Bank",
        "Insurance company": "Insurance company",
        "Asset management firm": "Asset management firm",
        "Venture capital firm": "Venture capital firm",
        "Fintech startup": "Fintech startup"
    },
    "Chemicals, Pharmaceuticals & Plastics": {
        "Chemical manufacturer": "Chemical manufacturer",
        "Industrial chemicals wholesaler": "Industrial chemicals wholesaler",
        "Pharmaceutical company": "Pharmaceutical company",
        "Biotechnology firm": "Biotechnology firm"
    },
    "Construction": {
        "Construction contractor": "Construction contractor",
        "Building materials supplier": "Building materials supplier",
        "Architecture firm": "Architecture firm",
        "Property developer": "Property developer",
        "Real estate agency": "Real estate agency"
    },
    "Education, Training & Organisations": {
        "School": "School",
        "E-learning provider": "E-learning provider"
    },
    "Electrical, Electronics & Optical": {
        "Electrical products wholesaler": "Electrical products wholesaler",
        "Electrical equipment supplier": "Electrical equipment supplier",
        "Electrical engineer": "Electrical engineer",
        "Hardware manufacturer": "Hardware manufacturer",
        "Semiconductor manufacturer": "Semiconductor manufacturer",
        "Telecommunications equipment supplier": "Telecommunications equipment supplier",
        "Telecommunications service provider": "Telecommunications service provider",
        "Telecommunications contractor": "Telecommunications contractor",
        "Cable company": "Cable company",
        "Security system supplier": "Security system supplier"
    },
    "Energy, Environment": {
        "Oil refinery": "Oil refinery",
        "Oil & natural gas company": "Oil & natural gas company",
        "Oil field equipment supplier": "Oil field equipment supplier",
        "Oil wholesaler": "Oil wholesaler",
        "Diesel fuel supplier": "Diesel fuel supplier",
        "Oil store": "Oil store",
        "Oilfield": "Oilfield",
        "Solar energy company": "Solar energy company",
        "Solar energy system service": "Solar energy system service",
        "Solar energy equipment supplier": "Solar energy equipment supplier",
        "Solar hot water system supplier": "Solar hot water system supplier",
        "Electric utility company": "Electric utility company",
        "Power station": "Power station",
        "Energy equipment and solutions": "Energy equipment and solutions",
        "Coal mining": "Coal mining",
        "Coal processing": "Coal processing",
        "Wind energy company": "Wind energy company",
        "Hydropower plant": "Hydropower plant"
    },
    "IT, Internet & R&D": {
        "Software company": "Software company",
        "IT services provider": "IT services provider",
        "E-commerce platform": "E-commerce platform",
        "Cybersecurity firm": "Cybersecurity firm",
        "AI solutions provider": "AI solutions provider"
    },
    "Leisure & Tourism": {
        "TV broadcaster": "TV broadcaster",
        "Film production company": "Film production company",
        "Music label": "Music label",
        "Game developer": "Game developer",
        "Creative agency": "Creative agency"
    },
    "Metals, Machinery & Engineering": {
        "Industrial equipment supplier": "Industrial equipment supplier",
        "Equipment rental agency": "Equipment rental agency",
        "Manufacturer": "Manufacturer",
        "Shipyard": "Shipyard",
        "Shipbuilding and repair company": "Shipbuilding and repair company",
        "Metal processing": "Metal processing",
        "Steel manufacturer": "Steel manufacturer",
        "Car manufacturer": "Car manufacturer",
        "Aerospace company": "Aerospace company",
        "Defense contractor": "Defense contractor",
        "Automation solutions provider": "Automation solutions provider"
    },
    "Minerals": {
        "Mining company": "Mining company",
        "Mineral processing": "Mineral processing"
    },
    "Paper, Printing & Publishing": {
        "Paper mill": "Paper mill",
        "Packaging company": "Packaging company",
        "Printing service": "Printing service"
    },
    "Retail & Traders": {
        "Retail chain": "Retail chain",
        "Consumer electronics retailer": "Consumer electronics retailer",
        "Luxury brand": "Luxury brand",
        "Household products manufacturer": "Household products manufacturer"
    },
    "Textiles, Clothing, Leather, Watchmaking, Jewellery": {
        "Textile manufacturer": "Textile manufacturer",
        "Clothing store": "Clothing store"
    },
    "Transport & Logistics": {
        "Distribution service": "Distribution service",
        "Shipping company": "Shipping company",
        "Airline": "Airline",
        "Railway operator": "Railway operator",
        "Trucking company": "Trucking company",
        "Warehouse": "Warehouse",
        "Courier service": "Courier service"
    }
}



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
        'Country': t['column_country'],
        'Email': t['column_email'],
        'Phone number': t['column_phone'],
    }
    return df.rename(columns=column_mapping)

# Translate categories and countries in the DataFrame
def translate_values(df: pd.DataFrame, t: dict) -> pd.DataFrame:
    if t['column_country'] in df.columns:
        df[t['column_country']] = df[t['column_country']].map(t['countries']).fillna(df[t['column_country']])
    return df

# Updated process_file function with industry mapping
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
        'consolidate_rows': '🛠 Consolidate Rows by Company',
        'filter_preview': '🔍 Filter Preview and Processed File',
        'num_rows': 'Number of rows to display (1-5000)',
        'filter_country': 'Filter by Country',
        'filter_sphere': 'Filter by Business Sphere/Industry',
        'filtered_preview': '🔍 Filtered Preview',
        'download_file': '📥 Download Filtered File',
        'rows_per_country': '📊 Rows Per Country',
        'rows_per_sphere': '📊 Rows Per Business Sphere/Industry',
        'column_country': 'Country',
        'column_email': 'Email',
        'column_phone': 'Phone Number',
        'countries': {  # Translations for countries
            'United States/Canada': 'United States/Canada',
            'Russia/Kazakhstan': 'Russia/Kazakhstan',
            'Egypt': 'Egypt',
            'South Africa': 'South Africa',
            'Greece': 'Greece',
            'Netherlands': 'Netherlands',
            'Belgium': 'Belgium',
            'France': 'France',
            'Spain': 'Spain',
            'Hungary': 'Hungary',
            'Italy': 'Italy',
            'Romania': 'Romania',
            'Switzerland': 'Switzerland',
            'Austria': 'Austria',
            'United Kingdom': 'United Kingdom',
            'Denmark': 'Denmark',
            'Sweden': 'Sweden',
            'Norway': 'Norway',
            'Poland': 'Poland',
            'Germany': 'Germany',
            'Peru': 'Peru',
            'Mexico': 'Mexico',
            'Cuba': 'Cuba',
            'Argentina': 'Argentina',
            'Brazil': 'Brazil',
            'Chile': 'Chile'
        }
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
        'consolidate_rows': '🛠 Объединить строки по компании',
        'filter_preview': '🔍 Предварительный просмотр и обработанный файл',
        'num_rows': 'Количество строк для отображения (1-5000)',
        'filter_country': 'Фильтр по стране',
        'filter_sphere': 'Фильтр по сфере бизнеса/индустрии',
        'filtered_preview': '🔍 Предварительный просмотр',
        'download_file': '📥 Скачать обработанный файл',
        'rows_per_country': '📊 Строки по странам',
        'rows_per_sphere': '📊 Строки по сфере бизнеса/индустрии',
        'column_country': 'Страна',
        'column_industry': 'Категория индустрии',
        'column_email': 'Электронная почта',
        'column_phone': 'Номер телефона',
        'countries': {  # Translations for countries
            'United States/Canada': 'США/Канада',
            'Russia/Kazakhstan': 'Россия/Казахстан',
            'Egypt': 'Египет',
            'South Africa': 'Южная Африка',
            'Greece': 'Греция',
            'Netherlands': 'Нидерланды',
            'Belgium': 'Бельгия',
            'France': 'Франция',
            'Spain': 'Испания',
            'Hungary': 'Венгрия',
            'Italy': 'Италия',
            'Romania': 'Румыния',
            'Switzerland': 'Швейцария',
            'Austria': 'Австрия',
            'United Kingdom': 'Великобритания',
            'Denmark': 'Дания',
            'Sweden': 'Швеция',
            'Norway': 'Норвегия',
            'Poland': 'Польша',
            'Germany': 'Германия',
            'Peru': 'Перу',
            'Mexico': 'Мексика',
            'Cuba': 'Куба',
            'Argentina': 'Аргентина',
            'Brazil': 'Бразилия',
            'Chile': 'Чили'
        }
    }
}

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

    # Translate column names in the result DataFrame
    result_df = translate_columns(result_df, t)

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
                return "Other", "Other"

            # Apply the mapping to create new columns
            filtered_df[['Main Category', 'Subcategory']] = filtered_df[industry_column].apply(
                lambda x: pd.Series(map_to_main_and_subcategory(x))
            )

        # Save initial row counts for Main Category and Subcategory
        initial_category_counts = filtered_df.groupby(['Main Category', 'Subcategory']).size().reset_index(name='Count')
        initial_country_counts = filtered_df[t['column_country']].value_counts().reset_index(name='Count')


    # Filtering Section
    show_filters = st.toggle(t['show_filters'], value=True)  # Toggle for showing filters
    consolidate_rows = st.toggle("🛠 Consolidate Rows by Company", value=False, disabled=True)  
    remove_columns_toggle = st.toggle("🗑️ Remove unnecessary columns", value=True)
    rename_columns_toggle = st.toggle("📝 Rename Columns", value=True)

    # Initialize filtered_df with result_df
    filtered_df = result_df.copy()

    if consolidate_rows:
        # Consolidate rows by company
        if 'Email' in result_df.columns or 'Websites' in result_df.columns:
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
            result_df['Company Identifier'] = result_df['Email'].apply(extract_email_domain)
            if 'Websites' in result_df.columns:
                result_df['Company Identifier'].fillna(result_df['Websites'].apply(normalize_url), inplace=True)

            # Group by the company identifier
            company_group = result_df.groupby('Company Identifier', as_index=False)

            def consolidate_column(series):
                unique_values = series.dropna().unique()
                return '; '.join(unique_values)

            # Consolidate emails, phone numbers, and links
            if 'Email' in result_df.columns:
                result_df['Email'] = company_group['Email'].transform(consolidate_column)
            if 'Phone number' in result_df.columns:
                result_df['Phone number'] = company_group['Phone number'].transform(consolidate_column)
            if 'Websites' in result_df.columns:
                result_df['Websites'] = company_group['Websites'].transform(consolidate_column)

            # Drop duplicate rows after consolidation
            result_df = result_df.drop_duplicates(subset=['Company Identifier'])

            # Drop the temporary 'Company Identifier' column
            result_df.drop(columns=['Company Identifier'], inplace=True)


    # Rename all columns in the DataFrame
    #filtered_df.columns = [f"Column_{i+1}" for i in range(len(filtered_df.columns))]

    if show_filters:
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
                return "Other", "Other"

            # Apply the mapping to create new columns
            filtered_df[['Main Category', 'Subcategory']] = filtered_df[industry_column].apply(
                lambda x: pd.Series(map_to_main_and_subcategory(x))
            )

        # Filter: Main Category and Subcategory with counts
        if 'Main Category' in filtered_df.columns and 'Subcategory' in filtered_df.columns:
            # Get available main categories with counts
            main_category_counts = initial_category_counts.groupby('Main Category')['Count'].sum().to_dict()
            available_main_categories = filtered_df['Main Category'].dropna().unique().tolist()
            selected_main_categories = []

            st.subheader("Select Main Categories")
            for category in available_main_categories:
                count = main_category_counts.get(category, 0)
                if st.checkbox(f"{category} ({count})", key=f"main_category_{category}"):
                    selected_main_categories.append(category)

            selected_subcategories = []
            if selected_main_categories:
                for main_category in selected_main_categories:
                    st.subheader(f"Subcategories for {main_category}")
                    # Get available subcategories for the selected main category with counts
                    subcategory_counts = initial_category_counts[initial_category_counts['Main Category'] == main_category].set_index('Subcategory')['Count'].to_dict()
                    available_subcategories = filtered_df[filtered_df['Main Category'] == main_category]['Subcategory'].dropna().unique().tolist()
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
            filtered_df = filtered_df[filtered_df['Main Category'].isin(selected_main_categories)]

        if selected_subcategories:
            filtered_df = filtered_df[filtered_df['Subcategory'].isin(selected_subcategories)]

        # Limit the number of rows
        filtered_df = filtered_df.head(max_rows)

        # Remove unnecessary columns from the filtered DataFrame      
        if remove_columns_toggle:
            filtered_df = filtered_df.drop(columns=["Status", "Column_2", "Column_4", "Column_5", "Column_6", "Column_7", "Column_8", "Column_12"], axis=1)
        
        # Rename columns
        if rename_columns_toggle and 'Column_3' in result_df.columns:
            filtered_df.rename(columns={
            'Column_3': 'Websites',
            'Column_9': 'Address 1',
            'Column_10': 'Address 2',
            'Column_11': 'Address 3',
            }, inplace=True)
       
       # Display filtered preview
        if filtered_df.empty:
            st.warning("No data available for the selected filters.")
        else:
            st.subheader(t['filtered_preview'])
            st.dataframe(filtered_df)

    else:
        # If filters are not shown, use the unfiltered DataFrame
        filtered_df = result_df.copy()
    # Translate values in the filtered DataFrame
    #filtered_df = translate_values(filtered_df, t)

    # Add Main Category and Subcategory columns to the filtered preview based on column 13
    if len(filtered_df.columns) > 13:
        industry_column = filtered_df.columns[13]  # Column at index 13

        def map_to_main_and_subcategory(value):
            for main_category, subcategories in industry_mapping.items():
                if value in subcategories.keys():  # Check against the keys of subcategories
                    return main_category, value
            return "Other", "Other"

        # Apply the mapping to create new columns
        filtered_df[['Main Category', 'Subcategory']] = filtered_df[industry_column].apply(
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
    show_country_counts = st.toggle(t['rows_per_country'], value=True)
    if show_country_counts and t['column_country'] in filtered_df.columns:

        # Display the counts
        st.subheader(t['rows_per_country'])
        st.dataframe(initial_country_counts)

    # Count rows per Main Category and Subcategory based on filtered preview
    show_category_counts = st.toggle("📊 Rows Per Main Category and Subcategory", value=True)
    if show_category_counts and 'Main Category' in filtered_df.columns and 'Subcategory' in filtered_df.columns:

        # Display the counts
        st.subheader("📊 Rows Per Main Category and Subcategory (Filtered)")
        st.dataframe(initial_category_counts)