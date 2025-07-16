# dicom-editor

A little dicom editor tool that allows you to edit dicom attributes, save them, and eventually push the changes back to a Azure DICOM Service.

## Getting started

Set all variables in a .env file:
```
DICOM_ROOT=./dicoms
AZURE_DICOM_ENDPOINT=https://your-dicom.azurehealthcareapis.com
```

Place DICOM content in the /dicoms folder. There also is a sample.zip that you can unpack and place in the folder as a sample to test things out.

Run the app:
```
python app.py
```

Visit http://localhost:5000 to get started.