from dotenv import load_dotenv
import os

load_dotenv()

DICOM_ROOT = os.getenv("DICOM_ROOT", "./dicoms")
AZURE_DICOM_ENDPOINT = os.getenv("AZURE_DICOM_ENDPOINT")
AZURE_TOKEN = os.getenv("AZURE_TOKEN")
