from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import os
import pydicom
import requests
from urllib3.filepost import encode_multipart_formdata, choose_boundary
from azure.identity import ClientSecretCredential
from io import BytesIO
from pathlib import Path
import logging
from pydicom.uid import generate_uid
import requests_toolbelt as tb
import urllib3
import shutil
from dotenv import load_dotenv
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For flash messages

# Configure logging for the Flask app
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dicom_editor.log'),
        logging.StreamHandler()
    ]
)

# Session-based settings management
def get_current_settings():
    """Get current settings from session or environment variables"""
    if 'settings' not in session:
        session['settings'] = {
            'DICOM_ROOT': os.getenv("DICOM_ROOT", "./dicoms"),
            'AZURE_DICOM_ENDPOINT': os.getenv("AZURE_DICOM_ENDPOINT"),
            'AZURE_DICOM_CLIENT_ID': os.getenv("AZURE_DICOM_CLIENT_ID"),
            'AZURE_DICOM_SECRET': os.getenv("AZURE_DICOM_SECRET"),
            'AZURE_TENANT_ID': os.getenv("AZURE_TENANT_ID")
        }
    return session['settings']

def get_dicom_root():
    """Get current DICOM_ROOT from session settings"""
    settings = get_current_settings()
    return settings.get('DICOM_ROOT', "./dicoms")

def get_azure_settings():
    """Get current Azure settings from session"""
    settings = get_current_settings()
    return {
        'client_id': settings.get('AZURE_DICOM_CLIENT_ID'),
        'client_secret': settings.get('AZURE_DICOM_SECRET'),
        'tenant_id': settings.get('AZURE_TENANT_ID'),
        'endpoint': settings.get('AZURE_DICOM_ENDPOINT')
    }

def get_all_studies():
    dicom_root = get_dicom_root()
    return [d for d in os.listdir(dicom_root) if os.path.isdir(os.path.join(dicom_root, d))]

def get_dicom_files(study_path):
    dicoms = []
    for root, _, files in os.walk(study_path):
        for file in files:
            if file.endswith('.dcm'):
                dicoms.append(os.path.join(root, file))
    return dicoms

@app.route("/")
def index():
    study_paths = get_local_studies_with_metadata()
    return render_template("select.html", studies=study_paths)

@app.route("/edit-study/<study>")
def edit_study(study):
    dicom_root = get_dicom_root()
    study_path = os.path.join(dicom_root, study)
    dicom_files = get_dicom_files(study_path)

    sample = pydicom.dcmread(dicom_files[0], force=True) if dicom_files else None

    fields = {
        "StudyInstanceUID": getattr(sample, "StudyInstanceUID", ""),
        "PatientName": getattr(sample, "PatientName", ""),
        "PatientID": getattr(sample, "PatientID", ""),
        "PatientBirthDate": getattr(sample, "PatientBirthDate", ""),
        "AccessionNumber": getattr(sample, "AccessionNumber", ""),
        "StudyDescription": getattr(sample, "StudyDescription", ""),
        "ReferringPhysicianName": getattr(sample, "ReferringPhysicianName", ""),
        "StudyDate": getattr(sample, "StudyDate", ""),
        "StudyTime": getattr(sample, "StudyTime", ""),
    }

    return render_template("edit_study.html", study=study, fields=fields)

@app.route("/save-study/<study>", methods=["POST"])
def save_study(study):
    dicom_root = get_dicom_root()
    study_path = os.path.join(dicom_root, study)
    dicom_files = get_dicom_files(study_path)

    for file in dicom_files:
        ds = pydicom.dcmread(file, force=True)
        for key, value in request.form.items():
            if hasattr(ds, key):
                setattr(ds, key, value)
        ds.save_as(file)

    return redirect(url_for('edit_study', study=study))

@app.route("/edit-file/<path:file_path>")
def edit_file(file_path):
    dicom_root = get_dicom_root()
    abs_path = os.path.join(dicom_root, file_path)
    ds = pydicom.dcmread(abs_path, force=True)
    fields = [
        {
            "tag": str(elem.tag),
            "keyword": elem.keyword or "(unknown)",
            "VR": elem.VR,
            "VM": elem.VM,
            "length": len(str(elem.value)),
            "value": elem.value if isinstance(elem.value, (str, int, float)) else str(elem.value),
        }
        for elem in ds
        if elem.keyword
    ]
    return render_template("edit_file.html", fields=fields, file_path=file_path)


@app.route("/save-file/<path:file_path>", methods=["POST"])
def save_file(file_path):
    dicom_root = get_dicom_root()
    abs_path = os.path.join(dicom_root, file_path)
    ds = pydicom.dcmread(abs_path, force=True)
    for key in request.form:
        if hasattr(ds, key):
            setattr(ds, key, request.form[key])
    ds.save_as(abs_path)
    return redirect(url_for('edit_file', file_path=file_path))

def get_bearer_token():
    """Get Azure authentication token"""
    try:
        azure_settings = get_azure_settings()
        client_id = azure_settings['client_id']
        client_secret = azure_settings['client_secret']
        tenant_id = azure_settings['tenant_id']
        
        if not all([client_id, client_secret, tenant_id]):
            raise ValueError("Missing Azure credentials in session settings")
            
        credential = ClientSecretCredential(
            client_id=client_id,
            client_secret=client_secret,
            tenant_id=tenant_id
        )
        token = credential.get_token('https://dicom.healthcareapis.azure.com/.default')
        return f'Bearer {token.token}'
    except Exception as e:
        logging.error(f"Failed to get authentication token: {e}")
        raise

def encode_multipart_related(fields, boundary=None):
    """Encode multipart related content for DICOM STOW-RS"""
    if boundary is None:
        boundary = choose_boundary()
    body, _ = encode_multipart_formdata(fields, boundary)
    content_type = str('multipart/related; boundary=%s' % boundary)
    return body, content_type

def search_dicom_studies():
    """Search for studies in the DICOM service"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings['endpoint']
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured in session settings")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies'
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            studies = response.json()
            # Return tuple (success, studies_list)
            return True, studies if studies else []
        else:
            logging.error(f"Failed to search studies. Status code: {response.status_code}")
            return False, []
    except Exception as e:
        logging.error(f"Error searching DICOM studies: {e}")
        return False, []

def generate_random_study_instance_uid():
    """Generate a new Study Instance UID"""
    return generate_uid(prefix='1.2.528.1.1036.')

def upload_study_to_dicom(study_path):
    """Upload a local study to the DICOM service using STOW-RS"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings.get("endpoint")
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured")
            
        headers = {"Authorization": get_bearer_token()}
        study_instance_uid = generate_random_study_instance_uid()
        url = f'{base_url}/v2/studies/{study_instance_uid}'
        headers['Accept'] = 'application/dicom+json'
        
        parts = {}
        dicom_files = get_dicom_files(study_path)
        
        for file_path in dicom_files:
            dicom_file = pydicom.dcmread(file_path, force=True)
            dicom_file.StudyInstanceUID = study_instance_uid
            
            with BytesIO() as buffer:
                dicom_file.save_as(buffer)
                buffer.seek(0)
                file_name = os.path.basename(file_path)
                parts[file_name] = ('dicomfile', buffer.read(), 'application/dicom')
        
        body, content_type = encode_multipart_related(fields=parts)
        headers['Content-Type'] = content_type
        
        response = requests.post(url, data=body, headers=headers, verify=True)
        return response.status_code in [200, 202]
    except Exception as e:
        logging.error(f"Error uploading study to DICOM service: {e}")
        return False

@app.route("/fetch-dicom-studies")
def fetch_dicom_studies():
    """Fetch studies from DICOM service and display them"""
    try:
        success, studies = search_dicom_studies()
        dicom_studies = []
        
        if not success:
            flash("Error connecting to DICOM service or retrieving studies.", "error")
            return redirect(url_for('index'))
        
        for study in studies:
            study_data = {
                'study_instance_uid': study.get('0020000D', {}).get('Value', [''])[0],
                'patient_name': study.get('00100010', {}).get('Value', [''])[0],
                'patient_id': study.get('00100020', {}).get('Value', [''])[0],
                'patient_birth_date': study.get('00100030', {}).get('Value', [''])[0],
                'accession_number': study.get('00080050', {}).get('Value', [''])[0],
                'study_description': study.get('00081030', {}).get('Value', [''])[0],
                'referring_physician_name': study.get('00080090', {}).get('Value', [''])[0],
                'study_date': study.get('00080020', {}).get('Value', [''])[0],
                'study_time': study.get('00080030', {}).get('Value', [''])[0]
            }
            dicom_studies.append(study_data)
        
        # Add info message if search was successful but no studies found
        if success and len(studies) == 0:
            flash("Successfully connected to DICOM service, but no studies were found.", "info")
        
        return render_template("select.html", 
                             studies=get_local_studies_with_metadata(), 
                             dicom_studies=dicom_studies)
    except Exception as e:
        flash(f"Error fetching DICOM studies: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route("/upload-study/<study>")
def upload_study(study):
    """Upload a local study to the DICOM service"""
    try:
        current_settings = get_current_settings()
        study_path = os.path.join(current_settings['DICOM_ROOT'], study)
        if not os.path.exists(study_path):
            flash(f"Study '{study}' not found", "error")
            return redirect(url_for('index'))
        
        # Check if study is valid for upload
        dicom_files = get_dicom_files(study_path)
        if dicom_files:
            try:
                sample = pydicom.dcmread(dicom_files[0], force=True)
                metadata = {
                    'StudyInstanceUID': str(getattr(sample, "StudyInstanceUID", "")).strip(),
                    'PatientName': str(getattr(sample, "PatientName", "")).strip(),
                    'PatientID': str(getattr(sample, "PatientID", "")).strip(),
                    'AccessionNumber': str(getattr(sample, "AccessionNumber", "")).strip()
                }
                
                if not is_study_valid_for_upload(metadata):
                    flash(f"Study '{study}' cannot be uploaded: missing required fields (Study Instance UID, Patient Name, Patient ID, or Accession Number)", "error")
                    return redirect(url_for('index'))
            except Exception as e:
                flash(f"Error validating study '{study}': {str(e)}", "error")
                return redirect(url_for('index'))
        else:
            flash(f"Study '{study}' has no DICOM files", "error")
            return redirect(url_for('index'))
        
        success = upload_study_to_dicom(study_path)
        if success:
            flash(f"Study '{study}' successfully uploaded to DICOM service", "success")
        else:
            flash(f"Failed to upload study '{study}' to DICOM service", "error")
    except Exception as e:
        flash(f"Error uploading study: {str(e)}", "error")
    
    return redirect(url_for('index'))

def get_local_studies_with_files():
    """Get local studies with their files (existing functionality)"""
    current_settings = get_current_settings()
    dicom_root = current_settings['DICOM_ROOT']
    studies = get_all_studies()
    return {
        study: [
            os.path.relpath(path, dicom_root)
            for path in get_dicom_files(os.path.join(dicom_root, study))
        ]
        for study in studies
    }

def is_study_valid_for_upload(study_metadata):
    """Check if a study has the required metadata fields for upload to DICOM service"""
    required_fields = ['StudyInstanceUID', 'PatientName', 'PatientID', 'AccessionNumber']
    
    for field in required_fields:
        value = study_metadata.get(field, '').strip()
        if not value or value.lower() == 'n/a':
            return False
    
    return True

def get_local_studies_with_metadata():
    """Get local studies with their metadata for display"""
    studies = get_all_studies()
    studies_with_metadata = {}
    current_settings = get_current_settings()
    dicom_root = current_settings['DICOM_ROOT']
    
    for study in studies:
        study_path = os.path.join(dicom_root, study)
        dicom_files = get_dicom_files(study_path)
        files_list = [
            os.path.relpath(path, dicom_root)
            for path in dicom_files
        ]
        
        # Extract metadata from first DICOM file
        metadata = {
            'PatientName': '',
            'PatientID': '',
            'StudyDescription': '',
            'AccessionNumber': '',
            'ReferringPhysicianName': '',
            'StudyInstanceUID': ''
        }
        
        if dicom_files:
            try:
                sample = pydicom.dcmread(dicom_files[0], force=True)
                metadata['PatientName'] = str(getattr(sample, "PatientName", "")).strip()
                metadata['PatientID'] = str(getattr(sample, "PatientID", "")).strip()
                metadata['StudyDescription'] = str(getattr(sample, "StudyDescription", "")).strip()
                metadata['AccessionNumber'] = str(getattr(sample, "AccessionNumber", "")).strip()
                metadata['ReferringPhysicianName'] = str(getattr(sample, "ReferringPhysicianName", "")).strip()
                metadata['StudyInstanceUID'] = str(getattr(sample, "StudyInstanceUID", "")).strip()
            except Exception as e:
                logging.warning(f"Failed to read metadata for study {study}: {e}")
        
        studies_with_metadata[study] = {
            'files': files_list,
            'metadata': metadata,
            'is_valid_for_upload': is_study_valid_for_upload(metadata)
        }
    
    return studies_with_metadata

def retrieve_study_from_dicom(study_instance_uid):
    """Download a study from DICOM service to local storage"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings.get("endpoint")
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies/{study_instance_uid}'
        headers['Accept'] = 'multipart/related; type="application/dicom"; transfer-syntax=*'
        
        logging.debug(f"Retrieving study from URL: {url}")
        flash("[STARTED] Starting download DICOM study to local. Please be patient.", "info")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            # Use only Study Instance UID as folder name
            folder_name = str(study_instance_uid).replace('.', '_')
            folder_name = sanitize_filename(folder_name)
            
            # Create local study folder
            current_settings = get_current_settings()
            study_folder = os.path.join(current_settings['DICOM_ROOT'], folder_name)
            os.makedirs(study_folder, exist_ok=True)
            
            # Get metadata first
            metadata_url = f'{base_url}/v2/studies/{study_instance_uid}/metadata'
            metadata_headers = {'Accept': 'application/dicom+json', "Authorization": headers["Authorization"]}
            metadata_response = requests.get(metadata_url, headers=metadata_headers)
            
            if metadata_response.status_code == 200:
                metadata = metadata_response.json()
                logging.debug(f"Retrieved metadata for {len(metadata)} instances")
            else:
                logging.error(f"Failed to retrieve metadata. Status code: {metadata_response.status_code}")
                return False, "Failed to retrieve study metadata"
            
            # Parse multipart response to extract DICOM files
            mpd = tb.MultipartDecoder.from_response(response)
            series_folders = {}
            file_count = 0
            
            for part in mpd.parts:
                if b'application/dicom' in part.headers[b'Content-Type']:
                    dicom_file = pydicom.dcmread(BytesIO(part.content), force=True)
                    
                    # Create series folder if it doesn't exist
                    series_uid = getattr(dicom_file, 'SeriesInstanceUID', 'unknown_series')
                    series_number = getattr(dicom_file, 'SeriesNumber', '00000')
                    series_folder_name = f"series-{str(series_number).zfill(5)}"
                    
                    if series_folder_name not in series_folders:
                        series_folder_path = os.path.join(study_folder, series_folder_name)
                        os.makedirs(series_folder_path, exist_ok=True)
                        series_folders[series_folder_name] = series_folder_path
                    
                    # Save DICOM file
                    instance_number = getattr(dicom_file, 'InstanceNumber', file_count)
                    file_name = f"image-{str(instance_number).zfill(5)}.dcm"
                    file_path = os.path.join(series_folders[series_folder_name], file_name)
                    
                    dicom_file.save_as(file_path)
                    file_count += 1
                    
                    logging.debug(f"Saved DICOM file: {file_path}")
            
            return True, f"Study downloaded successfully with {file_count} files to {folder_name}"
            
        else:
            logging.error(f"Failed to retrieve study. Status code: {response.status_code}")
            return False, f"Failed to retrieve study from DICOM service (Status: {response.status_code})"
            
    except Exception as e:
        logging.error(f"Error retrieving study from DICOM service: {e}")
        return False, f"Error downloading study: {str(e)}"

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe folder creation"""
    invalid_chars = '<>:"/\\|?*'
    for ch in invalid_chars:
        filename = filename.replace(ch, '_')
    return filename

@app.route("/download-study/<study_instance_uid>")
def download_study(study_instance_uid):
    """Download a study from DICOM service to local storage"""
    try:
        success, message = retrieve_study_from_dicom(study_instance_uid)
        if success:
            flash(message, "success")
        else:
            flash(message, "error")
    except Exception as e:
        flash(f"Error downloading study: {str(e)}", "error")
    
    return redirect(url_for('fetch_dicom_studies'))

@app.route("/load-sample-data")
def load_sample_data():
    """Load sample data by copying from dicoms_sample to dicoms folder"""
    try:
        sample_folder = "dicoms_sample"
        current_settings = get_current_settings()
        target_folder = current_settings['DICOM_ROOT']
        
        if not os.path.exists(sample_folder):
            flash("Sample data folder not found", "error")
            return redirect(url_for('index'))
        
        # Check if sample folder has any content
        sample_studies = [d for d in os.listdir(sample_folder) 
                         if os.path.isdir(os.path.join(sample_folder, d)) and not d.startswith('.')]
        
        if not sample_studies:
            flash("No sample studies found in sample data folder", "error")
            return redirect(url_for('index'))
        
        # Ensure target directory exists
        os.makedirs(target_folder, exist_ok=True)
        
        copied_count = 0
        skipped_count = 0
        
        for study in sample_studies:
            source_path = os.path.join(sample_folder, study)
            target_path = os.path.join(target_folder, study)
            
            if os.path.exists(target_path):
                logging.info(f"Study '{study}' already exists, skipping")
                skipped_count += 1
                continue
            
            try:
                shutil.copytree(source_path, target_path)
                logging.info(f"Copied study '{study}' from sample data")
                copied_count += 1
            except Exception as e:
                logging.error(f"Failed to copy study '{study}': {e}")
                flash(f"Failed to copy study '{study}': {str(e)}", "error")
        
        # Provide feedback to user
        if copied_count > 0:
            flash(f"Successfully loaded {copied_count} sample stud{'y' if copied_count == 1 else 'ies'}", "success")
        
        if skipped_count > 0:
            flash(f"Skipped {skipped_count} stud{'y' if skipped_count == 1 else 'ies'} (already exist{'s' if skipped_count == 1 else ''})", "info")
        
        if copied_count == 0 and skipped_count == 0:
            flash("No studies were loaded", "warning")
            
    except Exception as e:
        flash(f"Error loading sample data: {str(e)}", "error")
        logging.error(f"Error loading sample data: {e}")
    
    return redirect(url_for('index'))

@app.route("/delete-study/<study>", methods=["POST"])
def delete_study(study):
    """Delete a local study folder and all its contents"""
    try:
        current_settings = get_current_settings()
        dicom_root = current_settings['DICOM_ROOT']
        study_path = os.path.join(dicom_root, study)
        
        # Security check: ensure the study path is within DICOM_ROOT
        if not os.path.abspath(study_path).startswith(os.path.abspath(dicom_root)):
            flash("Invalid study path", "error")
            return redirect(url_for('index'))
        
        if not os.path.exists(study_path):
            flash(f"Study '{study}' not found", "error")
            return redirect(url_for('index'))
        
        if not os.path.isdir(study_path):
            flash(f"'{study}' is not a valid study folder", "error")
            return redirect(url_for('index'))
        
        # Delete the entire study folder
        shutil.rmtree(study_path)
        logging.info(f"Deleted study folder: {study}")
        flash(f"Successfully deleted study '{study}'", "success")
        
    except Exception as e:
        logging.error(f"Error deleting study '{study}': {e}")
        flash(f"Error deleting study '{study}': {str(e)}", "error")
    
    return redirect(url_for('index'))

@app.route("/view-logs")
def view_logs():
    """Display the application log file"""
    log_content = []
    try:
        if os.path.exists('dicom_editor.log'):
            with open('dicom_editor.log', 'r', encoding='utf-8') as f:
                log_content = f.readlines()
                # Get last 500 lines to avoid huge pages
                log_content = log_content[-500:] if len(log_content) > 500 else log_content
                # Strip newlines for cleaner display
                log_content = [line.rstrip() for line in log_content]
        else:
            flash("Log file not found", "warning")
    except Exception as e:
        flash(f"Error reading log file: {str(e)}", "error")
        logging.error(f"Error reading log file: {e}")
    
    return render_template('logfile.html', log_content=log_content)

@app.route("/view-settings")
def view_settings():
    """Display and edit application settings"""
    settings = get_current_settings()
    return render_template('settings.html', settings=settings)

@app.route("/update-settings", methods=["POST"])
def update_settings():
    """Update application settings for current session"""
    try:
        # Get form data and update session settings
        session['settings'] = {
            'DICOM_ROOT': request.form.get('DICOM_ROOT', '').strip(),
            'AZURE_TENANT_ID': request.form.get('AZURE_TENANT_ID', '').strip(),
            'AZURE_DICOM_ENDPOINT': request.form.get('AZURE_DICOM_ENDPOINT', '').strip(),
            'AZURE_DICOM_CLIENT_ID': request.form.get('AZURE_DICOM_CLIENT_ID', '').strip(),
            'AZURE_DICOM_SECRET': request.form.get('AZURE_DICOM_SECRET', '').strip()
        }
        
        # Validate required fields
        settings = session['settings']
        if not settings['DICOM_ROOT']:
            flash("DICOM Root Directory cannot be empty", "error")
            return redirect(url_for('view_settings'))
        
        # Create DICOM root directory if it doesn't exist
        try:
            os.makedirs(settings['DICOM_ROOT'], exist_ok=True)
        except Exception as e:
            flash(f"Failed to create DICOM root directory: {str(e)}", "error")
            return redirect(url_for('view_settings'))
        
        flash("Settings updated successfully for current session", "success")
        logging.info("Settings updated via web interface")
        
    except Exception as e:
        flash(f"Error updating settings: {str(e)}", "error")
        logging.error(f"Error updating settings: {e}")
    
    return redirect(url_for('view_settings'))

@app.route("/reset-settings")
def reset_settings():
    """Reset settings to original .env values"""
    try:
        # Clear session settings to force reload from .env
        if 'settings' in session:
            del session['settings']
        flash("Settings reset to original .env file values", "success")
        logging.info("Settings reset to .env values")
    except Exception as e:
        flash(f"Error resetting settings: {str(e)}", "error")
        logging.error(f"Error resetting settings: {e}")
    
    return redirect(url_for('view_settings'))

if __name__ == "__main__":
    # Debug mode configuration
    debug_mode = os.getenv('FLASK_DEBUG', '1') == '1'
    port = int(os.getenv('FLASK_RUN_PORT', 5001))
    
    if debug_mode:
        app.logger.info(f"Starting Flask app in debug mode on port {port}")
        app.logger.info("Debug features enabled:")
        app.logger.info("- Auto-reload on file changes")
        app.logger.info("- Enhanced error pages")
        app.logger.info("- VSCode debugging support")
    
    app.run(debug=debug_mode, port=port, host='127.0.0.1')