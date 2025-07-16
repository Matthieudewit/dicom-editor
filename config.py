from dotenv import load_dotenv
import os

load_dotenv()

DICOM_ROOT = os.getenv("DICOM_ROOT", "./dicoms")
AZURE_DICOM_ENDPOINT = os.getenv("AZURE_DICOM_ENDPOINT")
AZURE_DICOM_CLIENT_ID = os.getenv("AZURE_DICOM_CLIENT_ID")
AZURE_DICOM_SECRET = os.getenv("AZURE_DICOM_SECRET")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
