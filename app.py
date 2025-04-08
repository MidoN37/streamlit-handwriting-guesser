import streamlit as st
import random
import time
import os
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
import xml.etree.ElementTree as ET
import glob # To find files

# --- Configuration ---
# No longer a single file path, we'll detect .txt files
WEBSITE_URL = 'https://www.calligrapher.ai/'
SPECIAL_CATEGORY_FILE = 'Medpharm.txt'
SPECIAL_CATEGORY_NAME = "Tous les médicaments"

# Slider settings
TARGET_LEGIBILITY_VALUE = "0.15" # ~10%? Adjust as needed
TARGET_SPEED_VALUE = "9.51"     # Max speed

# --- Selenium Functions --- (Keep these as they are)

@st.cache_resource(show_spinner="Initializing handwriting engine...")
def get_webdriver():
    """Initializes and returns a HEADLESS WebDriver instance for Streamlit Cloud."""
    print("Initializing HEADLESS WebDriver for Streamlit Cloud...")
    service = Service()
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    try:
        driver = webdriver.Chrome(service=service, options=options)
        print("HEADLESS WebDriver initialized.")
        return driver
    except WebDriverException as e:
        st.error(f"Failed to initialize WebDriver: {e}")
        st.stop()
    except Exception as e:
        st.error(f"An unexpected error occurred during WebDriver setup: {e}")
        st.stop()

def set_slider_value(driver, slider_id, target_value):
    """Sets slider value using JS."""
    try:
        slider = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, slider_id))
        )
        driver.execute_script(
            f"arguments[0].value = '{target_value}'; arguments[0.dispatchEvent(new Event('input'));",
            slider
        )
        time.sleep(0.2)
    except TimeoutException: pass
    except Exception as e: pass

def enhance_svg(svg_string, bbox):
    """Adds path style and a viewBox based on provided bbox dictionary."""
    if not svg_string or not svg_string.strip().startswith('<svg'):
        return svg_string
    if not bbox or not all(k in bbox for k in ['x', 'y', 'width', 'height']):
         print("DEBUG: enhance_svg received invalid bbox. Using default.")
         viewBox_value = '0 0 1000 500' # Default fallback
    else:
        padding = 20
        vb_x = bbox['x'] - padding
        vb_y = bbox['y'] - padding
        vb_width = bbox['width'] + (2 * padding)
        vb_height = bbox['height'] + (2 * padding)
        vb_width = max(vb_width, 1)
        vb_height = max(vb_height, 1)
        viewBox_value = f"{vb_x:.2f} {vb_y:.2f} {vb_width:.2f} {vb_height:.2f}"
    try:
        namespaces = {'svg': 'http://www.w3.org/2000/svg'}
        ET.register_namespace('', namespaces['svg'])
        root = ET.fromstring(svg_string)
        root.set('viewBox', viewBox_value)
        if 'width' in root.attrib: del root.attrib['width']
        if 'height' in root.attrib: del root.attrib['height']
        paths = root.findall('.//svg:path', namespaces=namespaces)
        for path in paths:
            path.set('style', 'stroke:black; stroke-width:2px; fill:none;')
        enhanced_svg_string = ET.tostring(root, encoding='unicode', method='xml')
        return enhanced_svg_string
    except Exception as e:
        print(f"Error enhancing SVG: {e}")
        return svg_string

@st.cache_data(show_spinner="Une seconde s'il vous plaît !")
def get_handwriting_svg(_driver_placeholder, name, legibility, speed):
    """Gets and enhances SVG using getBBox."""
    driver = get_webdriver()
    if not driver: return None
    svg_source, enhanced_svg, bbox = None, None, None
    try:
        driver.get(WEBSITE_URL)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "text-input")))
        set_slider_value(driver, "bias-slider", legibility)
        set_slider_value(driver, "speed-slider", speed)
        text_input = driver.find_element(By.ID, "text-input")
        text_input.clear()
        text_input.send_keys(name)
        write_button = driver.find_element(By.ID, "draw-button")
        write_button.click()
        time.sleep(2)
        download_button_locator = (By.ID, "save-button")
        WebDriverWait(driver, 60).until(EC.visibility_of_element_located(download_button_locator))
        time.sleep(0.5)
        try:
            bbox_script = "return document.getElementById('canvas').getBBox();"
            bbox = driver.execute_script(bbox_script)
            if not bbox or not all(k in bbox for k in ['x', 'y', 'width', 'height']): bbox = None
        except Exception as js_err: bbox = None
        svg_canvas = driver.find_element(By.ID, "canvas")
        svg_source = driver.execute_script("return arguments[0].outerHTML;", svg_canvas)
        if svg_source: enhanced_svg = enhance_svg(svg_source, bbox)
    except Exception as e:
        st.error(f"Error generating handwriting for '{name}': {e}")
    return enhanced_svg

# --- NEW: Load Categories Function ---
@st.cache_data
def load_categories():
    """Loads drug names from .txt files into categories."""
    categories = {}
    script_dir = os.path.dirname(__file__)
    txt_files = glob.glob(os.path.join(script_dir, "*.txt"))
    ignore_files = ['requirements.txt', 'packages.txt']
    print(f"Found files: {txt_files}") # Debug

    all_meds_list = [] # To store names from Medpharm.txt separately if needed

    for full_path in txt_files:
        filename = os.path.basename(full_path)

        if filename in ignore_files:
            continue

        category_name = os.path.splitext(filename)[0] # Get filename without .txt

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                names = [line.strip() for line in f if line.strip() and line != '\ufeff']

            if not names:
                print(f"Warning: No names found in {filename}")
                continue # Skip empty files

            if filename == SPECIAL_CATEGORY_FILE:
                 # Store separately for now, handle special category later
                 all_meds_list = names
                 print(f"Loaded {len(names)} names for special category '{SPECIAL_CATEGORY_NAME}' from {filename}")
            else:
                # Use filename (without extension) as category key
                categories[category_name] = names
                print(f"Loaded {len(names)} names for category '{category_name}' from {filename}")

        except FileNotFoundError:
            print(f"Error: File not found {full_path}") # Should not happen with glob
        except Exception as e:
            print(f"Error reading file {filename}: {e}")

    # Now, add the special category if its list has names
    if all_meds_list:
        categories[SPECIAL_CATEGORY_NAME] = all_meds_list

    if not categories:
        st.error("Aucune catégorie de médicaments n'a été trouvée ! Assurez-vous que les fichiers .txt sont présents.")
        return None

    # Sort categories alphabetically, but keep "Tous les médicaments" conceptually separate/last
    sorted_categories = sorted([cat for cat in categories if cat != SPECIAL_CATEGORY_NAME])
    if SPECIAL_CATEGORY_NAME in categories:
        sorted_categories.append(SPECIAL_CATEGORY_NAME) # Add special category at the end

    # Return the data dictionary and the sorted list of keys
    return categories, sorted_categories


# --- Streamlit App Logic ---

st.set_page_config(page_title="Lecteur d'Ordonnance", layout="centered")

# Inject Custom CSS (Keep as is)
st.markdown("""
<style>
div.stImage { background-color: white; padding: 25px; border-radius: 10px; border: 1px solid #eee; margin-top: 20px; margin-bottom: 20px; display: flex; justify-content: center; align-items: center; overflow: hidden; }
div.stImage > img { max-width: 100%; max-height: 350px; object-fit: contain; }
</style>
""", unsafe_allow_html=True)


st.title("Savez-vous lire vos médicaments? 🤔")
st.markdown("Voici une application simple créée par El Mahdi Nih pour vous aider à lire les ordonnances mal rédigées!")

# --- Load Category Data ---
loaded_data = load_categories()
categories_data = None
category_names_list = []

if loaded_data:
    categories_data, category_names_list = loaded_data

# --- Initialize/Manage Session State ---
if 'selected_category' not in st.session_state:
    st.session_state.selected_category = None # Start with no category selected
if 'current_name' not in st.session_state:
    st.session_state.current_name = None
if 'svg_data' not in st.session_state:
    st.session_state.svg_data = None
if 'guess_submitted' not in st.session_state:
    st.session_state.guess_submitted = False
if 'user_guess' not in st.session_state:
    st.session_state.user_guess = ""

# --- Callback to reset game when category changes ---
def reset_game_state():
    st.session_state.current_name = None
    st.session_state.svg_data = None
    st.session_state.guess_submitted = False
    st.session_state.user_guess = ""
    print(f"Category changed, game state reset.")

# --- UI Elements ---

if categories_data and category_names_list:
    # --- Category Selection ---
    st.header("1. Choisissez une catégorie")
    selected_cat = st.selectbox(
        "Catégories disponibles:",
        options=category_names_list,
        index=None, # No default selection
        placeholder="Sélectionnez une catégorie...",
        key='category_selector', # Use a key to access value easily if needed
        on_change=reset_game_state # Reset game if selection changes
    )
    st.session_state.selected_category = selected_cat # Update state

    st.markdown("---") # Visual separator

    # --- Game Area (only shown if category is selected) ---
    if st.session_state.selected_category:
        st.header("2. Devinez le médicament")

        # Get names for the currently selected category
        current_category_names = categories_data.get(st.session_state.selected_category, [])

        if not current_category_names:
             st.warning(f"Aucun médicament trouvé pour la catégorie : {st.session_state.selected_category}")
        else:
            if st.button(f"Nouveau médicament)", key="new_name_button"):
                st.session_state.current_name = random.choice(current_category_names)
                st.session_state.svg_data = None
                st.session_state.guess_submitted = False
                st.session_state.user_guess = ""

                driver_instance = get_webdriver()
                if driver_instance:
                    svg = get_handwriting_svg(id(driver_instance), st.session_state.current_name, TARGET_LEGIBILITY_VALUE, TARGET_SPEED_VALUE)
                    if svg:
                        st.session_state.svg_data = svg
                        st.info("Pouvez-vous lire cette mauvaise écriture ?")
                    else:
                        st.warning("Failed to generate handwriting image.")
                else:
                    st.error("Cannot generate image because WebDriver failed to initialize.")

            if st.session_state.svg_data:
                # st.subheader("Quel est ce médicament?") # Subheader might be redundant now
                st.image(st.session_state.svg_data, use_container_width=True)

                with st.form(key='guess_form'):
                    user_guess = st.text_input("Votre réponse:", key="guess_input", value=st.session_state.user_guess)
                    submit_button = st.form_submit_button(label='Vérifier')

                    if submit_button:
                        st.session_state.user_guess = user_guess
                        st.session_state.guess_submitted = True

                if st.session_state.guess_submitted:
                    st.markdown("---")
                    if st.session_state.user_guess.strip().lower() == st.session_state.current_name.strip().lower():
                        st.success(f"🎉 C'est vrai ! Le médicament est vraiment **{st.session_state.current_name}**.")
                        st.balloons()
                    else:
                        st.error(f"❌ Faux '{st.session_state.user_guess}'. C'était en fait **{st.session_state.current_name}**.")

            # Message if category selected but no image generated yet/failed
            elif st.session_state.current_name is not None and not st.session_state.svg_data:
                 st.warning("Problème lors de la génération de l'image.")
            elif st.session_state.current_name is None:
                 st.info("Cliquez sur 'Nouveau médicament' pour commencer.")

    else:
        st.info("Veuillez sélectionner une catégorie pour commencer.")

else:
    st.error("Impossible de charger les catégories de médicaments. Vérifiez les fichiers .txt et les logs.")


st.markdown("---")
st.markdown("Créé par El Mahdi Nih | Bonne chance !")