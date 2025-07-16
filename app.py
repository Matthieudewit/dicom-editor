from flask import Flask, render_template, request, redirect, url_for
import os
import pydicom
from config import DICOM_ROOT

app = Flask(__name__)

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
    studies = get_all_studies()
    # study_paths = {study: get_dicom_files(os.path.join(DICOM_ROOT, study)) for study in studies}

    study_paths = {
    study: [
        os.path.relpath(path, DICOM_ROOT)
        for path in get_dicom_files(os.path.join(DICOM_ROOT, study))
    ]
    for study in studies
}

    return render_template("select.html", studies=study_paths)

@app.route("/edit-study/<study>")
def edit_study(study):
    study_path = os.path.join(DICOM_ROOT, study)
    dicom_files = get_dicom_files(study_path)

    sample = pydicom.dcmread(dicom_files[0]) if dicom_files else None

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
        ds = pydicom.dcmread(file)
        for key, value in request.form.items():
            if hasattr(ds, key):
                setattr(ds, key, value)
        ds.save_as(file)

    return redirect(url_for('edit_study', study=study))

@app.route("/edit-file/<path:file_path>")
def edit_file(file_path):
    abs_path = os.path.join(DICOM_ROOT, file_path)
    ds = pydicom.dcmread(abs_path)
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
    ds = pydicom.dcmread(abs_path)
    for key in request.form:
        if hasattr(ds, key):
            setattr(ds, key, request.form[key])
    ds.save_as(abs_path)
    return redirect(url_for('edit_file', file_path=file_path))

if __name__ == "__main__":
    app.run(debug=True)