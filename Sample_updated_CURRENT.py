import streamlit as st
import os
import psycopg2
import shutil
from bs4 import BeautifulSoup
import google.generativeai as genai
import ollama
from dotenv import load_dotenv
import re
import json
import socket
import urllib.error
import urllib.request
import time
import zipfile
import tempfile
# --- Unified Filename Extraction Function ---
def extract_filename(file_name):
    base = os.path.splitext(file_name)[0]
    # Remove YB or HN prefix
    if base.startswith('YB') or base.startswith('HN'):
        base = base[2:]
    # Take everything before first underscore
    if '_' in base:
        base = base.split('_')[0]
    return base + '.txt'

# Load environment variables
load_dotenv()

# --- Configuration File for Gemini Sequence ---
GEMINI_SEQUENCE_CONFIG_FILE = "gemini_sequence_config.json"
DEFAULT_GEMINI_MODEL_SEQUENCE = [
    "gemini-2.0-flash-exp",
    "gemini-2.0-flash", 
    "gemini-1.5-flash"
]
    
def load_gemini_sequence():
    if os.path.exists(GEMINI_SEQUENCE_CONFIG_FILE):
        try:
            with open(GEMINI_SEQUENCE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("gemini_model_sequence")
        except (FileNotFoundError, json.JSONDecodeError):
            return None  # Don't fall back to default
    return None  # Don't fall back to default


def save_gemini_sequence(sequence):
    data = {"gemini_model_sequence": sequence}
    try:
        with open(GEMINI_SEQUENCE_CONFIG_FILE, "w") as f:
            json.dump(data, f)
        print("Gemini model sequence saved to file.") # Removed st.success for integration
    except Exception as e:
        st.error(f"❌ Error saving Gemini model sequence: {e}")

# Session state for authentication
if "user" not in st.session_state:
    st.session_state["user"] = None
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "show_login" not in st.session_state:
    st.session_state["show_login"] = True
if "show_register" not in st.session_state:
    st.session_state["show_register"] = False
if "show_forgot_password" not in st.session_state:
    st.session_state["show_forgot_password"] = False
if "show_change_password" not in st.session_state:
    st.session_state["show_change_password"] = False
if "user_role" not in st.session_state:
    st.session_state["user_role"] = None
if "app_config" not in st.session_state:
    loaded_sequence = load_gemini_sequence()
    st.session_state["app_config"] = {
        "input_folder": "",
        "output_folder": "",
        "completed_folder": "",
        "selected_model": None, # Will be set based on the sequence
        "model_provider": "Google Gemini",
        "gemini_api_key": "",
        "ollama_model": "deepseek-r1:1.5b",
        "temperature": 0.5,
        "gemini_model_sequence": loaded_sequence if loaded_sequence else []
# Load sequence on app start
    }
    st.session_state["app_config"]["selected_model"] = (
        st.session_state["app_config"]["gemini_model_sequence"][0]
        if st.session_state["app_config"]["gemini_model_sequence"]
        else None
    )
    st.session_state["app_config"]["selected_model"] = st.session_state["app_config"]["gemini_model_sequence"][0] if st.session_state["app_config"]["gemini_model_sequence"] else None
if "current_gemini_model_index" not in st.session_state:
    st.session_state["current_gemini_model_index"] = 0
if "working_model" not in st.session_state:
    st.session_state["working_model"] = None
if "exhausted_models" not in st.session_state:
    st.session_state["exhausted_models"] = set()
if "model_sequence_inputs" not in st.session_state:
    st.session_state["model_sequence_inputs"] = st.session_state["app_config"].get("gemini_model_sequence", []) + [None]
# Session state initialization - remove duplicate
if "exhausted_models" not in st.session_state:
    st.session_state["exhausted_models"] = set()
if "gemini_api_configured" not in st.session_state:
    st.session_state["gemini_api_configured"] = False
# Function to check internet connection
def check_internet_connection():
    """Checks for internet connection by trying to reach Google."""
    try:
        with urllib.request.urlopen('https://www.google.com', timeout=5) as response:
            return True
    except urllib.error.URLError:
        return False

def load_configuration():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT gemini_model_sequence FROM app_config_admin ORDER BY id LIMIT 1")
        row = cursor.fetchone()
        if row:
            loaded_sequence = json.loads(row[0])
            st.session_state["app_config"]["gemini_model_sequence"] = loaded_sequence
            st.session_state["app_config"]["selected_model"] = loaded_sequence[0] if loaded_sequence else None
            st.info(f"💾 Loaded {len(loaded_sequence)} models from database")
            # Load temperature if present
            if len(row) > 1 and row[1] is not None:
                st.session_state["app_config"]["temperature"] = float(row[1])
        else:
            st.warning("⚠ No Gemini model sequence found in DB. Please set it manually.")
            st.session_state["app_config"]["gemini_model_sequence"] = []
            st.session_state["app_config"]["selected_model"] = None

    except Exception as e:
        st.error(f"❌ Failed to load admin config: {e}")
    finally:
        cursor.close()
        conn.close()

def save_configuration():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE app_config_admin
            SET gemini_model_sequence = %s
            WHERE id = (SELECT id FROM app_config_admin ORDER BY id LIMIT 1)
            """,
            (
                json.dumps(st.session_state["app_config"]["gemini_model_sequence"]),
            )  
        )
        conn.commit()
        st.success("✅ Configuration saved to Supabase.")
    except Exception as e:
        st.error(f"❌ Failed to save admin config: {e}")
    finally:
        cursor.close()
        conn.close()
def login(email, password):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot log in.")
        return

    try:
        conn = get_connection()
        if not conn:
            st.error("❌ Could not connect to the database during login.")
            return

        cursor = conn.cursor()
        cursor.execute(
            "SELECT api_key, role, password, output_folder_path, completed_folder_path "
            "FROM user_api_keys WHERE email = %s",
            (email,)
        )
        result = cursor.fetchone()

        if not result:
            st.error("❌ User not found.")
            return

        db_api_key, db_role, db_password, output_path, completed_path = result

        # Validate password (plain text check – hash it in production)
        if password != db_password:
            st.error("❌ Incorrect password.")
            return

        # Store session state
        st.session_state["user"] = {
            "email": email,
            "api_key": db_api_key
        }
        st.session_state["logged_in"] = True
        st.session_state["show_login"] = False
        st.session_state["show_register"] = False
        st.session_state["show_forgot_password"] = False

        # Set user role
        st.session_state["user_role"] = db_role if db_role else "user"

        # Set folder paths

        st.session_state["app_config"]["output_folder"] = output_path or "output_files"
        st.session_state["app_config"]["completed_folder"] = completed_path or "completed_files"
        

        # Default fallback if API key is missing
        if not db_api_key:
            default_api_key = st.session_state["app_config"].get("gemini_api_key")
            if default_api_key:
                st.session_state["user"]["api_key"] = default_api_key
                st.info(f"🔑 Using default API Key for new user: {email}")
            else:
                st.warning(f"⚠️ No API Key found for {email} and no default key is set.")
                st.session_state["user"]["api_key"] = None
        else:
            st.success(f"🔑 API Key fetched for {email}")

        load_configuration()
        st.session_state["model_sequence_inputs"] = st.session_state["app_config"]["gemini_model_sequence"] + [None]


        st.success("✅ Successfully logged in!")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Login failed: {e}")

    finally:
        if conn:
            cursor.close()
            conn.close()
            
# --- Modified register() Function (using your existing get_connection()) ---
def register(email, password):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot register.")
        return
    try:
        # Generate API Key
        api_key = os.urandom(24).hex()
        role = "user"  # Default role

        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            # Check if user already exists
            cursor.execute("SELECT * FROM user_api_keys WHERE email = %s", (email,))
            if cursor.fetchone():
                st.warning("⚠️ Email already registered.")
            else:
                cursor.execute(
                    "INSERT INTO user_api_keys (email, password, api_key, role) VALUES (%s, %s, %s, %s)",
                    (email, password, api_key, role)
                )
                conn.commit()
                st.success("✅ Account created! Please login.")
                st.session_state["show_register"] = False
                st.session_state["show_login"] = True
                st.rerun()
            cursor.close()
            conn.close()
        else:
            st.error("❌ Could not connect to the database.")
    except Exception as e:
        st.error(f"❌ Registration failed: {e}")


# --- Modified manage_user_api_keys() Function (using your existing get_connection()) ---
def manage_user_api_keys():
    st.subheader("🔑 Manage User API Keys")
    conn = get_connection()
    if not conn:
        st.error("❌ Could not connect to the database.")
        return

    cursor = conn.cursor()
    cursor.execute("SELECT email, api_key FROM user_api_keys")
    api_key_data = cursor.fetchall()

    if not api_key_data:
        st.info("No user API keys found.")
    else:
        st.info("List of User API Keys:")
        for email, current_api_key in api_key_data:
            col1, col2 = st.columns([3, 5])
            with col1:
                st.markdown(f"**Email:** {email}")
            with col2:
                new_api_key = st.text_input("API Key", current_api_key, type="password", key=f"api_key_input_{email}")
                if new_api_key != current_api_key:
                    if st.button("Update API Key", key=f"update_api_key_{email}"):
                        try:
                            update_cursor = conn.cursor()
                            update_cursor.execute("UPDATE user_api_keys SET api_key = %s WHERE email = %s", (new_api_key, email))
                            conn.commit()
                            st.success(f"✅ API Key updated for {email}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error updating API Key for {email}: {e}")
                        finally:
                            update_cursor.close()

    st.markdown("---")
    st.subheader("➕ Add New User API Key")
    new_email = st.text_input("Email for new API Key:")
    new_api = st.text_input("New API Key:", type="password")
    if st.button("➕ Add API Key"):
        if new_email and new_api:
            try:
                insert_cursor = conn.cursor()
                insert_cursor.execute("INSERT INTO user_api_keys (email, api_key) VALUES (%s, %s)", (new_email, new_api))
                conn.commit()
                st.success(f"✅ API Key added for {new_email}")
                st.rerun()
            except psycopg2.errors.UniqueViolation:
                st.error(f"❌ Email '{new_email}' already exists in the API Key table.")
                conn.rollback()
            except Exception as e:
                st.error(f"❌ Error adding API Key: {e}")
            finally:
                insert_cursor.close()
        else:
            st.warning("Please enter both email and API Key.")

    cursor.close()
    conn.close()

def logout():
    # Clear all session state on logout
    keys_to_keep = ["show_login", "show_register", "show_forgot_password"]
    keys_to_clear = [key for key in st.session_state.keys() if key not in keys_to_keep]
    for key in keys_to_clear:
        del st.session_state[key]
    
    # Reset essential states
    st.session_state["user"] = None
    st.session_state["logged_in"] = False
    st.session_state["user_role"] = None
    st.session_state["show_login"] = True
    st.success("✅ Logged out successfully!")
    st.rerun()

def send_password_reset_email(email):
    st.info("📬 To reset your password, please contact the administrator.")

def change_password(current_password, new_password):
    if not st.session_state.get("user"):
        st.error("❌ No user logged in.")
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM user_api_keys WHERE email = %s", (st.session_state["user"]["email"],))
        result = cursor.fetchone()
        if not result or result[0] != current_password:
            st.error("❌ Current password is incorrect.")
            return
        cursor.execute("UPDATE user_api_keys SET password = %s WHERE email = %s", (new_password, st.session_state["user"]["email"]))
        conn.commit()
        st.success("🔑 Password changed successfully!")
    except Exception as e:
        st.error(f"❌ Error changing password: {e}")
    finally:
        cursor.close()
        conn.close()

# --- Promote/Demote Admin ---
def promote_to_admin(email):
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can perform this action")
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_api_keys SET role = 'admin' WHERE email = %s", (email,))
        cursor.execute("SELECT * FROM user_api_keys WHERE email = %s", (email,))
        if not cursor.fetchone():
            st.warning("⚠️ User not found.")

        conn.commit()
        st.success(f"✅ User {email} promoted to admin.")
    except Exception as e:
        st.error(f"❌ Error promoting user: {e}")
    finally:
        cursor.close()
        conn.close()

def demote_from_admin(email):
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can perform this action")
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_api_keys SET role = 'user' WHERE email = %s", (email,))
        conn.commit()
        st.success(f"✅ User {email} demoted to user.")
    except Exception as e:
        st.error(f"❌ Error demoting user: {e}")
    finally:
        cursor.close()
        conn.close()

# --- Manage Users from Supabase (was Firebase) ---
def manage_users():
    st.subheader("🧑‍💻 Manage Users")
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can manage users.")
        return

    conn = get_connection()
    if not conn:
        st.error("❌ Could not connect to the database.")
        return

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email, role FROM user_api_keys")
        users_data = cursor.fetchall()

        for email, role in users_data:
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.markdown(f"**Email:** {email}")
            with col2:
                st.markdown(f"**Role:** {role}")
            with col3:
                if role == "user" and email != st.session_state["user"]["email"]:
                    if st.button("Promote to Admin", key=f"promote_{email}"):
                        promote_to_admin(email)
                        st.rerun()
                elif role == "admin" and email != st.session_state["user"]["email"]:
                    if st.button("Demote to User", key=f"demote_{email}"):
                        demote_from_admin(email)
                        st.rerun()
    except Exception as e:
        st.error(f"❌ Error fetching users: {e}")
    finally:
        cursor.close()
        conn.close()
def auth_section():
    st.title("🔒 Authentication")
    
    # Tab-based navigation for cleaner UI
    tab1, tab2, tab3 = st.tabs(["Login", "Register", "Forgot Password"])
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                login(email, password)
    
    with tab2:
        with st.form("register_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            if st.form_submit_button("Register", use_container_width=True):
                if password == confirm_password:
                    register(email, password)
                else:
                    st.error("Passwords do not match!")
    
    
    with tab3:
        st.info("📧 Contact admin for password reset")


def get_connection():
    try:
        conn = psycopg2.connect(
        host=st.secrets["supabase"]["host"],
        port=st.secrets["supabase"]["port"],
        dbname=st.secrets["supabase"]["database"],
        user=st.secrets["supabase"]["user"],
        password=st.secrets["supabase"]["password"],
        sslmode="require"
    )

        return conn
    except Exception as e:
        st.error(f"❌ Could not connect to Supabase: {e}")
        return None


def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator='\n')
    # Remove any potential script or style content that might still be present
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    # Further cleaning: remove extra whitespace and newlines
    text = ' '.join(text.split())
    return text


def generate_prompt(extracted_text, selected_questions):
    prompt = f"""
    ## AI Assistant for Legal Document Analysis
    Extracted Text:
    {extracted_text}
    """
    if selected_questions:
        prompt += "\n### Selected Tasks:\n"
        for idx, question in enumerate(selected_questions, 1):
            prompt += f"✅ Task {idx}: {question}\n"
    else:
        prompt += "\n❌ No tasks selected."

    prompt += "\n\n*Instructions:*\n"
    prompt += "- Answer each task based on the extracted text.\n"
    prompt += "- If a task cannot be answered, state 'Information not available.'\n"
    return prompt

def get_gemini_response(prompt):
    if not check_internet_connection():
        return "❌ No internet connection."

    temperature = st.session_state["app_config"].get("temperature", 0.5)
    
    # Initialize exhausted_models if not exists
    if "exhausted_models" not in st.session_state:
        st.session_state["exhausted_models"] = set()
    
    # Initialize quota_exceeded_shown flag
    if "quota_exceeded_shown" not in st.session_state:
        st.session_state["quota_exceeded_shown"] = False
    
    # Use working model if we found one that works
    if "working_model" in st.session_state and st.session_state["working_model"]:
        working_model = st.session_state["working_model"]
        if working_model not in st.session_state["exhausted_models"]:
            try:
                st.info(f"🤖 Using model: {working_model}")
                model_instance = genai.GenerativeModel(working_model)
                response = model_instance.generate_content(
                    prompt,
                    generation_config={"temperature": temperature}
                )
                return f"[Response from: {working_model}]\n\n{response.text}"
            except Exception as e:
                error_msg = str(e).lower()
                if ("quota" in error_msg or "rate limit" in error_msg or "resource_exhausted" in error_msg or "429" in str(e)):
                    st.session_state["exhausted_models"].add(working_model)
                    st.session_state["working_model"] = None
                    st.warning(f"⚠️ Model {working_model} quota exceeded, switching...")
                else:
                    st.session_state["working_model"] = None
    
    # Need to find a working model - use only configured sequence
    configured_sequence = st.session_state["app_config"].get("gemini_model_sequence", [])
    if not configured_sequence:
        return "❌ No models configured."
    
    # Filter out exhausted models
    available_models = [m for m in configured_sequence if m not in st.session_state["exhausted_models"]]
    
    if not available_models:
        if not st.session_state["quota_exceeded_shown"]:
            st.error(f"❌ All {len(configured_sequence)} models quota exceeded, switching to DeepSeek")
            st.session_state["quota_exceeded_shown"] = True
        deepseek_response = get_deepseek_response(prompt, st.session_state["app_config"]["ollama_model"])
        return f"[Response from: DeepSeek]\n\n{deepseek_response}"
    
    for model in available_models:
        try:
            st.info(f"🤖 Trying model: {model}")
            model_instance = genai.GenerativeModel(model)
            response = model_instance.generate_content(
                prompt,
                generation_config={"temperature": temperature}
            )
            st.session_state["working_model"] = model
            st.success(f"✅ Successfully using model: {model}")
            return f"[Response from: {model}]\n\n{response.text}"
        except Exception as e:
            error_msg = str(e).lower()
            if ("quota" in error_msg or "rate limit" in error_msg or "resource_exhausted" in error_msg or "429" in str(e)):
                st.session_state["exhausted_models"].add(model)
                st.warning(f"⚠️ Model {model} quota exceeded, trying next...")
                continue
            else:
                st.warning(f"⚠️ Model {model} failed, trying next...")
                continue

    # If ALL models failed
    if not st.session_state["quota_exceeded_shown"]:
        st.error(f"❌ All {len(configured_sequence)} models quota exceeded, switching to DeepSeek")
        st.session_state["quota_exceeded_shown"] = True
    deepseek_response = get_deepseek_response(prompt, st.session_state["app_config"]["ollama_model"])
    return f"[Response from: DeepSeek]\n\n{deepseek_response}"

def get_deepseek_response(prompt, selected_model):
    if not check_internet_connection():
        return "❌ No internet connection."
    
    temperature = st.session_state["app_config"].get("temperature", 0.5)
    try:
        response = ollama.chat(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature}
        )
        response_content = response['message']['content']
        if '<think>' in response_content:
            response_content = response_content.split('</think>')[-1].strip()
        return response_content
    except Exception as e:
        return f"❌ Error generating response: {str(e)}"

def clear_processing_state():
    """Clear all processing-related session state"""
    keys_to_clear = [
        "zip_responses", "show_zip_download", "processed_files_count",
        "processing_stopped", "working_model", "exhausted_models", "quota_exceeded_shown"
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    
    # Reset exhausted models and quota flag
    st.session_state["exhausted_models"] = set()
    st.session_state["quota_exceeded_shown"] = False

def clear_output_folder():
    """Clear output folder of previous results"""
    output_folder = st.session_state["app_config"]["output_folder"]
    if os.path.exists(output_folder):
        for file in os.listdir(output_folder):
            if file.endswith(".txt"):
                try:
                    os.remove(os.path.join(output_folder, file))
                except:
                    pass
def read_txt_file(file_path):
    """
    Reads a text file and returns its content.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except UnicodeDecodeError:
        # Try another encoding if UTF-8 fails
        with open(file_path, "r", encoding="latin-1") as f:
            return f.read()

def process_html(file_path, file_name, selected_questions):
    if not check_internet_connection():
        return None

    config = st.session_state["app_config"]
    output_folder = config["output_folder"]
    completed_folder = config["completed_folder"]

    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)

    # Determine file type and process accordingly
    file_extension = os.path.splitext(file_name)[1].lower()
    
    if file_extension in ['.html', '.htm']:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                file_content = f.read()
        extracted_text = extract_text_from_html(file_content)
    elif file_extension in ['.txt']:
        extracted_text = read_txt_file(file_path)
    else:
        return None

    formatted_prompt = generate_prompt(extracted_text, selected_questions)

    response = None
    try:
        if config["model_provider"] == "Google Gemini":
            if not st.session_state.get("gemini_api_configured", False):
                api_key = st.session_state["user"].get("api_key")
                if api_key:
                    genai.configure(api_key=api_key)
                    st.session_state["gemini_api_configured"] = True
                else:
                    response = "Error: No API key available."
            if not response:
                response = get_gemini_response(formatted_prompt)
        else:
            response = get_deepseek_response(formatted_prompt, config["ollama_model"])
    except Exception as e:
        response = f"Error: Could not process file due to: {e}"

    txt_file_name = extract_filename(file_name)
    txt_output_path = os.path.join(output_folder, txt_file_name)
    with open(txt_output_path, "w", encoding="utf-8") as f:
        f.write(response if response else "Error: No response generated.")

    # Move processed file to completed folder
    if not os.path.exists(completed_folder):
        os.makedirs(completed_folder, exist_ok=True)

    try:
        destination_path = os.path.join(completed_folder, file_name)
        shutil.move(file_path, destination_path)
    except Exception as e:
        pass

    return response, txt_file_name

# SOLUTION 2: Updated process_html_in_folder function
def process_html_in_folder(file_path, file_name, selected_questions, destination_subfolder):
    if not check_internet_connection():
        return None

    config = st.session_state["app_config"]
    output_folder = config["output_folder"]
    subfolder_name = os.path.basename(os.path.dirname(file_path))
    output_subfolder = os.path.join(output_folder, subfolder_name)

    if not os.path.exists(output_subfolder):
        os.makedirs(output_subfolder, exist_ok=True)

    # Determine file type and process accordingly
    file_extension = os.path.splitext(file_name)[1].lower()
    
    if file_extension in ['.html', '.htm']:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                file_content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1") as f:
                file_content = f.read()
        extracted_text = extract_text_from_html(file_content)
    elif file_extension in ['.txt']:
        extracted_text = read_txt_file(file_path)
    else:
        return None

    formatted_prompt = generate_prompt(extracted_text, selected_questions)

    response = None
    try:
        if config["model_provider"] == "Google Gemini":
            if not st.session_state.get("gemini_api_configured", False):
                api_key = st.session_state["user"].get("api_key")
                if api_key:
                    genai.configure(api_key=api_key)
                    st.session_state["gemini_api_configured"] = True
                else:
                    response = "Error: No API key available."
            if not response:
                response = get_gemini_response(formatted_prompt)
        else:
            response = get_deepseek_response(formatted_prompt, config["ollama_model"])
    except Exception as e:
        response = f"Error: Could not process file due to: {e}"

    txt_file_name = extract_filename(file_name)
    txt_output_path = os.path.join(output_subfolder, txt_file_name)
    with open(txt_output_path, "w", encoding="utf-8") as f:
        f.write(response if response else "Error: No response generated.")

    # Move processed HTML file to completed subfolder
    try:
        destination_path = os.path.join(destination_subfolder, file_name)
        shutil.copy2(file_path, destination_path)
    except Exception as e:
        pass

    return response, txt_file_name
    
def process_folder(folder_path, selected_questions):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot process folder.")
        return

    completed_folder = st.session_state["app_config"]["completed_folder"]
    if not os.path.exists(completed_folder):
        os.makedirs(completed_folder, exist_ok=True)

    subfolders_to_process = [
        os.path.join(folder_path, d) for d in os.listdir(folder_path)
        if os.path.isdir(os.path.join(folder_path, d))
    ]

    if not subfolders_to_process:
        st.warning("⚠ No subfolders found in the source folder.")
        return

    total_subfolders = len(subfolders_to_process)
    progress_bar = st.progress(0)

    moved_subfolders_count = 0
    error_files = []
    for i, subfolder_path in enumerate(subfolders_to_process):
        subfolder_name = os.path.basename(subfolder_path)
        st.info(f"📂 Processing subfolder {i+1}/{total_subfolders}: {subfolder_name}")

        supported_files = []
        for root, _, files in os.walk(subfolder_path):
            for file in files:
                if file.lower().endswith((".htm", ".html", ".txt")):
                    supported_files.append(os.path.join(root, file))

        if not supported_files:
            st.warning(f"⚠ No supported files (.html/.htm/.txt) found in subfolder: {subfolder_name}")
        else:
            destination_subfolder_path = os.path.join(completed_folder, subfolder_name)
            if not os.path.exists(destination_subfolder_path):
                os.makedirs(destination_subfolder_path, exist_ok=True)

            for file_path in supported_files:
                file_name = os.path.basename(file_path)
                st.info(f"📄 Processing file in {subfolder_name}: {file_name}")
                try:
                    response = process_html_in_folder(file_path, file_name, selected_questions, destination_subfolder_path)
                    if not response:
                        error_files.append(file_name)
                        st.warning(f"⚠️ Processing failed for {file_name} in {subfolder_name}.")
                    else:
                        st.text_area(f"Response for {file_name} in {subfolder_name}", response, height=150, key=f"response_{subfolder_name}_{file_name}")
                except Exception as e:
                    error_files.append(file_name)
                    st.error(f"❌ Error processing {file_name} in {subfolder_name}: {e}.")

        try:
            if os.path.exists(subfolder_path):
                shutil.rmtree(subfolder_path)
                moved_subfolders_count += 1
                st.success(f"✅ Processed subfolder '{subfolder_name}' and moved contents to: {destination_subfolder_path}")
        except Exception as e:
            st.error(f"❌ Error removing source subfolder '{subfolder_name}' after processing: {e}")

        progress_bar.progress((i + 1) / total_subfolders)

    if error_files:
        st.warning(f"⚠️ The following files failed to process: {', '.join(error_files)}")
    st.success(f"✅ Successfully attempted to process {total_subfolders} subfolders. Moved {moved_subfolders_count} subfolders.")
    

def get_available_gemini_models():
    """Dynamically fetch ALL available models from the Google Generative AI API."""
    if not check_internet_connection():
        return []
    
    try:
        # First ensure an API key is configured
        api_key = st.session_state["app_config"]["gemini_api_key"]
        if not api_key:
            # Try to get from user session if available
            api_key = st.session_state["user"].get("api_key") if "user" in st.session_state else None
            if not api_key:
                return []
        
        # Configure the API with the available key
        genai.configure(api_key=api_key)
        
        # Get ALL models - no filtering at all
        models = genai.list_models()
        all_models = []
        for model in models:
            model_name = model.name.split('/')[-1]
            all_models.append(model_name)
        
        all_models.sort()
        
        if all_models:
            st.success(f"✅ Found {len(all_models)} total models!")
        return all_models

    except Exception as e:
        st.error(f"❌ Error fetching models: {e}")
        return []
    
def admin_ui():
    st.title("⚙️ Admin Panel")

    with st.sidebar:
        st.subheader(f"👤 Admin: {st.session_state['user']['email']}")
        if st.button("Manage User API Keys"):
            st.session_state["show_manage_api_keys"] = not st.session_state.get("show_manage_api_keys", False)
            st.session_state["show_manage_users"] = False
            st.session_state["show_app_config"] = True
            st.session_state["show_gemini_manage"] = False
            st.session_state["show_deepseek_manage"] = False
        if st.button("Manage Users"):
            st.session_state["show_manage_users"] = not st.session_state.get("show_manage_users", False)
            st.session_state["show_manage_api_keys"] = False
            st.session_state["show_app_config"] = True
            st.session_state["show_gemini_manage"] = False
            st.session_state["show_deepseek_manage"] = False
        st.markdown("---")
        st.subheader("🛠️ Configuration")
        if st.button("Application"):
            st.session_state["show_app_config"] = True
            st.session_state["show_manage_api_keys"] = False
            st.session_state["show_manage_users"] = False
            st.session_state["show_gemini_manage"] = False
            st.session_state["show_deepseek_manage"] = False
        if st.button("Questions"):
            st.session_state["show_app_config"] = False
            st.session_state["show_manage_api_keys"] = False
            st.session_state["show_manage_users"] = False
            if st.session_state["app_config"]["model_provider"] == "Google Gemini":
                st.session_state["show_gemini_manage"] = not st.session_state.get("show_gemini_manage", False)
                st.session_state["show_deepseek_manage"] = False
            else:
                st.session_state["show_deepseek_manage"] = not st.session_state.get("show_deepseek_manage", False)
                st.session_state["show_gemini_manage"] = False
        if st.button("Logout"):
            logout()
            return

    if st.session_state.get("show_manage_api_keys", False):
        manage_user_api_keys()

    if st.session_state.get("show_manage_users", False):
        manage_users()

    if st.session_state.get("show_app_config", True):
        st.subheader("⚙️ Application Configuration")

        model_provider = st.radio("Select Model Provider:", ["Google Gemini", "DeepSeek (Ollama)"], index=0 if st.session_state["app_config"]["model_provider"] == "Google Gemini" else 1)
        st.session_state["app_config"]["model_provider"] = model_provider

        if model_provider == "Google Gemini":
        # Dynamically fetch available Gemini models
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                if "available_gemini_models" not in st.session_state:
                    st.session_state["available_gemini_models"] = get_available_gemini_models()
            with col2:
                if st.button("🔄 Get ALL Models"):
                    st.session_state["available_gemini_models"] = get_available_gemini_models()
                    # Auto-populate with ALL available models
                    if st.session_state["available_gemini_models"]:
                        st.session_state["app_config"]["gemini_model_sequence"] = st.session_state["available_gemini_models"]
                        st.session_state["model_sequence_inputs"] = st.session_state["available_gemini_models"] + [None]
                        st.success(f"✅ Auto-configured ALL {len(st.session_state['available_gemini_models'])} models!")
                        st.info(f"📋 Models: {', '.join(st.session_state['available_gemini_models'][:5])}{'...' if len(st.session_state['available_gemini_models']) > 5 else ''}")
                        st.rerun()
            with col3:
                if st.button("🗑️ Reset Models"):
                    st.session_state["app_config"]["gemini_model_sequence"] = []
                    st.session_state["model_sequence_inputs"] = [None]
                    st.success("✅ Model sequence reset!")
                    st.rerun()
            
            gemini_models = st.session_state["available_gemini_models"]
            
            if "model_sequence_inputs" not in st.session_state:
                st.session_state["model_sequence_inputs"] = st.session_state["app_config"].get("gemini_model_sequence", []) + [None]

            st.subheader("Gemini Model Sequence")
            st.info("📝 Select models in order of preference. The system will try each model in sequence if quota limits are reached.")
            
            updated_sequence = []
            for i, model in enumerate(st.session_state["model_sequence_inputs"]):
                col1, col2 = st.columns([3, 1])
                with col1:
                    options = [None] + gemini_models
                    default_index = options.index(model) if model in options else 0
                    selected_model = st.selectbox(f"Model {i+1}", options, index=default_index, key=f"model_select_{i}")
                    if selected_model:
                        updated_sequence.append(selected_model)
                with col2:
                    if len(st.session_state["model_sequence_inputs"]) > 1: # Show delete button if more than one
                        if st.button("🗑️", key=f"delete_model_{i}"):
                            del st.session_state["model_sequence_inputs"][i]
                            st.rerun()

            if st.button("➕ Add Model"):
                st.session_state["model_sequence_inputs"].append(None)
                st.rerun()

            # Filter out None values and update the sequence in app_config
            st.session_state["app_config"]["gemini_model_sequence"] = [model for model in updated_sequence if model]

            if st.session_state["app_config"]["gemini_model_sequence"]:
                sequence = st.session_state['app_config']['gemini_model_sequence']
                display_sequence = ', '.join(sequence[:5]) + ('...' if len(sequence) > 5 else '')
                st.markdown(f"**Current Model Sequence ({len(sequence)} models):** {display_sequence}")
                if len(sequence) > 5:
                    with st.expander(f"View all {len(sequence)} models"):
                        st.write(', '.join(sequence))
                st.session_state["app_config"]["selected_model"] = st.session_state["app_config"]["gemini_model_sequence"][0] # Set the first model as the initial selected one
            else:
                st.warning("⚠️ Please select at least one Gemini model in the sequence.")
                st.session_state["app_config"]["selected_model"] = None

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Active Gemini Model:** {st.session_state['app_config'].get('selected_model', 'Not Selected')}")
            with col2:
                st.session_state["app_config"]["gemini_api_key"] = st.text_input(
                    "Gemini API Key",
                    st.session_state["app_config"]["gemini_api_key"],
                    type="password"
                )
        else:
            model_options = ["deepseek-r1:1.5b"]
            current_model = st.session_state["app_config"]["ollama_model"]
            default_index = 0

            if current_model in model_options:
                default_index = model_options.index(current_model)

            st.session_state["app_config"]["ollama_model"] = st.selectbox(
                "DeepSeek Model",
                model_options,
                index=default_index
            )

        if st.button("💾 Save Configuration"):
            save_configuration()

    if st.session_state.get("show_gemini_manage", False):
        manage_questions("Gemini")

    if st.session_state.get("show_deepseek_manage", False):
        manage_questions("Deep_seek")
def manage_questions(table_name):
    st.subheader(f"Manage {table_name} Questions")
    conn = get_connection()
    if not conn:
        st.error("❌ Could not connect to the database.")
        return

    cursor = conn.cursor()

    # Fetch existing questions
    cursor.execute(f"SELECT id, q_id, ques FROM {table_name} ORDER BY id")
    questions_data = cursor.fetchall()
    st.session_state[f"{table_name}_questions"] = {row[0]: row[2] for row in questions_data}

    if not st.session_state.get(f"{table_name}_questions"):
        st.info(f"No questions available in the {table_name} table.")
    else:
        st.info(f"List of {table_name} Questions:")
        for question_id, question_text in st.session_state[f"{table_name}_questions"].items():
            col1, col2 = st.columns([1, 5])
            with col1:
                st.markdown(f"**ID:** {question_id}")
            with col2:
                updated_question = st.text_area("Question", question_text, key=f"question_edit_{table_name}_{question_id}")
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Update", key=f"update_btn_{table_name}_{question_id}"):
                        try:
                            update_cursor = conn.cursor()
                            update_cursor.execute(f"UPDATE {table_name} SET ques = %s WHERE id = %s", (updated_question, question_id))
                            conn.commit()
                            st.success(f"✅ Question ID {question_id} updated!")
                            renumber_questions(conn, table_name)  # Renumber after update
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error updating question ID {question_id}: {e}")
                        finally:
                            if 'update_cursor' in locals():
                                update_cursor.close()
                with col_btn2:
                    if st.button("🗑️ Delete", key=f"delete_btn_{table_name}_{question_id}"):
                        try:
                            delete_cursor = conn.cursor()
                            delete_cursor.execute(f"DELETE FROM {table_name} WHERE id = %s", (question_id,))
                            conn.commit()
                            st.success(f"✅ Question ID {question_id} deleted!")
                            renumber_questions(conn, table_name)  # Renumber after delete
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error deleting question ID {question_id}: {e}")
                        finally:
                            if 'delete_cursor' in locals():
                                delete_cursor.close()
            st.markdown("---")

    st.subheader(f"➕ Add New Question to {table_name}")
    new_question = st.text_area("Enter new question to add:", key=f"new_question_{table_name}")
    if st.button(f"➕ Add Question to {table_name}"):
        if new_question:
            try:
                # 1. Get the next available ID to generate q_id
                add_cursor = conn.cursor()
                add_cursor.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table_name}")
                next_id = add_cursor.fetchone()[0]
                next_q_id = f"Q_{next_id}"
                
                # 2. Insert the new question with both q_id and ques
                add_cursor.execute(f"INSERT INTO {table_name} (q_id, ques) VALUES (%s, %s)", (next_q_id, new_question))
                conn.commit()
                st.success(f"✅ Question '{new_question[:20]}...' added (renumbering...)!")
                add_cursor.close()

                # 3. Immediately renumber the questions
                renumber_questions(conn, table_name)
                st.rerun()

            except Exception as e:
                if conn:
                    conn.rollback()
                st.error(f"❌ Error adding question: {e}")
            finally:
                if conn:
                    cursor.close()
                    conn.close()
def renumber_questions(conn, table_name):
    
    cursor = conn.cursor()
    try:
        # Fetch all questions ordered by the original id
        cursor.execute(f"SELECT ques FROM {table_name} ORDER BY id")
        questions = cursor.fetchall()

        # Clear the table
        cursor.execute(f"DELETE FROM {table_name}")
        conn.commit()

        # Insert questions with new sequential ids and q_ids
        for i, (ques,) in enumerate(questions):
            new_id = i + 1
            new_q_id = f"Q_{new_id}"
            cursor.execute(f"INSERT INTO {table_name} (id, q_id, ques) VALUES (%s, %s, %s)", (new_id, new_q_id, ques))
        conn.commit()
        st.info(f"🔄 Questions in '{table_name}' table renumbered and resorted.")
    except Exception as e:
        conn.rollback()
        st.error(f"❌ Error renumbering questions in '{table_name}': {e}")
    finally:
        cursor.close()


def get_gemini_questions():
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot fetch questions.")
        return []
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT q_id, ques FROM Gemini ORDER BY id") # Order by id to maintain sequence
            rows = cursor.fetchall()
            return [(row[0], row[1]) for row in rows] if rows else [] # Returns a list of tuples (q_id, ques)
        except Exception as e:
            st.error(f"⚠ Error fetching questions from Gemini table: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    return []

def get_deepseek_questions():
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot fetch questions.")
        return []
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT q_id, ques FROM Deep_seek ORDER BY id") # Order by id to maintain sequence
            rows = cursor.fetchall()
            return [(row[0], row[1]) for row in rows] if rows else [] # Returns a list of tuples (q_id, ques)
        except Exception as e:
            st.error(f"⚠ Error fetching questions from Deep_seek table: {e}")
            return []
        finally:
            cursor.close()
            conn.close()
    return []

# SOLUTION 3: Updated user_ui function with ordered question processing and moved ZIP download
def user_ui():
    st.title("⚖ Document Analyzer")

    with st.sidebar:
        st.subheader(f"👤 User: {st.session_state['user']['email']}")
        st.info("ℹ Using admin-configured settings")
        if st.button("Change Password"):
            st.session_state["show_change_password"] = True
        if st.button("Logout"):
            logout()
            return

    if st.session_state["show_change_password"]:
        with st.form("change_password_form"):
            st.subheader("Change Password")
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_new_password = st.text_input("Confirm New Password", type="password")
            change_button = st.form_submit_button("Change Password")

            if change_button:
                if new_password == confirm_new_password:
                    change_password(current_password, new_password)
                else:
                    st.error("New passwords don't match!")
    else:
        st.markdown("---")
        processing_mode = st.radio(
            "Select Processing Mode:",
            ["Upload Single File", "Upload Zip of Files"],
            index=0
        )
        uploaded_file = None
        uploaded_zip = None
        if processing_mode == "Upload Single File":
            uploaded_file = st.file_uploader("📥 Upload an HTML or TXT file", type=["htm", "html", "txt"])
        else:
            uploaded_zip = st.file_uploader("📦 Upload a ZIP file containing HTML/TXT files", type=["zip"])

        st.subheader("🌡️ Temperature Control")
        st.warning(
            "Adjusting the temperature may affect the accuracy of the results.  \n"
            "Lower values (e.g., 0.0) provide more accurate answers, while higher values (e.g., 1.0) \n"
            "can lead to more creative but potentially less reliable responses."
        )
        temp_options = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        saved_temperature = st.session_state["app_config"].get("temperature")
        default_temp_index = 0  # Default to the index of 0.0

        if saved_temperature is not None and saved_temperature in temp_options:
            default_temp_index = temp_options.index(saved_temperature)

        st.session_state["app_config"]["temperature"] = st.selectbox(
            "Temperature",
            temp_options,
            index=default_temp_index
        )
        st.markdown("### Select Questions")
        questions = []
        if st.session_state["app_config"]["model_provider"] == "Google Gemini":
            questions = get_gemini_questions()
        else:
            questions = get_deepseek_questions()

        # FIXED: Store selected questions in order with their original indices
        cols = st.columns(4)  # Adjust the number of columns as needed
        selected_questions_with_order = []  # Store (index, question_text) tuples

        for i, (q_id, question_text) in enumerate(questions):
            with cols[i % 4]:  # This will distribute questions across 4 columns
                if st.checkbox(f"{q_id}", key=question_text):
                    selected_questions_with_order.append((i, question_text))

        # Sort by original index to maintain order
        selected_questions_with_order.sort(key=lambda x: x[0])
        selected_questions = [q[1] for q in selected_questions_with_order]  # Extract just the questions in order

        st.markdown("---")

        # Initialize session state for tracking processed files
        if "processed_files_count" not in st.session_state:
            st.session_state["processed_files_count"] = 0
        if "show_zip_download" not in st.session_state:
            st.session_state["show_zip_download"] = False

        # Process based on mode
        if processing_mode == "Upload Single File":
            if st.button("🚀 Analyze Document"):
                if uploaded_file is None:
                    st.error("⚠️ Please upload an HTML or TXT file before analyzing.")
                else:
                    # Clear previous results
                    clear_processing_state()
                    clear_output_folder()
                    
                    try:
                        file_name = uploaded_file.name
                        try:
                            file_content = uploaded_file.getvalue().decode("utf-8")
                        except UnicodeDecodeError:
                            file_content = uploaded_file.getvalue().decode("latin-1")

                        # Save to a temporary location instead of input_folder
                        temp_path = os.path.join(tempfile.gettempdir(), file_name)
                        with open(temp_path, "w", encoding="utf-8") as f:
                            f.write(file_content)

                        result = process_html(temp_path, file_name, selected_questions)

                        if result:
                            response, clean_filename = result
                            st.success("✅ Analysis Complete!")
                            st.text_area("Response", response, height=150, key="response_single_file")
                            st.download_button(
                                label="📥 Download Response",
                                data=response,
                                file_name=clean_filename,  # Use cleaned filename
                                mime="text/plain",
                                key="download_single_file"
                            )
                            st.session_state["processed_files_count"] = 1
                            st.session_state["show_zip_download"] = True
                        else:
                            st.error("❌ Document analysis failed. See error messages above.")
                    except Exception as e:
                        st.error(f"❌ Error during file processing: {e}")
        elif processing_mode == "Upload Zip of Files":
            if st.button("🚀 Process Zip"):
                if uploaded_zip is None:
                    st.error("⚠️ Please upload a ZIP file before processing.")
                else:
                    process_zip_file(uploaded_zip, selected_questions)
    # Show responses and download button after processing
    if st.session_state.get("show_zip_download", False):
        st.markdown("---")
        st.subheader("📦 Download All Responses")
        # Show all responses from session state
        if "zip_responses" in st.session_state:
            for resp in st.session_state["zip_responses"]:
                st.text_area(f"Response for {resp['display_name']}", resp["response"], height=150, key=f"response_{resp['original_name']}")
                st.download_button(
                    label=f"📥 Download Response for {resp['display_name']}",
                    data=resp["response"],
                    file_name=resp["clean_filename"],
                    mime="text/plain",
                    key=f"download_{resp['original_name']}"
                )
        zip_buffer = create_zip_and_download(st.session_state["app_config"]["output_folder"])
        if zip_buffer:
            st.download_button(
                label="📦 Download All Responses as ZIP",
                data=zip_buffer,
                file_name="all_responses.zip",
                mime="application/zip",
                key="main_zip_download"
            )

# SOLUTION 4: Updated process_zip_file function with stop functionality
def process_zip_file(zip_file, selected_questions):
    # Clear previous results
    clear_processing_state()
    clear_output_folder()
    
    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        supported_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith((".htm", ".html", ".txt")):
                    supported_files.append(os.path.join(root, file))
        if not supported_files:
            st.warning("⚠ No supported files (.html/.htm/.txt) found in the zip.")
            return
        
        st.session_state["zip_responses"] = []
        st.session_state["processing_stopped"] = False
        
        # Create progress display
        progress_placeholder = st.empty()
        status_placeholder = st.empty()
        
        total_files = len(supported_files)
        for i, file_path in enumerate(supported_files):
            if st.session_state.get("processing_stopped", False):
                break
                
            # Update progress
            with progress_placeholder.container():
                st.progress((i + 1) / total_files, text=f"Processing {i+1}/{total_files} files")
            
            original_name = os.path.basename(file_path)
            with status_placeholder.container():
                st.info(f"📄 {original_name}")
            
            result = process_html(file_path, original_name, selected_questions)
            if result:
                response, clean_filename = result
            else:
                response = "Error: Could not process this file."
                clean_filename = extract_filename(original_name)
            
            import re
            display_name = re.sub(r'^(HN|YB)([a-zA-Z]\d+)_.*', r'\2', os.path.splitext(original_name)[0]) + os.path.splitext(original_name)[1]
            st.session_state["zip_responses"].append({
                "display_name": display_name,
                "response": response,
                "clean_filename": clean_filename,
                "original_name": original_name
            })
        
        progress_placeholder.empty()
        status_placeholder.empty()
        
        st.session_state["show_zip_download"] = True
        st.success(f"🎉 Processed {len(st.session_state['zip_responses'])} files")
    finally:
        shutil.rmtree(temp_dir)
        st.session_state["processing_stopped"] = False

# SOLUTION 5: New function to create ZIP buffer (replaces create_zip_and_download)
# SOLUTION 5: Updated function to replace create_zip_and_download
def create_zip_and_download(output_folder):
    """Create ZIP buffer for download without automatic sidebar placement"""
    import io
    
    zip_buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            files_added = 0
            for root, _, files in os.walk(output_folder):
                for file in files:
                    if file.endswith(".txt"):
                        file_path = os.path.join(root, file)
                        try:
                            try:
                                with open(file_path, "r", encoding="utf-8",errors="ignore") as f:
                                    content = f.read().strip()
                            except UnicodeDecodeError:
                                with open(file_path, "r", encoding="latin-1") as f:
                                    content = f.read().strip()
                            arcname = os.path.relpath(file_path, output_folder)
                            zipf.writestr(arcname, content)
                            files_added += 1
                        except Exception as e:
                            continue
            if files_added == 0:
                return None
        zip_buffer.seek(0)
        return zip_buffer.getvalue()
    except Exception as e:
        st.error(f"Error creating ZIP: {e}")
        return None

# SOLUTION 6: Updated main function (remove the old create_zip_and_download call)
def main():
    if not st.session_state["logged_in"]:
        auth_section()
    else:
        # Load config from Supabase on refresh after login
        if "config_loaded" not in st.session_state:
            load_configuration()
            st.session_state["config_loaded"] = True

        if st.session_state["user_role"] == "admin":
            admin_ui()
        else:
            user_ui()


if __name__ == "__main__":
    main()
