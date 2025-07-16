# dicom-editor

A little dicom editor tool that allows you to edit dicom attributes, save them, and eventually push the changes back to a Azure DICOM Service.

## Features

### Local DICOM Management
- Browse and edit local DICOM studies and files
- Edit individual DICOM tags and attributes
- Organize studies in folder structures with series

### Azure DICOM Service Integration
- **Fetch Studies**: Manual retrieval of studies from Azure DICOM service
- **Download Studies**: Download remote studies to local storage for editing
- **Upload Studies**: Push local studies to Azure DICOM service using STOW-RS
- Azure authentication using service principal credentials

### Web Interface
- Modern, responsive web interface
- Study and file navigation
- Flash messaging for user feedback
- Individual file and study-level editing

## Getting started

Set all variables in a .env file:
```
DICOM_ROOT=./dicoms
AZURE_DICOM_ENDPOINT=https://your-dicom.azurehealthcareapis.com
AZURE_TENANT_ID=your-tenant-id
AZURE_DICOM_CLIENT_ID=your-client-id
AZURE_DICOM_SECRET=your-client-secret
```

Install dependencies:
```bash
pip install -r requirements.txt
```

Place DICOM content in the /dicoms folder. There also is a sample.zip that you can unpack and place in the folder as a sample to test things out.

Run the app:
```
python app.py
```

Visit http://localhost:5000 to get started.

## Workflow

1. **Browse Local Studies**: View existing local DICOM studies on the main page
2. **Fetch Remote Studies**: Click "Fetch Studies from DICOM Service" to retrieve studies from Azure
3. **Download Studies**: Click "[Download to Local]" next to any remote study to download it locally
4. **Edit Studies**: Use "[Edit study]" to modify study-level attributes or click individual files to edit specific DICOM tags
5. **Upload Studies**: Use "[Upload to DICOM]" to push local studies to the Azure DICOM service

## File Structure

Downloaded studies are organized as:
```
dicoms/
├── PatientName_StudyInstanceUID/
│   ├── series-00000/
│   │   ├── image-00000.dcm
│   │   ├── image-00001.dcm
│   │   └── ...
│   ├── series-00001/
│   │   └── ...
│   └── ...
```