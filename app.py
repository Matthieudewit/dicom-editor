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

# Configure Flask for handling larger files and requests
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max request size
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development

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
    
    # Define protected tags that should not be deleted
    protected_tags = {
        'SOPClassUID', 'SOPInstanceUID', 'StudyInstanceUID', 'SeriesInstanceUID',
        'PatientID', 'PatientName', 'Modality', 'TransferSyntaxUID',
        'MediaStorageSOPClassUID', 'MediaStorageSOPInstanceUID',
        'ImplementationClassUID', 'SpecificCharacterSet'
    }
    
    fields = []
    for elem in ds:
        if elem.keyword:
            try:
                # Handle different value types more carefully
                if isinstance(elem.value, (str, int, float)):
                    value_str = str(elem.value)
                elif hasattr(elem.value, '__iter__') and not isinstance(elem.value, (str, bytes)):
                    # Handle sequences and arrays
                    try:
                        value_str = str(elem.value)
                        if len(value_str) > 1000:  # Truncate very long values for display
                            value_str = value_str[:1000] + "... [TRUNCATED - Click to edit full value]"
                    except:
                        value_str = f"[Complex Value - Type: {type(elem.value).__name__}]"
                else:
                    value_str = str(elem.value)
                
                # Truncate extremely long values for better UI performance
                if len(value_str) > 1000:
                    display_value = value_str[:1000] + "... [TRUNCATED]"
                else:
                    display_value = value_str
                
                field_data = {
                    "tag": str(elem.tag),
                    "keyword": elem.keyword,
                    "VR": elem.VR,
                    "VM": elem.VM,
                    "length": len(str(elem.value)),
                    "value": display_value,
                    "original_value": value_str,  # Keep original for form submission
                    "is_deletable": elem.keyword not in protected_tags
                }
                fields.append(field_data)
                
            except Exception as e:
                logging.warning(f"Error processing DICOM tag {elem.keyword}: {e}")
                # Add a fallback entry for problematic tags
                fields.append({
                    "tag": str(elem.tag),
                    "keyword": elem.keyword or "(unknown)",
                    "VR": getattr(elem, 'VR', 'UN'),
                    "VM": getattr(elem, 'VM', '1'),
                    "length": 0,
                    "value": "[Error reading value]",
                    "original_value": "",
                    "is_deletable": (elem.keyword or "") not in protected_tags
                })
    
    # Calculate total tag count
    tag_count = len(fields)
    
    return render_template("edit_file.html", fields=fields, file_path=file_path, tag_count=tag_count)


@app.route("/save-file/<path:file_path>", methods=["POST"])
def save_file(file_path):
    """Save changes to DICOM file"""
    try:
        dicom_root = get_dicom_root()
        abs_path = os.path.join(dicom_root, file_path)
        
        if not os.path.exists(abs_path):
            flash(f"DICOM file not found: {file_path}", "error")
            return redirect(url_for('index'))
        
        ds = pydicom.dcmread(abs_path, force=True)
        changes_made = []
        
        # Process form data more efficiently
        for key in request.form:
            if hasattr(ds, key):
                try:
                    old_value = str(getattr(ds, key, ''))
                    new_value = request.form[key].strip()
                    
                    # Skip if no actual change
                    if old_value == new_value:
                        continue
                    
                    # Handle large values more carefully
                    if len(new_value) > 10000:  # If value is very large
                        logging.warning(f"Large value detected for tag {key}: {len(new_value)} characters")
                        # Truncate for logging but use full value for saving
                        log_value = new_value[:100] + "..." if len(new_value) > 100 else new_value
                        changes_made.append(f"{key}: Large value updated ({len(new_value)} chars)")
                    else:
                        changes_made.append(f"{key}: '{old_value}' → '{new_value}'")
                    
                    # Set the new value
                    setattr(ds, key, new_value)
                    
                except Exception as e:
                    logging.warning(f"Failed to update tag {key}: {e}")
                    continue
        
        if changes_made:
            # Save with better error handling
            try:
                ds.save_as(abs_path)
                flash(f"Successfully saved {len(changes_made)} change(s) to DICOM file", "success")
                logging.info(f"Saved changes to DICOM file '{file_path}': {len(changes_made)} changes made")
                
                # Log first few changes for debugging
                for change in changes_made[:3]:
                    logging.debug(f"Change: {change}")
                if len(changes_made) > 3:
                    logging.debug(f"... and {len(changes_made)-3} more changes")
                    
            except Exception as save_error:
                logging.error(f"Failed to save DICOM file '{file_path}': {save_error}")
                flash(f"Error saving DICOM file: {str(save_error)}", "error")
                return redirect(url_for('edit_file', file_path=file_path))
        else:
            flash("No changes detected in DICOM file", "info")
        
    except Exception as e:
        logging.error(f"Error processing DICOM file '{file_path}': {e}")
        flash(f"Error processing DICOM file: {str(e)}", "error")
    
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

def search_study_by_uid(study_instance_uid):
    """Search for a specific study by Study Instance UID in the DICOM service"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings['endpoint']
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured in session settings")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies/{study_instance_uid}'
        
        # First try to get study metadata to check if it exists
        metadata_url = f'{base_url}/v2/studies/{study_instance_uid}/metadata'
        headers_json = {
            "Authorization": headers["Authorization"],
            "Accept": "application/dicom+json"
        }
        
        response = requests.get(metadata_url, headers=headers_json)
        if response.status_code == 200:
            # Study exists, parse the metadata
            metadata = response.json()
            if metadata and len(metadata) > 0:
                # Extract study information from first instance metadata
                first_instance = metadata[0]
                study_data = {
                    'study_instance_uid': study_instance_uid,
                    'patient_name': first_instance.get('00100010', {}).get('Value', [''])[0],
                    'patient_id': first_instance.get('00100020', {}).get('Value', [''])[0],
                    'patient_birth_date': first_instance.get('00100030', {}).get('Value', [''])[0],
                    'accession_number': first_instance.get('00080050', {}).get('Value', [''])[0],
                    'study_description': first_instance.get('00081030', {}).get('Value', [''])[0],
                    'referring_physician_name': first_instance.get('00080090', {}).get('Value', [''])[0],
                    'study_date': first_instance.get('00080020', {}).get('Value', [''])[0],
                    'study_time': first_instance.get('00080030', {}).get('Value', [''])[0]
                }
                return True, [study_data]
            else:
                return False, []
        elif response.status_code == 404:
            logging.info(f"Study with UID '{study_instance_uid}' not found in DICOM service")
            return False, []
        else:
            logging.error(f"Failed to search for study. Status code: {response.status_code}")
            return False, []
    except Exception as e:
        logging.error(f"Error searching for study by UID: {e}")
        return False, []

def search_studies(search_params):
    """Search for studies in the DICOM service using various parameters"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings['endpoint']
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured in session settings")
            
        headers = {
            "Authorization": get_bearer_token(),
            "Accept": "application/dicom+json"
        }
        
        url = f'{base_url}/v2/studies'
        
        logging.info(f"Searching studies with params: {search_params}")
        response = requests.get(url, headers=headers, params=search_params)
        
        if response.status_code == 200:
            data = response.json()
            studies = []
            
            # Parse the response to extract study information
            for item in data:
                # Extract DICOM tags from the response
                study_data = {
                    'study_instance_uid': item.get('0020000D', {}).get('Value', [''])[0] if '0020000D' in item else '',
                    'patient_name': item.get('00100010', {}).get('Value', [{}])[0].get('Alphabetic', '') if '00100010' in item else '',
                    'patient_id': item.get('00100020', {}).get('Value', [''])[0] if '00100020' in item else '',
                    'patient_birth_date': item.get('00100030', {}).get('Value', [''])[0] if '00100030' in item else '',
                    'accession_number': item.get('00080050', {}).get('Value', [''])[0] if '00080050' in item else '',
                    'study_description': item.get('00081030', {}).get('Value', [''])[0] if '00081030' in item else '',
                    'referring_physician_name': item.get('00080090', {}).get('Value', [{}])[0].get('Alphabetic', '') if '00080090' in item else '',
                    'study_date': item.get('00080020', {}).get('Value', [''])[0] if '00080020' in item else '',
                    'study_time': item.get('00080030', {}).get('Value', [''])[0] if '00080030' in item else ''
                }
                studies.append(study_data)
            
            logging.info(f"Found {len(studies)} studies")
            return True, studies
        else:
            logging.error(f"Failed to search studies. Status code: {response.status_code}, Response: {response.text}")
            return False, []
    except Exception as e:
        logging.error(f"Error searching studies: {e}")
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

@app.route("/search-study-by-uid", methods=["POST"])
def search_study_by_uid_route():
    """Route to search for a specific study by Study Instance UID"""
    try:
        study_uid = request.form.get('study_uid', '').strip()
        
        if not study_uid:
            flash("Please enter a Study Instance UID", "error")
            return redirect(url_for('index'))
        
        # Validate UID format (basic validation)
        if not study_uid.replace('.', '').replace('0', '').replace('1', '').replace('2', '').replace('3', '').replace('4', '').replace('5', '').replace('6', '').replace('7', '').replace('8', '').replace('9', '') == '':
            flash("Invalid Study Instance UID format. UID should contain only numbers and dots.", "error")
            return redirect(url_for('index'))
        
        success, studies = search_study_by_uid(study_uid)
        
        if success and studies:
            flash(f"Found study with UID: {study_uid}", "success")
            return render_template("select.html", 
                                 studies=get_local_studies_with_metadata(), 
                                 dicom_studies=studies)
        elif success and not studies:
            flash(f"No study found with UID: {study_uid}", "info")
            return redirect(url_for('index'))
        else:
            flash(f"Error searching for study with UID: {study_uid}", "error")
            return redirect(url_for('index'))
    
    except Exception as e:
        flash(f"Error searching for study: {str(e)}", "error")
        logging.error(f"Error in search_study_by_uid_route: {e}")
        return redirect(url_for('index'))

@app.route("/advanced-search", methods=["POST"])
def advanced_search_route():
    """Route to search studies by various parameters"""
    try:
        search_type = request.form.get('search_type', '').strip()
        search_value = request.form.get('search_value', '').strip()
        
        if not search_type or not search_value:
            flash("Please select a search type and enter a search value", "error")
            return redirect(url_for('index'))
        
        # Build search parameters based on search type
        search_params = {}
        
        if search_type == 'PatientName':
            search_params['PatientName'] = search_value
            search_params['fuzzymatching'] = 'true'
            flash_field = "Patient Name"
        elif search_type == 'PatientBirthDate':
            # Validate date format (YYYYMMDD)
            if not (len(search_value) == 8 and search_value.isdigit()):
                flash("Patient Birth Date must be in YYYYMMDD format (e.g., 19800115)", "error")
                return redirect(url_for('index'))
            search_params['PatientBirthDate'] = search_value
            flash_field = "Patient Birth Date"
        elif search_type == 'PatientID':
            search_params['PatientID'] = search_value
            flash_field = "Patient ID"
        elif search_type == 'AccessionNumber':
            search_params['AccessionNumber'] = search_value
            flash_field = "Accession Number"
        else:
            flash("Invalid search type", "error")
            return redirect(url_for('index'))
        
        success, studies = search_studies(search_params)
        
        if success and studies:
            flash(f"Found {len(studies)} study/studies matching {flash_field}: {search_value}", "success")
            return render_template("select.html", 
                                 studies=get_local_studies_with_metadata(), 
                                 dicom_studies=studies)
        elif success and not studies:
            flash(f"No studies found matching {flash_field}: {search_value}", "info")
            return redirect(url_for('index'))
        else:
            flash(f"Error searching for studies with {flash_field}: {search_value}", "error")
            return redirect(url_for('index'))
    
    except Exception as e:
        flash(f"Error performing advanced search: {str(e)}", "error")
        logging.error(f"Error in advanced_search_route: {e}")
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
        
        # Calculate series and image counts
        series_count = 0
        image_count = len(dicom_files)
        
        # Count unique series by examining the folder structure
        # Series are typically organized in separate folders
        series_folders = set()
        for file_path in dicom_files:
            # Get the parent directory name (series folder)
            relative_path = os.path.relpath(file_path, study_path)
            series_folder = os.path.dirname(relative_path)
            if series_folder:  # Only count if there's actually a series folder
                series_folders.add(series_folder)
        
        series_count = len(series_folders) if series_folders else 1  # At least 1 series if files exist
        
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
            'is_valid_for_upload': is_study_valid_for_upload(metadata),
            'series_count': series_count,
            'image_count': image_count
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

@app.route("/delete-tag/<path:file_path>", methods=["POST"])
def delete_tag(file_path):
    """Delete a specific DICOM tag from a file"""
    try:
        dicom_root = get_dicom_root()
        abs_path = os.path.join(dicom_root, file_path)
        
        if not os.path.exists(abs_path):
            flash(f"DICOM file not found: {file_path}", "error")
            return redirect(url_for('index'))
        
        tag_keyword = request.form.get('tag_keyword')
        if not tag_keyword:
            flash("No tag specified for deletion", "error")
            return redirect(url_for('edit_file', file_path=file_path))
        
        # Define protected tags that should not be deleted
        protected_tags = {
            'SOPClassUID', 'SOPInstanceUID', 'StudyInstanceUID', 'SeriesInstanceUID',
            'PatientID', 'PatientName', 'Modality', 'TransferSyntaxUID',
            'MediaStorageSOPClassUID', 'MediaStorageSOPInstanceUID',
            'ImplementationClassUID', 'SpecificCharacterSet'
        }
        
        if tag_keyword in protected_tags:
            flash(f"Tag '{tag_keyword}' is protected and cannot be deleted", "error")
            return redirect(url_for('edit_file', file_path=file_path))
        
        # Load and modify the DICOM file
        ds = pydicom.dcmread(abs_path, force=True)
        
        if not hasattr(ds, tag_keyword):
            flash(f"Tag '{tag_keyword}' not found in DICOM file", "warning")
            return redirect(url_for('edit_file', file_path=file_path))
        
        # Delete the tag
        delattr(ds, tag_keyword)
        
        # Save the modified file
        ds.save_as(abs_path)
        
        flash(f"Successfully deleted DICOM tag '{tag_keyword}'", "success")
        logging.info(f"Deleted DICOM tag '{tag_keyword}' from file: {file_path}")
        
    except Exception as e:
        flash(f"Error deleting DICOM tag: {str(e)}", "error")
        logging.error(f"Error deleting DICOM tag '{tag_keyword}' from file '{file_path}': {e}")
    
    return redirect(url_for('edit_file', file_path=file_path))

def search_study_by_uid(study_instance_uid):
    """Search for a specific study by Study Instance UID in the DICOM service"""
    try:
        azure_settings = get_azure_settings()
        base_url = azure_settings['endpoint']
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured in session settings")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies/{study_instance_uid}'
        
        # First try to get study metadata to check if it exists
        metadata_url = f'{base_url}/v2/studies/{study_instance_uid}/metadata'
        headers_json = {
            "Authorization": headers["Authorization"],
            "Accept": "application/dicom+json"
        }
        
        response = requests.get(metadata_url, headers=headers_json)
        if response.status_code == 200:
            # Study exists, parse the metadata
            metadata = response.json()
            if metadata and len(metadata) > 0:
                # Extract study information from first instance metadata
                first_instance = metadata[0]
                study_data = {
                    'study_instance_uid': study_instance_uid,
                    'patient_name': first_instance.get('00100010', {}).get('Value', [''])[0],
                    'patient_id': first_instance.get('00100020', {}).get('Value', [''])[0],
                    'patient_birth_date': first_instance.get('00100030', {}).get('Value', [''])[0],
                    'accession_number': first_instance.get('00080050', {}).get('Value', [''])[0],
                    'study_description': first_instance.get('00081030', {}).get('Value', [''])[0],
                    'referring_physician_name': first_instance.get('00080090', {}).get('Value', [''])[0],
                    'study_date': first_instance.get('00080020', {}).get('Value', [''])[0],
                    'study_time': first_instance.get('00080030', {}).get('Value', [''])[0]
                }
                return True, [study_data]
            else:
                return False, []
        elif response.status_code == 404:
            logging.info(f"Study with UID '{study_instance_uid}' not found in DICOM service")
            return False, []
        else:
            logging.error(f"Failed to search for study. Status code: {response.status_code}")
            return False, []
    except Exception as e:
        logging.error(f"Error searching for study by UID: {e}")
        return False, []

if __name__ == "__main__":
    # Debug mode configuration
    debug_mode = os.getenv('FLASK_DEBUG', '1') == '1'
    port = int(os.getenv('FLASK_RUN_PORT', 5001))
    host = os.getenv('FLASK_RUN_HOST', '127.0.0.1')
    
    if debug_mode:
        app.logger.info(f"Starting Flask app in debug mode on {host}:{port}")
        app.logger.info("Debug features enabled:")
        app.logger.info("- Auto-reload on file changes")
        app.logger.info("- Enhanced error pages")
        app.logger.info("- VSCode debugging support")
    else:
        app.logger.info(f"Starting Flask app on {host}:{port}")
    
    app.run(debug=debug_mode, port=port, host=host)