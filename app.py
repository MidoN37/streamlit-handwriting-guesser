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


# --- Configuration ---
NAMES_FILE_PATH = '/Users/user/Desktop/Medpharm.txt'
CHROMEDRIVER_PATH = '/usr/local/bin/chromedriver'
WEBSITE_URL = 'https://www.calligrapher.ai/'
OUTPUT_FOLDER_PATH = '/Users/user/Desktop/Handwr'

# Slider settings
TARGET_LEGIBILITY_VALUE = "0.39" # ~10%
TARGET_SPEED_VALUE = "9.51"     # Max speed

if not os.path.exists(OUTPUT_FOLDER_PATH):
    try:
        os.makedirs(OUTPUT_FOLDER_PATH)
    except OSError as e:
        st.error(f"Could not create directory {OUTPUT_FOLDER_PATH}: {e}")

# --- Selenium Functions ---

@st.cache_resource(show_spinner="Initializing handwriting engine...")
def get_webdriver():
    print("Initializing HEADLESS WebDriver...")
    service = Service(executable_path=CHROMEDRIVER_PATH)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080") # Use a reasonably large window size
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    prefs = {
        "download.default_directory": OUTPUT_FOLDER_PATH,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_svg_externally": True
    }
    options.add_experimental_option("prefs", prefs)
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
    try:
        slider = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, slider_id))
        )
        driver.execute_script(
            f"arguments[0].value = '{target_value}'; arguments[0].dispatchEvent(new Event('input'));",
            slider
        )
        time.sleep(0.2)
    except TimeoutException: pass
    except Exception as e: pass

# --- Function to Add Style and ViewBox using PROVIDED bbox ---
def enhance_svg(svg_string, bbox):
    """
    Adds path style and a viewBox based on provided bbox dictionary.
    """
    if not svg_string or not svg_string.strip().startswith('<svg'):
        print("DEBUG: enhance_svg received invalid SVG input.")
        return svg_string
    if not bbox or not all(k in bbox for k in ['x', 'y', 'width', 'height']):
         print("DEBUG: enhance_svg received invalid bbox. Using default.")
         # Fallback to a default large viewBox
         viewBox_value = '0 0 1000 500'
    else:
        # Add padding to the bbox values
        padding = 20
        vb_x = bbox['x'] - padding
        vb_y = bbox['y'] - padding
        vb_width = bbox['width'] + (2 * padding)
        vb_height = bbox['height'] + (2 * padding)

        # Ensure width/height are positive
        vb_width = max(vb_width, 1)
        vb_height = max(vb_height, 1)
        viewBox_value = f"{vb_x:.2f} {vb_y:.2f} {vb_width:.2f} {vb_height:.2f}"
        print(f"DEBUG: Using getBBox-derived viewBox: {viewBox_value}")


    try:
        namespaces = {'svg': 'http://www.w3.org/2000/svg'}
        ET.register_namespace('', namespaces['svg'])
        root = ET.fromstring(svg_string)

        # Set the viewBox
        root.set('viewBox', viewBox_value)

        # Remove explicit width/height - let CSS handle sizing
        if 'width' in root.attrib:
            del root.attrib['width']
        if 'height' in root.attrib:
            del root.attrib['height']

        # Find all path elements and apply style
        paths = root.findall('.//svg:path', namespaces=namespaces)
        print(f"DEBUG: Found {len(paths)} path elements in SVG.")
        for path in paths:
            path.set('style', 'stroke:black; stroke-width:2px; fill:none;')

        enhanced_svg_string = ET.tostring(root, encoding='unicode', method='xml')
        print("DEBUG: SVG enhanced successfully.")
        return enhanced_svg_string

    except ET.ParseError as e:
        print(f"Error parsing SVG: {e}")
        return svg_string # Return original on error
    except Exception as e:
        print(f"Unexpected error enhancing SVG: {e}")
        return svg_string # Return original on error

# --- Function to get and enhance the SVG using getBBox ---
@st.cache_data(show_spinner="Generating handwriting...")
def get_handwriting_svg(_driver_placeholder, name, legibility, speed):
    """
    Uses Selenium (HEADLESS) to generate handwriting, gets bbox via JS,
    extracts SVG source, and enhances it for display.
    """
    driver = get_webdriver()
    if not driver:
        st.error("WebDriver not available for generation.")
        return None

    svg_source = None
    enhanced_svg = None
    bbox = None
    print(f"Starting handwriting generation for '{name}'...")
    try:
        driver.get(WEBSITE_URL)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "text-input"))
        )
        set_slider_value(driver, "bias-slider", legibility)
        set_slider_value(driver, "speed-slider", speed)
        text_input = driver.find_element(By.ID, "text-input")
        text_input.clear()
        text_input.send_keys(name)
        write_button = driver.find_element(By.ID, "draw-button")
        write_button.click()
        time.sleep(2)
        print(f"Clicked Write! for '{name}'. Waiting for download button...")
        download_button_locator = (By.ID, "save-button")
        WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located(download_button_locator)
        )
        print("Download button is now visible.")
        time.sleep(0.5) # Delay before JS execution

        # --- Get Bounding Box using JavaScript ---
        try:
            bbox_script = "return document.getElementById('canvas').getBBox();"
            bbox = driver.execute_script(bbox_script)
            print(f"DEBUG: Raw bbox from getBBox(): {bbox}")
            # Ensure bbox has expected keys (sometimes returns empty dict if element not ready)
            if not bbox or not all(k in bbox for k in ['x', 'y', 'width', 'height']):
                print("WARN: getBBox() did not return valid data. Will use default viewBox.")
                bbox = None # Reset bbox so enhance_svg uses default
        except Exception as js_err:
            print(f"Error executing getBBox() script: {js_err}")
            bbox = None # Ensure enhance_svg uses default
        # --- End Get Bounding Box ---

        # Extract SVG source
        svg_canvas = driver.find_element(By.ID, "canvas")
        svg_source = driver.execute_script("return arguments[0].outerHTML;", svg_canvas)
        print("Extracted SVG source code.")

        # --- Enhance the extracted SVG using bbox ---
        if svg_source:
            enhanced_svg = enhance_svg(svg_source, bbox) # Pass bbox here
        else:
             print("SVG source was empty, skipping enhancement.")

    except TimeoutException as e:
        st.error(f"Error: Timed out (60s) waiting for download button for name '{name}'.")
    except NoSuchElementException as e:
        st.error(f"Error: Could not find element for name '{name}'.")
    except WebDriverException as e:
         st.error(f"WebDriver Error during generation for '{name}': {e}.")
         st.cache_resource.clear()
    except Exception as e:
        st.error(f"An unexpected error occurred while generating handwriting for '{name}': {e}")

    return enhanced_svg # Return the enhanced version


# --- Streamlit App Logic --- (Remains the same)

st.set_page_config(page_title="Handwriting Guesser", layout="centered")

# Inject Custom CSS
st.markdown("""
<style>
div.stImage {
    background-color: white;
    padding: 25px;
    border-radius: 10px;
    border: 1px solid #eee;
    margin-top: 20px;
    margin-bottom: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
    overflow: hidden;
}
div.stImage > img {
    max-width: 100%;
    max-height: 350px; /* Adjust if needed */
    object-fit: contain;
}
</style>
""", unsafe_allow_html=True)


st.title("✍️ Handwriting Guessing Game")
st.markdown("Guess the name written in the generated handwriting!")

# Load names
@st.cache_data
def load_names(file_path):
    try:
        with open(file_path, 'r') as f:
            names = [line.strip() for line in f if line.strip() and line != '\ufeff']
        if not names:
            st.error(f"No valid names found in the file: {file_path}")
            return None
        return names
    except FileNotFoundError:
        st.error(f"Error: Names file not found at {file_path}")
        return None
    except Exception as e:
        st.error(f"Error reading names file: {e}")
        return None

names_list = load_names(NAMES_FILE_PATH)

# Initialize session state variables
if 'current_name' not in st.session_state:
    st.session_state.current_name = None
if 'svg_data' not in st.session_state:
    st.session_state.svg_data = None
if 'guess_submitted' not in st.session_state:
    st.session_state.guess_submitted = False
if 'user_guess' not in st.session_state:
    st.session_state.user_guess = ""

# --- UI Elements ---

if names_list:
    if st.button("Get New Name & Image", key="new_name_button"):
        st.session_state.current_name = random.choice(names_list)
        st.session_state.svg_data = None
        st.session_state.guess_submitted = False
        st.session_state.user_guess = ""
        # st.info(f"Selected name: {st.session_state.current_name}. Generating image...")

        driver_instance = get_webdriver()
        if driver_instance:
            svg = get_handwriting_svg(id(driver_instance), st.session_state.current_name, TARGET_LEGIBILITY_VALUE, TARGET_SPEED_VALUE)
            if svg:
                st.session_state.svg_data = svg
                st.info("Handwriting image ready.")
            else:
                st.warning("Failed to generate or enhance handwriting image. Try again or get a new name.")
        else:
            st.error("Cannot generate image because WebDriver failed to initialize.")

    if st.session_state.svg_data:
        st.markdown("---")
        st.subheader("Guess this name:")

        # Display the DYNAMICALLY ENHANCED SVG data
        st.image(st.session_state.svg_data, use_container_width=True)

        with st.form(key='guess_form'):
            user_guess = st.text_input("Enter your guess:", key="guess_input", value=st.session_state.user_guess)
            submit_button = st.form_submit_button(label='Submit Guess')

            if submit_button:
                st.session_state.user_guess = user_guess
                st.session_state.guess_submitted = True

        if st.session_state.guess_submitted:
            st.markdown("---")
            if st.session_state.user_guess.strip().lower() == st.session_state.current_name.strip().lower():
                st.success(f"🎉 Correct! The name is **{st.session_state.current_name}**.")
                st.balloons()
            else:
                st.error(f"❌ Incorrect. Your guess was '{st.session_state.user_guess}'. The correct name was **{st.session_state.current_name}**.")

    elif st.session_state.current_name is not None and not st.session_state.svg_data:
         st.warning(f"Could not display image for '{st.session_state.current_name}'. Generation/Enhancement may have failed, see messages/logs.")

else:
    st.warning("Cannot start the game because the name list could not be loaded.")

st.markdown("---")
st.markdown("Powered by [Calligrapher.ai](https://www.calligrapher.ai/) and [Streamlit](https://streamlit.io).")