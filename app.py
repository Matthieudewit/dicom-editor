from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
import pydicom
from config import DICOM_ROOT
import requests
from urllib3.filepost import encode_multipart_formdata, choose_boundary
from azure.identity import ClientSecretCredential
from io import BytesIO
from pathlib import Path
import logging
from pydicom.uid import generate_uid
import requests_toolbelt as tb
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

def get_all_studies():
    return [d for d in os.listdir(DICOM_ROOT) if os.path.isdir(os.path.join(DICOM_ROOT, d))]

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
    study_path = os.path.join(DICOM_ROOT, study)
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
    study_path = os.path.join(DICOM_ROOT, study)
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
    abs_path = os.path.join(DICOM_ROOT, file_path)
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
    abs_path = os.path.join(DICOM_ROOT, file_path)
    ds = pydicom.dcmread(abs_path, force=True)
    for key in request.form:
        if hasattr(ds, key):
            setattr(ds, key, request.form[key])
    ds.save_as(abs_path)
    return redirect(url_for('edit_file', file_path=file_path))

def get_bearer_token():
    """Get Azure authentication token"""
    try:
        client_id = os.getenv("AZURE_DICOM_CLIENT_ID")
        client_secret = os.getenv("AZURE_DICOM_SECRET")
        tenant_id = os.getenv("AZURE_TENANT_ID")
        
        if not all([client_id, client_secret, tenant_id]):
            raise ValueError("Missing Azure credentials in environment variables")
            
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
        base_url = os.getenv("AZURE_DICOM_ENDPOINT")
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies'
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Failed to search studies. Status code: {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"Error searching DICOM studies: {e}")
        return []

def generate_random_study_instance_uid():
    """Generate a new Study Instance UID"""
    return generate_uid(prefix='1.2.528.1.1036.')

def upload_study_to_dicom(study_path):
    """Upload a local study to the DICOM service using STOW-RS"""
    try:
        base_url = os.getenv("AZURE_DICOM_ENDPOINT")
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
        studies = search_dicom_studies()
        dicom_studies = []
        
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
        
        return render_template("select.html", 
                             studies=get_local_studies_with_files(), 
                             dicom_studies=dicom_studies)
    except Exception as e:
        flash(f"Error fetching DICOM studies: {str(e)}", "error")
        return redirect(url_for('index'))

@app.route("/upload-study/<study>")
def upload_study(study):
    """Upload a local study to the DICOM service"""
    try:
        study_path = os.path.join(DICOM_ROOT, study)
        if not os.path.exists(study_path):
            flash(f"Study '{study}' not found", "error")
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
    studies = get_all_studies()
    return {
        study: [
            os.path.relpath(path, DICOM_ROOT)
            for path in get_dicom_files(os.path.join(DICOM_ROOT, study))
        ]
        for study in studies
    }

def get_local_studies_with_metadata():
    """Get local studies with their metadata for display"""
    studies = get_all_studies()
    studies_with_metadata = {}
    
    for study in studies:
        study_path = os.path.join(DICOM_ROOT, study)
        dicom_files = get_dicom_files(study_path)
        files_list = [
            os.path.relpath(path, DICOM_ROOT)
            for path in dicom_files
        ]
        
        # Extract metadata from first DICOM file
        metadata = {
            'PatientName': '',
            'PatientID': '',
            'StudyDescription': '',
            'AccessionNumber': '',
            'ReferringPhysicianName': ''
        }
        
        if dicom_files:
            try:
                sample = pydicom.dcmread(dicom_files[0], force=True)
                metadata['PatientName'] = str(getattr(sample, "PatientName", "")).strip()
                metadata['PatientID'] = str(getattr(sample, "PatientID", "")).strip()
                metadata['StudyDescription'] = str(getattr(sample, "StudyDescription", "")).strip()
                metadata['AccessionNumber'] = str(getattr(sample, "AccessionNumber", "")).strip()
                metadata['ReferringPhysicianName'] = str(getattr(sample, "ReferringPhysicianName", "")).strip()
            except Exception as e:
                logging.warning(f"Failed to read metadata for study {study}: {e}")
        
        studies_with_metadata[study] = {
            'files': files_list,
            'metadata': metadata
        }
    
    return studies_with_metadata

def retrieve_study_from_dicom(study_instance_uid):
    """Download a study from DICOM service to local storage"""
    try:
        base_url = os.getenv("AZURE_DICOM_ENDPOINT")
        if not base_url:
            raise ValueError("AZURE_DICOM_ENDPOINT not configured")
            
        headers = {"Authorization": get_bearer_token()}
        url = f'{base_url}/v2/studies/{study_instance_uid}'
        headers['Accept'] = 'multipart/related; type="application/dicom"; transfer-syntax=*'
        
        logging.debug(f"Retrieving study from URL: {url}")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            # Use only Study Instance UID as folder name
            folder_name = str(study_instance_uid).replace('.', '_')
            folder_name = sanitize_filename(folder_name)
            
            # Create local study folder
            study_folder = os.path.join(DICOM_ROOT, folder_name)
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

if __name__ == "__main__":
    app.run(debug=True)