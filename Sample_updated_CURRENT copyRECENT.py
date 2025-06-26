import streamlit as st
import os
import psycopg2
import shutil
from bs4 import BeautifulSoup
import pyrebase
import google.generativeai as genai
import ollama
from dotenv import load_dotenv
import re
import json
import socket
import urllib.error
import urllib.request
import time
# Load environment variables
load_dotenv()

# Firebase Configuration
firebase_config = {
    "apiKey": "AIzaSyCQVrVcKhUkE3e6PG6C_ewx-3ty9uj7eO0",
    "authDomain": "lawbot-11325.firebaseapp.com",
    "projectId": "lawbot-11325",
    "storageBucket": "lawbot-11325.firebasestorage.app",
    "messagingSenderId": "770333510012",
    "appId": "1:770333510012:web:ab44b10f59a148922dbcf9",
    "measurementId": "G-32ZF3VXT5G",
    "databaseURL": "https://lawbot-11325-default-rtdb.firebaseio.com/"
}

  
firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()
db = firebase.database()

# --- Configuration File for Gemini Sequence ---
GEMINI_SEQUENCE_CONFIG_FILE = "gemini_sequence_config.json"
DEFAULT_GEMINI_MODEL_SEQUENCE = ["gemini-2.5-pro-exp-03-25", "gemini-2.0-flash", "gemini-1.5-pro"]
    
def load_gemini_sequence():
    if os.path.exists(GEMINI_SEQUENCE_CONFIG_FILE):
        try:
            with open(GEMINI_SEQUENCE_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("gemini_model_sequence", DEFAULT_GEMINI_MODEL_SEQUENCE)
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULT_GEMINI_MODEL_SEQUENCE
    return DEFAULT_GEMINI_MODEL_SEQUENCE

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
    st.session_state["app_config"] = {
        "input_folder": "",
        "output_folder": "",
        "completed_folder": "",
        "selected_model": None, # Will be set based on the sequence
        "model_provider": "Google Gemini",
        "gemini_api_key": "",
        "ollama_model": "deepseek-r1:1.5b",
        "temperature": 0.5,
        "gemini_model_sequence": load_gemini_sequence() # Load sequence on app start
    }
    st.session_state["app_config"]["selected_model"] = st.session_state["app_config"]["gemini_model_sequence"][0] if st.session_state["app_config"]["gemini_model_sequence"] else None
if "current_gemini_model_index" not in st.session_state:
    st.session_state["current_gemini_model_index"] = 0
if "model_sequence_inputs" not in st.session_state:
    st.session_state["model_sequence_inputs"] = st.session_state["app_config"].get("gemini_model_sequence", []) + [None]
if "gemini_models_last_fetch" not in st.session_state:
    st.session_state["gemini_models_last_fetch"] = 0
# Function to check internet connection
def check_internet_connection():
    """Checks for internet connection by trying to reach Google."""
    try:
        with urllib.request.urlopen('https://www.google.com', timeout=5) as response:
            return True
    except urllib.error.URLError:
        return False

# Load configuration from Firebase
def load_configuration():
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot load configuration.")
        return
    try:
        config = db.child("app_config").get().val()
        if config:
            # Keep existing config, but ensure Gemini sequence is loaded from file
            config["gemini_model_sequence"] = st.session_state["app_config"]["gemini_model_sequence"]
            st.session_state["app_config"] = config
    except Exception as e:
        st.error(f"Error loading configuration: {e}")

def save_configuration():
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot save configuration.")
        return
    # Save Gemini sequence to local file
    save_gemini_sequence(st.session_state["app_config"]["gemini_model_sequence"])
    # Ensure Gemini sequence in Firebase matches the file
    temp_config = st.session_state["app_config"].copy()
    temp_config["gemini_model_sequence"] = load_gemini_sequence() # Reload to ensure latest from file
    try:
        db.child("app_config").set(temp_config)
        st.success("Configuration saved successfully!")
    except Exception as e:
        st.error(f"Error saving configuration to Firebase: {e}")

# --- Modified login() Function (using your existing get_connection()) ---
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
            "SELECT api_key, role, password, input_folder_path, output_folder_path, completed_folder_path "
            "FROM user_api_keys WHERE email = %s",
            (email,)
        )
        result = cursor.fetchone()

        if not result:
            st.error("❌ User not found.")
            return

        db_api_key, db_role, db_password, input_path, output_path, completed_path = result

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
        st.session_state["app_config"]["input_folder"] = input_path or "input_files"
        st.session_state["app_config"]["output_folder"] = output_path or "output_files"
        st.session_state["app_config"]["completed_folder"] = completed_path or "completed_files"
        st.success(f"📁 Folder paths loaded for {email}")

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
    st.session_state["user"] = None
    st.session_state["logged_in"] = False
    st.session_state["user_role"] = None
    st.session_state["show_login"] = True
    st.success("✅ Logged out successfully!")
    st.rerun()

def send_password_reset_email(email):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot send reset email.")
        return
    try:
        auth.send_password_reset_email(email)
        st.success("📧 Password reset email sent! Check your inbox.")
        st.session_state["show_forgot_password"] = False
        st.session_state["show_login"] = True
        st.rerun()
    except Exception as e:
        st.error(f"❌ Error sending reset email: {e}")

def change_password(current_password, new_password):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot change password.")
        return
    try:
        user = auth.sign_in_with_email_and_password(
            st.session_state["user"]["email"],
            current_password
        )
        auth.update_password(user["idToken"], new_password)
        st.success("🔑 Password changed successfully!")
        st.session_state["show_change_password"] = False
        st.rerun()
    except Exception as e:
        st.error(f"❌ Error changing password: {e}")

def promote_to_admin(email):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot promote user.")
        return
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can perform this action")
        return

    try:
        # Find user by email
        users = db.child("users").get().val()

        user_id = None
        for uid, user_data in users.items():
            if user_data.get("email") == email:
                user_id = uid
                break

        if user_id:
            db.child("users").child(user_id).update({"role": "admin"})
            st.success(f"✅ User {email} promoted to admin.")
        else:
            st.error(f"❌ User with email {email} not found.")
    except Exception as e:
        st.error(f"❌ Error promoting user: {e}")

def demote_from_admin(email):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot demote user.")
        return
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can perform this action")
        return

    try:
        # Find user by email
        users = db.child("users").get().val()
        user_id = None
        for uid, user_data in users.items():
            if user_data.get("email") == email:
                user_id = uid
                break

        if user_id:
            db.child("users").child(user_id).update({"role": "user"})
            st.success(f"✅ User {email} demoted to user.")
        else:
            st.error(f"❌ User with email {email} not found.")
    except Exception as e:
        st.error(f"❌ Error demoting user: {e}")
def manage_users():
    st.subheader("🧑‍💻 Manage Users")
    if st.session_state["user_role"] != "admin":
        st.error("❌ Only admins can manage users.")
        return

    users_data = db.child("users").get().val()
    if users_data:
        for user_id, user_info in users_data.items():
            email = user_info.get("email")
            role = user_info.get("role", "user")
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.markdown(f"**Email:** {email if email else 'N/A'}")
            with col2:
                st.markdown(f"**Role:** {role}")
            with col3:
                if role == "user" and email != st.session_state["user"]["email"]:
                    if st.button("Promote to Admin", key=f"promote_{user_id}"):
                        promote_to_admin(email)
                        st.rerun()
                elif role == "admin" and email is not None and st.session_state["user"].get("email") is not None and email != st.session_state["user"]["email"] and (email is not None and email.lower() != "rajacharya3242@gmail.com"): # Added another explicit None check
                    if st.button("Demote to User", key=f"demote_{user_id}"):
                        demote_from_admin(email)
                        st.rerun()
    else:
        st.info("No users registered.")
def auth_section():
    st.title("🔒 Authentication")
    if st.session_state["show_login"]:
        with st.form("login_form"):
            st.subheader("Login")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                login(email, password)
                return
        st.markdown("Don't have an account? [Register here](#register)")
        st.markdown("[Forgot password?](#forgot-password)")

    if st.session_state["show_register"]:
        with st.form("register_form"):
            st.subheader("Register")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Register")
            if submitted:
                if password == confirm_password:
                    register(email, password)
                    return
                else:
                    st.error("Passwords do not match!")
        st.markdown("Already have an account? [Login here](#login)")

    if st.session_state["show_forgot_password"]:
        with st.form("forgot_password_form"):
            st.subheader("Forgot Password")
            email = st.text_input("Enter your email:")
            submitted = st.form_submit_button("Send Reset Email")
            if submitted:
                send_password_reset_email(email)
                return
        st.markdown("Remember your password? [Login here](#login)")

    st.markdown("---")
    cols = st.columns(3)
    with cols[0]:
        if st.button("Register"):
            st.session_state["show_login"] = False
            st.session_state["show_register"] = True
            st.session_state["show_forgot_password"] = False
            st.rerun()
    with cols[1]:
        if st.button("Login"):
            st.session_state["show_login"] = True
            st.session_state["show_register"] = False
            st.session_state["show_forgot_password"] = False
            st.rerun()
    with cols[2]:
        if st.button("Forgot Password"):
            st.session_state["show_login"] = False
            st.session_state["show_register"] = False
            st.session_state["show_forgot_password"] = True
            st.rerun()

def get_connection():
    try:
        conn = psycopg2.connect(
            host="aws-0-ap-south-1.pooler.supabase.com",
            port=6543,
            dbname="postgres",
            user="postgres.zyuonbuasxdxdizxxuzj",
            password="Law_bot@1234",
            sslmode="require"  # Important for Supabase!
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

def get_gemini_response(prompt): # Removed selected_model argument
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot get Gemini response.")
        return "❌ No internet connection."

    temperature = st.session_state["app_config"].get("temperature")
    model_sequence = st.session_state["app_config"].get("gemini_model_sequence", [])

    for model in model_sequence:
        st.info(f"⏳ Attempting to get response from **{model}**...") # Inform the user
        try:
            model_instance = genai.GenerativeModel(model)
            response = model_instance.generate_content(
                prompt,
                generation_config={"temperature": temperature}
            )
            st.success(f"✅ Response received from **{model}**!") # Indicate success
            return f"[Response from: {model}]\n\n{response.text}" # Add model name to response
        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "rate limit" in error_msg:
                st.warning(f"⚠ Quota exceeded for {model}, trying next model...")
                continue # Try the next model in the sequence
            else:
                st.error(f"❌ Error with model {model}: {e}")
                return f"❌ Error with model {model}: {e}"

    # If all Gemini models failed, switch to DeepSeek
    st.warning("⚠ All configured Gemini models have failed. Switching to DeepSeek...")
    deepseek_response = get_deepseek_response(prompt, st.session_state["app_config"]["ollama_model"])
    return f"[Response from: DeepSeek - {st.session_state['app_config']['ollama_model']}]\n\n{deepseek_response}"

def get_deepseek_response(prompt, selected_model):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot get DeepSeek response.")
        return "❌ No internet connection."
    temperature = st.session_state["app_config"].get("temperature") # Get temperature
    try:
        response = ollama.chat(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": temperature}
        )
        response_content = response['message']['content']
        if '<think>' in response_content:
            response_content = response_content.split('</think>')[-1].strip()
        return f"[Response from: DeepSeek - {selected_model}]\n\n{response_content}" # Add model name
    except Exception as e:
        return f"❌ Error generating response: {str(e)}"

def read_txt_file(file_path):
    """
    Reads a text file and returns its content.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        # Try another encoding if UTF-8 fails
        with open(file_path, "r", encoding="latin-1") as f:
            return f.read()
        
def process_html(file_path, file_name, selected_questions):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot process file.")
        return None

    config = st.session_state["app_config"]
    output_folder = config["output_folder"]
    input_folder = config["input_folder"]
    completed_folder = config["completed_folder"]

    st.info(f"ℹ️ Processing file: {file_path}")

    output_subfolder = output_folder
    if not os.path.exists(output_subfolder):
        os.makedirs(output_subfolder, exist_ok=True)



    # Determine file type and process accordingly
    file_extension = os.path.splitext(file_name)[1].lower()
    
    if file_extension in ['.html', '.htm']:
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
        extracted_text = extract_text_from_html(file_content)
    elif file_extension in ['.txt']:
        extracted_text = read_txt_file(file_path)
    else:
        st.error(f"❌ Unsupported file type: {file_extension}")
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
                    st.info("🔑 Configured Gemini API key")
                else:
                    st.error("❌ No API key available. Please contact admin.")
                    return None
            response = get_gemini_response(formatted_prompt)
        else:
            response = get_deepseek_response(formatted_prompt, config["ollama_model"])
    except Exception as e:
        st.error(f"❌ Error generating response: {e}")
        return None

    if response:
        # Save .txt file
        base_name = os.path.splitext(file_name)[0]
        name_part = base_name.split('_')[0]  # remove suffix part
        if name_part.startswith("YB"):
            extracted_name = name_part[2:]
        elif name_part.startswith("HN"):
            extracted_name = name_part[2:]
        else:
            extracted_name = name_part

        txt_file_name = f"{extracted_name}.txt"
        txt_file_path = os.path.join(output_subfolder, txt_file_name)
        with open(txt_file_path, "w", encoding="utf-8") as txt_file:
            txt_file.write(response)

        # Move processed file to completed folder
        if not os.path.exists(completed_folder):
            os.makedirs(completed_folder, exist_ok=True)

        try:
            destination_path = os.path.join(completed_folder, file_name)
            shutil.move(file_path, destination_path)
            st.success(f"✅ Moved processed file to: {destination_path}")
        except Exception as e:
            st.error(f"❌ Error moving processed file: {e}")

        return response
    else:
        return None


# New function to process HTML files within their folder structure
def process_html_in_folder(file_path, file_name, selected_questions, destination_subfolder):
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot process HTML.")
        return None

    config = st.session_state["app_config"]
    output_folder = config["output_folder"]

    st.info(f"ℹ️ Processing file: {file_path}")

    subfolder_name = os.path.basename(os.path.dirname(file_path))
    output_subfolder = os.path.join(output_folder, subfolder_name)

    if not os.path.exists(output_subfolder):
        os.makedirs(output_subfolder, exist_ok=True)

    # Determine file type and process accordingly
    file_extension = os.path.splitext(file_name)[1].lower()
    
    if file_extension in ['.html', '.htm']:
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
        extracted_text = extract_text_from_html(file_content)
    elif file_extension in ['.txt']:
        extracted_text = read_txt_file(file_path)
    else:
        st.error(f"❌ Unsupported file type: {file_extension}")
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
                    st.info("🔑 Configured Gemini API key")
                else:
                    st.error("❌ No API key available. Please contact admin.")
                    return None
            response = get_gemini_response(formatted_prompt)
        else:
            response = get_deepseek_response(formatted_prompt, config["ollama_model"])
    except Exception as e:
        st.error(f"❌ Error generating response: {e}")
        return None

    if response:
        base_name = os.path.splitext(file_name)[0]  # e.g., HN40169_31 or YBm67453_1002

        # Remove suffix part (everything after the first underscore)
        if "_" in base_name:
            name_part = base_name.split('_')[0]  # Get part before first underscore
        else:
            name_part = base_name

        # Now remove prefix if it exists
        if name_part.startswith("YB"):
            extracted_name = name_part[2:]  # Remove "YB"
        elif name_part.startswith("HN"):
            extracted_name = name_part[2:]  # Remove "HN"
        else:
            extracted_name = name_part

        txt_file_name = f"{extracted_name}.txt"
        txt_file_path = os.path.join(output_subfolder, txt_file_name)
        with open(txt_file_path, "w", encoding="utf-8") as txt_file:
            txt_file.write(response)

        # Move processed HTML file to completed subfolder instead of root completed folder
        try:
            destination_path = os.path.join(destination_subfolder, file_name)
            shutil.copy2(file_path, destination_path)  # Copy the file to destination first
            st.success(f"✅ Copied processed file to: {destination_path}")
        except Exception as e:
            st.error(f"❌ Error copying processed file: {e}")

        return response
    else:
        return None
    
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
    for i, subfolder_path in enumerate(subfolders_to_process):
        subfolder_name = os.path.basename(subfolder_path)
        st.info(f"📂 Processing subfolder {i+1}/{total_subfolders}: {subfolder_name}")

        supported_files = []
        files_processed_successfully = True

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
                        files_processed_successfully = False
                        st.warning(f"⚠️ Processing failed for {file_name} in {subfolder_name}. Folder will not be moved.")
                        break
                    else:
                        st.text_area(f"Response for {file_name} in {subfolder_name}", response, height=150, key=f"response_{subfolder_name}_{file_name}")
                except Exception as e:
                    files_processed_successfully = False
                    st.error(f"❌ Error processing {file_name} in {subfolder_name}: {e}. Folder will not be moved.")
                    break

            if not files_processed_successfully:
                st.error(f"🛑 Errors in '{subfolder_name}'. Skipping folder move.")
                continue

        try:
            if os.path.exists(subfolder_path) and files_processed_successfully:
                shutil.rmtree(subfolder_path)
                moved_subfolders_count += 1
                st.success(f"✅ Processed subfolder '{subfolder_name}' and moved contents to: {destination_subfolder_path}")
        except Exception as e:
            st.error(f"❌ Error removing source subfolder '{subfolder_name}' after processing: {e}")

        progress_bar.progress((i + 1) / total_subfolders)

    st.success(f"✅ Successfully attempted to process {total_subfolders} subfolders. Moved {moved_subfolders_count} subfolders.")


def get_available_gemini_models():
    """Dynamically fetch available Gemini models from the Google Generative AI API."""
    if not check_internet_connection():
        st.error("❌ No internet connection. Cannot fetch Gemini models.")
        return []
    
    try:
        # First ensure an API key is configured
        api_key = st.session_state["app_config"]["gemini_api_key"]
        if not api_key:
            # Try to get from user session if available
            api_key = st.session_state["user"].get("api_key") if "user" in st.session_state else None
            if not api_key:
                st.warning("⚠️ No API key available. Using default model list.")
                # Return a default list as fallback
                return ["gemini-2.5-pro-exp-03-25", "gemini-2.0-pro", "gemini-1.5-pro", "gemini-2.0-flash"]
        
        # Configure the API with the available key
        genai.configure(api_key=api_key)
        
        # Get list of available models
        models = genai.list_models()
        # Filter for only Gemini models
        gemini_models = [model.name.split('/')[-1] for model in models if 'gemini' in model.name.lower()]
        
        if not gemini_models:
            st.warning("⚠️ No Gemini models found. Using default model list.")
            return ["gemini-2.5-pro-exp-03-25", "gemini-2.0-pro", "gemini-1.5-pro", "gemini-2.0-flash"]
        
        return gemini_models
   
    except Exception as e:
        st.error(f"❌ Error fetching Gemini models: {e}")
        # Return a default list as fallback
        return ["gemini-2.5-pro-exp-03-25", "gemini-2.0-pro", "gemini-1.5-pro", "gemini-2.0-flash"]
    
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
            if "available_gemini_models" not in st.session_state or st.button("🔄 Refresh Model List"):
                st.session_state["available_gemini_models"] = get_available_gemini_models()
                if st.session_state["available_gemini_models"]:
                    st.success(f"✅ Found {len(st.session_state['available_gemini_models'])} Gemini models!")
            
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
                st.markdown(f"**Current Model Sequence:** {', '.join(st.session_state['app_config']['gemini_model_sequence'])}")
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
def check_and_set_admin(email, user_id):
    if email.lower() == "rajacharya3242@gmail.com":
        db.child("users").child(user_id).update({"role": "admin"})
        return True
    return False

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

def user_ui():
    st.title("⚖ Document Analyzer")

    with st.sidebar:
        st.subheader(f"👤 User: {st.session_state['user']['email']}")
        st.info("ℹ Using admin-configured settings")

        # Display current configuration (read-only)
        st.markdown("### Current Configuration")
        config = st.session_state["app_config"]
        st.markdown(f"- **Model Provider:** {config['model_provider']}")
        if config["model_provider"] == "Google Gemini":
            st.markdown(f"- **Gemini Model Sequence:** {', '.join(config['gemini_model_sequence'])}")
        else:
            st.markdown(f"- **DeepSeek Model:** {config['ollama_model']}")
        st.markdown(f"- **Input Folder:** {config['input_folder']}")
        st.markdown(f"- **Output Folder:** {config['output_folder']}")
        st.markdown(f"- **Completed Folder:** {config['completed_folder']}")

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
        st.subheader("📂 Folder Configuration")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.session_state["app_config"]["input_folder"] = st.text_input(
                "Input Folder Path",
                st.session_state["app_config"]["input_folder"]
            )
        with col2:
            st.session_state["app_config"]["output_folder"] = st.text_input(
                "Output Folder Path",
                st.session_state["app_config"]["output_folder"]
            )
        with col3:
            st.session_state["app_config"]["completed_folder"] = st.text_input(
                "Completed Files Folder",
                st.session_state["app_config"]["completed_folder"]
            )

        if st.button("Save Settings"):
            if st.session_state["user"] and st.session_state["user"]["email"]:
                conn = get_connection()
                if conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute(
                            "UPDATE user_api_keys SET input_folder_path = %s, output_folder_path = %s, completed_folder_path = %s WHERE email = %s",
                            (
                                st.session_state["app_config"]["input_folder"],
                                st.session_state["app_config"]["output_folder"],
                                st.session_state["app_config"]["completed_folder"],
                                st.session_state["user"]["email"],
                            ),
                        )
                        conn.commit()
                        st.success("💾 Folder settings saved!")
                    except Exception as e:
                        st.error(f"❌ Error saving folder settings: {e}")
                    finally:
                        cursor.close()
                        conn.close()
                else:
                    st.error("❌ Could not connect to the database to save settings.")
            else:
                st.error("⚠️ User information not found. Cannot save settings.")

        st.markdown("---")

        # File upload and folder processing options
        processing_mode = st.radio(
            "Select Processing Mode:",
            ["Upload Single File", "Process Folder"],
            index=0
        )
        uploaded_file = None
        if processing_mode == "Upload Single File":
            uploaded_file = st.file_uploader("📥 Upload an HTML or TXT file", type=["htm", "html", "txt"])  # Added "txt" type
        else:  # Process Folder
            input_folder = st.session_state["app_config"]["input_folder"]
            st.info(f"🔍 Using configured input folder: {input_folder}")
            if not input_folder or not os.path.exists(input_folder):
                st.error("❌ Invalid input folder path! Please contact admin.")
                return

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

        # Display questions horizontally in columns
        cols = st.columns(4)  # Adjust the number of columns as needed
        selected_questions = []

        for i, (q_id, question_text) in enumerate(questions):
            with cols[i % 4]:  # This will distribute questions across 4 columns
                if st.checkbox(f"{q_id}", key=question_text):
                    selected_questions.append(question_text)

        st.markdown("---")

        # Process based on mode
        if processing_mode == "Upload Single File":
            if st.button("🚀 Analyze Document"):
                if uploaded_file is None:
                    st.error("⚠️ Please upload an HTML or TXT file before analyzing.")  # Updated message
                else:
                    try:
                        file_name = uploaded_file.name
                        file_content = uploaded_file.getvalue().decode("utf-8")

                        # Create temp file in input folder
                        input_folder = st.session_state["app_config"]["input_folder"]
                        if not os.path.exists(input_folder):
                            os.makedirs(input_folder, exist_ok=True)

                        temp_path = os.path.join(input_folder, file_name)
                        with open(temp_path, "w", encoding="utf-8") as f:
                            f.write(file_content)

                        response = process_html(temp_path, file_name, selected_questions)  # Changed to process_html
                        if response:
                            st.success("✅ Analysis Complete!")
                            st.download_button(
                                label="📥 Download Response",
                                data=response,
                                file_name=f"{os.path.splitext(file_name)[0]}_response.txt",
                                mime="text/plain"
                            )
                        else:
                            st.error("❌ Document analysis failed. See error messages above.")
                    except Exception as e:
                        st.session_state["upload_error"] = True
                        st.error(f"❌ Error during file processing Try Again: {e}")
                        st.rerun()
        elif processing_mode == "Process Folder":
            if st.button("🚀 Process Folder"):  # Add a button for folder processing
                process_folder(input_folder, selected_questions)

def main():

    if not st.session_state["logged_in"]:
        auth_section()
    else:
        if st.session_state["user_role"] == "admin":
            admin_ui()
        else:
            user_ui()

if __name__ == "__main__":
    main()