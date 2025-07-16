import requests
import pydicom
from pydicom.uid import generate_uid
from urllib3.filepost import encode_multipart_formdata, choose_boundary
from azure.identity import DefaultAzureCredential, CredentialUnavailableError, ClientSecretCredential
import json
import logging
from io import BytesIO
import requests_toolbelt as tb
import random
import string
import shutil
import uuid
import secrets
from pathlib import Path
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log_file_path = Path(__file__).parent / 'dicom_editor.log'

def clear_log_file():
    open(log_file_path, 'w').close()

def check_log_file_size():
    max_size = 10 * 1024 * 1024
    if log_file_path.stat().st_size > max_size:
        clear_log_file()

dicom_changes_log_file_path = Path(__file__).parent / 'dicom_changes.log'

def initialize_logs():
    open(log_file_path, 'w').close()
    open(dicom_changes_log_file_path, 'w').close()
    check_log_file_size()

initialize_logs()
check_log_file_size()

logging.basicConfig(level=logging.DEBUG, filename=log_file_path, filemode='a',
                    format='%(asctime)s - %(levelname)s - %(message)s')

dicom_changes_logger = logging.getLogger('dicom_changes_logger')
dicom_changes_logger.setLevel(logging.INFO)
dicom_changes_handler = logging.FileHandler(dicom_changes_log_file_path, mode='a')
dicom_changes_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
dicom_changes_logger.addHandler(dicom_changes_handler)

def get_bearer_token(client_id, client_secret, tenant_id):
    print("Logging in...")
    credential = ClientSecretCredential(
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id
    )
    try:
        token = credential.get_token('https://dicom.healthcareapis.azure.com/.default')
        print("Login successful.")
        return f'Bearer {token.token}'
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        print("Login failed.")
        raise Exception("Failed to retrieve token using client ID and secret")

def encode_multipart_related(fields, boundary=None):
    if boundary is None:
        boundary = choose_boundary()
    body, _ = encode_multipart_formdata(fields, boundary)
    content_type = str('multipart/related; boundary=%s' % boundary)
    return body, content_type

def search_studies(client, headers, base_url, search_params):
    url = f'{base_url}/v2/studies'
    response = client.get(url, headers=headers, params=search_params)
    if response.status_code == 200:
        return response.json()
    else:
        logging.error(f"Failed to search studies. Status code: {response.status_code}, Response: {response.text}")
        return None

def print_studies(studies):
    if not studies:
        print("No studies found.")
        return
    print("\033[96mSearch Results:\033[0m")
    print("-" * 87)
    for index, study in enumerate(studies, start=1):
        print(f"{index}. Study Instance UID: {study.get('0020000D', {}).get('Value', [''])[0]}")
        print(f"   Patient Name: {study.get('00100010', {}).get('Value', [''])[0]}")
        print(f"   Patient ID: {study.get('00100020', {}).get('Value', [''])[0]}")
        print(f"   Patient Birth Date: {study.get('00100030', {}).get('Value', [''])[0]}")
        print(f"   Accession Number: {study.get('00080050', {}).get('Value', [''])[0]}")
        print(f"   Study Description: {study.get('00081030', {}).get('Value', [''])[0]}")
        print(f"   Referring Physician Name: {study.get('00080090', {}).get('Value', [''])[0]}")
        print(f"   Study Date: {study.get('00080020', {}).get('Value', [''])[0]}")
        print(f"   Study Time: {study.get('00080030', {}).get('Value', [''])[0]}")
        print("-" * 90)

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\n\n")

    def generate_random_study_instance_uid():
        return generate_uid(prefix='1.2.528.1.1036.')

def stow_rs(client, headers, base_url, folder_path):
    study_instance_uid = generate_random_study_instance_uid()
    url = f'{base_url}/v2/studies/{study_instance_uid}'
    headers['Accept'] = 'application/dicom+json'
    parts = {}
    temp_folder = Path(__file__).parent / "temp" / folder_path.name
    for dicom_file_path in temp_folder.glob("*.dcm"):
        dicom_file = pydicom.dcmread(dicom_file_path, force=True)
        dicom_file.StudyInstanceUID = study_instance_uid
        with BytesIO() as buffer:
            dicom_file.save_as(buffer)
            buffer.seek(0)
            parts[dicom_file_path.name] = ('dicomfile', buffer.read(), 'application/dicom')
    body, content_type = encode_multipart_related(fields=parts)
    headers['Content-Type'] = content_type
    response = client.post(url, data=body, headers=headers, verify=True)
    return response

def sanitize_filename(filename: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for ch in invalid_chars:
        filename = filename.replace(ch, '_')
    return filename

def retrieve_study(client, headers, base_url, study_instance_uid, patient_name):
    url = f'{base_url}/v2/studies/{study_instance_uid}'
    headers['Accept'] = 'multipart/related; type="application/dicom"; transfer-syntax=*'
    logging.debug(f"Retrieving study from URL: {url}")
    logging.debug(f"Request headers: {headers}")
    try:
        response = client.get(url, headers=headers)
        logging.debug(f"Response status code: {response.status_code}")
        logging.debug(f"Response headers: {response.headers}")
        if response.status_code == 200:
            patient_name_str = patient_name.get('Alphabetic', 'Unknown_Patient')
            study_instance_uid_str = str(study_instance_uid)
            raw_folder_name = f"{patient_name_str.replace(' ', '_')}_{study_instance_uid_str.replace('.', '_')}"
            folder_name = sanitize_filename(raw_folder_name)
            temp_folder = Path(__file__).parent / "temp" / folder_name
            temp_folder.mkdir(parents=True, exist_ok=True)
            metadata_url = f'{base_url}/v2/studies/{study_instance_uid}/metadata'
            metadata_headers = {'Accept': 'application/dicom+json', "Authorization": headers["Authorization"]}
            metadata_response = client.get(metadata_url, headers=metadata_headers)
            if metadata_response.status_code == 200:
                metadata = metadata_response.json()
                logging.debug(f"Metadata: {metadata}")
            else:
                logging.error(f"Failed to retrieve metadata. Status code: {metadata_response.status_code}, Response: {metadata_response.text}")
                print("Failed to retrieve metadata.")
                return
            mpd = tb.MultipartDecoder.from_response(response)
            for part in mpd.parts:
                logging.debug(f"Part headers: {part.headers}")
                if b'application/dicom' in part.headers[b'Content-Type']:
                    dicom_file = pydicom.dcmread(BytesIO(part.content), force=True)
                    logging.debug(f"Patient Name: {dicom_file.PatientName}")
                    logging.debug(f"SOP Instance UID: {dicom_file.SOPInstanceUID}")
                    file_path = temp_folder / f"{dicom_file.SOPInstanceUID}.dcm"
                    dicom_file.save_as(file_path)
            print(f"Study saved to {temp_folder}")
            while True:
                print("\n\033[96mDICOM Tag Editor Menu:\033[0m")
                print("-" * 22)
                first_file = True
                for dicom_file_path in temp_folder.glob("*.dcm"):
                    dicom_file = pydicom.dcmread(dicom_file_path, force=True)
                    if first_file:
                        print("1. Patient Name:", f"\033[93m{dicom_file.PatientName}\033[0m")
                        print("2. Patient ID:", f"\033[93m{dicom_file.PatientID}\033[0m")
                        print("3. Patient Birth Date:", f"\033[93m{dicom_file.PatientBirthDate}\033[0m")
                        print("4. Accession Number:", f"\033[93m{dicom_file.AccessionNumber}\033[0m")
                        print("5. Study Description:", f"\033[93m{dicom_file.StudyDescription}\033[0m")
                        print("6. Referring Physician Name:", f"\033[93m{dicom_file.ReferringPhysicianName}\033[0m")
                        print("7. Study Instance UID:", f"\033[93m{dicom_file.StudyInstanceUID}\033[0m")
                        print("8. Study Date:", f"\033[93m{dicom_file.StudyDate}\033[0m")
                        print("9. Study Time:", f"\033[93m{dicom_file.StudyTime}\033[0m")
                        print("10. Send modified data back to DICOM server (STOW-RS)")
                        print("11. Delete study from DICOM server")
                        print()
                        first_file = False
                tag_options = {
                    "1": "PatientName",
                    "2": "PatientID",
                    "3": "PatientBirthDate",
                    "4": "AccessionNumber",
                    "5": "StudyDescription",
                    "6": "ReferringPhysicianName",
                    "7": "StudyInstanceUID",
                    "8": "StudyDate",
                    "9": "StudyTime",
                    "10": "Send modified data back to DICOM server (STOW-RS)",
                    "11": "Delete study from DICOM server"
                }
                tag_choice = input("Enter the number of the DICOM tag to edit (or 'q' to quit): ")
                clear_screen()
                if tag_choice.lower() == 'q':
                    break
                if tag_choice == '10':
                    old_study_instance_uid = study_instance_uid
                    new_study_instance_uid = generate_random_study_instance_uid()
                    for dicom_file_path in temp_folder.glob("*.dcm"):
                        dicom_file = pydicom.dcmread(dicom_file_path, force=True)
                        dicom_file.StudyInstanceUID = new_study_instance_uid
                        dicom_file.save_as(dicom_file_path)
                    print(f"Study Instance UID updated to \033[93m{new_study_instance_uid}\033[0m in all DICOM files.")
                    dicom_changes_logger.info(f"Generated new StudyInstanceUID: {new_study_instance_uid} (Old StudyInstanceUID: {old_study_instance_uid})")
                    response = stow_rs(client, headers, base_url, temp_folder)
                    if response.status_code == 200 or response.status_code == 202:
                        print("Data successfully sent back to the DICOM server.")
                        success = delete_study(client, headers, base_url, old_study_instance_uid)
                        if success:
                            print(f"Old study with StudyInstanceUID \033[93m{old_study_instance_uid}\033[0m successfully deleted.")
                        else:
                            print(f"\033[91mFailed to delete the old study with StudyInstanceUID \033[93m{old_study_instance_uid}\033[0m.\033[0m")
                    else:
                        print("\033[91mCritical Warning: Failed to upload modified data to the DICOM server.\033[0m")
                        print("\033[91mPlease contact support immediately at +31 885500500.\033[0m")
                        logging.critical(f"Failed to upload modified data. Status code: {response.status_code}, Response: {response.text}")
                elif tag_choice == '11':
                    confirm_delete = input(f"Are you sure you want to delete the study with StudyInstanceUID \033[93m{study_instance_uid}\033[0m? (y/n): ")
                    clear_screen()
                    if confirm_delete.lower() == 'y':
                        success = delete_study(client, headers, base_url, study_instance_uid)
                        if success:
                            return
                        else:
                            print("Returning to DICOM Tag Editor Menu due to failure.")
                    else:
                        print("Deletion cancelled.")
                else:
                    tag_to_edit = tag_options.get(tag_choice)
                    if tag_to_edit:
                        old_value = getattr(dicom_file, tag_to_edit)
                        new_value = input(f"Enter the new value for {tag_to_edit} (current value: \033[93m{old_value}\033[0m): ")
                        clear_screen()
                        confirm = input(f"Change {tag_to_edit} from \033[93m{old_value}\033[0m to \033[93m{new_value}\033[0m? (y/n): ")
                        clear_screen()
                        if confirm.lower() == 'y':
                            for dicom_file_path in temp_folder.glob("*.dcm"):
                                dicom_file = pydicom.dcmread(dicom_file_path, force=True)
                                setattr(dicom_file, tag_to_edit, new_value)
                                dicom_file.save_as(dicom_file_path)
                                dicom_changes_logger.info(f"File: {dicom_file_path.name}, Tag: {tag_to_edit}, Old Value: {old_value}, New Value: {new_value}")
                            print(f"{tag_to_edit} updated to \033[93m{new_value}\033[0m in all DICOM files.")
                        else:
                            print("No changes made.")
                    else:
                        print("Invalid choice. No changes made.")
                dicom_file = pydicom.dcmread(dicom_file_path, force=True)
        else:
            logging.error(f"Failed to retrieve study. Status code: {response.status_code}, Response: {response.text}")
            print("Failed to retrieve study.")
    except Exception as e:
        logging.error(f"An error occurred while retrieving the study: {e}")
        print("An error occurred while retrieving the study. Please check the log file for details.")

def delete_study(client, headers, base_url, study_instance_uid):
    print(f"StudyInstanceUID to delete: \033[93m{study_instance_uid}\033[0m")
    confirmation = input("Please type 'I confirm' to confirm deletion: ")
    if confirmation.strip() != "I confirm":
        print("Confirmation text does not match. Deletion aborted.")
        return False
    url = f'{base_url}/v2/studies/{study_instance_uid}'
    response = client.delete(url, headers=headers)
    if response.status_code == 204:
        clear_screen()
        print("Study successfully deleted from the DICOM server.\n")
        dicom_changes_logger.info(f"Study with StudyInstanceUID {study_instance_uid} was deleted from the DICOM server.")
        return True
    else:
        logging.error(f"Failed to delete study. Status code: {response.status_code}, Response: {response.text}")
        print("Failed to delete study from the DICOM server.")
        return False

def cleanup_folders():
    temp_folder = Path(__file__).parent / "temp"
    if temp_folder.exists():
        try:
            shutil.rmtree(temp_folder)
            print(f"Deleted temp folder: {temp_folder}")
        except Exception as e:
            logging.error(f"Failed to delete temp folder {temp_folder}: {e}")

def generate_random_config():
    config_path = Path(__file__).parent / 'config.json'
    if not config_path.exists():
        print("Configuration file 'config.json' not found. Let's create one.")
        example_dicom_service_url = "https://example.dicom.azurehealthcareapis.com"
        example_client_id = str(uuid.uuid4())
        example_client_secret = secrets.token_urlsafe(32)
        example_tenant_id = str(uuid.uuid4())
        dicom_service_url = input(f"Enter the DICOM Service URL (example: {example_dicom_service_url}): ").strip()
        client_id = input(f"Enter the Client ID (example: {example_client_id}): ").strip()
        client_secret = input(f"Enter the Client Secret (example: {example_client_secret}): ").strip()
        tenant_id = input(f"Enter the Tenant ID (example: {example_tenant_id}): ").strip()
        config_data = {
            "dicom_service_url": dicom_service_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id
        }
        with open(config_path, 'w') as config_file:
            json.dump(config_data, config_file, indent=4)
        print(f"Configuration file created at: {config_path}")

def display_changes_summary():
    if dicom_changes_log_file_path.exists():
        with open(dicom_changes_log_file_path, 'r') as changes_log:
            changes = changes_log.readlines()
            if changes:
                def print_summary_and_instructions():
                    print("\n\033[96mSummary of Changes:\033[0m")
                    print("-" * 22)
                    for change in changes:
                        print(change.strip())
                    instructions = (
                        "\n\033[93mIMPORTANT:\033[0m Please visit \033[94mhttps://service.skymedicalgroup.com\033[0m\n"
                        "and open a new support ticket. Copy-paste the above changes into the ticket.\n"
                        "A Sky Medical Group support representative will assist in finalizing the changes.\n"
                    )
                    print(instructions)
                print_summary_and_instructions()
                while True:
                    support_ticket = input("Have you already created a support ticket? (y/n): ").lower().strip()
                    if support_ticket == 'y':
                        break
                    elif support_ticket == 'n':
                        clear_screen()
                        print_summary_and_instructions()
                    else:
                        print("Please answer with 'y' or 'n'.\n")

if __name__ == "__main__":
    try:
        generate_random_config()
        config_path = Path(__file__).parent / 'config.json'
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
        client_id = config.get("client_id")
        client_secret = config.get("client_secret")
        tenant_id = config.get("tenant_id")
        bearer_token = get_bearer_token(client_id, client_secret, tenant_id)
        client = requests.session()
        headers = {"Authorization": bearer_token}
        base_url = config.get("dicom_service_url", "https://default-dicom-service-url")
        url = f'{base_url}/v1/changefeed'
        print("Fetching changefeed...")
        response = client.get(url, headers=headers)
        if response.status_code == 403:
            logging.error('Error! Forbidden access. Check if the token has the necessary permissions.')
            logging.error(f"Token: {bearer_token}")
            print("Access forbidden. Please check your permissions.")
        elif response.status_code != 200:
            logging.error(f'Error! Likely not authenticated! Status code: {response.status_code}, Response: {response.text}')
            print("Authentication failed. Please check your credentials.")
        else:
            logging.info('Authentication successful!')
            print("Changefeed fetched successfully.")
            clear_screen()
            print("-" * 55)
            print("\033[96mWelcome to Sky Dicom Editor\033[0m")
            print("\033[96mWARNING: For expert users only! Use with great caution!\033[0m")
            print("\033[96m© 2025 Sky Medical Group B.V.\033[0m")
            print("-" * 55)
        while True:
            print("\n\033[96mLookup Menu:\033[0m")
            print("-" * 12)
            print("1. Lookup study by PatientName")
            print("2. Lookup study by PatientBirthDate")
            print("3. Lookup study by PatientID")
            print("4. Lookup study by AccessionNumber")
            print()
            while True:
                choice = input("Enter your choice (or 'q' to quit): ").strip()
                if choice in ['1', '2', '3', '4', 'q']:
                    break
                print("\033[91mInvalid choice. Please try again.\033[0m")
            clear_screen()
            if choice == '1':
                patient_name = input("Enter PatientName: ")
                clear_screen()
                studies = search_studies(client, headers, base_url, {"PatientName": patient_name, "fuzzymatching": 'true'})
                clear_screen()
                print_studies(studies)
            elif choice == '2':
                patient_birth_date = input("Enter PatientBirthDate (YYYYMMDD): ")
                clear_screen()
                studies = search_studies(client, headers, base_url, {"PatientBirthDate": patient_birth_date})
                clear_screen()
                print_studies(studies)
            elif choice == '3':
                patient_id = input("Enter PatientID: ")
                clear_screen()
                studies = search_studies(client, headers, base_url, {"PatientID": patient_id})
                clear_screen()
                print_studies(studies)
            elif choice == '4':
                accession_number = input("Enter AccessionNumber: ")
                clear_screen()
                studies = search_studies(client, headers, base_url, {"AccessionNumber": accession_number})
                clear_screen()
                print_studies(studies)
            elif choice.lower() == 'q':
                print("Exiting...")
                cleanup_folders()
                break
            if studies:
                while True:
                    print()
                    study_choice = input("Select which study to edit (or 'q' to quit): ").strip()
                    if study_choice.lower() == 'q':
                        break
                    if study_choice.isdigit() and 1 <= int(study_choice) <= len(studies):
                        study_choice = int(study_choice)
                        selected_study = studies[study_choice - 1]
                        study_instance_uid = selected_study.get('0020000D', {}).get('Value', [''])[0]
                        patient_name = selected_study.get('00100010', {}).get('Value', [''])[0]
                        retrieve_study(client, headers, base_url, study_instance_uid, patient_name)
                        break
                    print("\033[91mInvalid choice. Please try again.\033[0m")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        print("An error occurred. Please check the log file for details.")
    finally:
        display_changes_summary()
