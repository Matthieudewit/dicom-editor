# DICOM Editor

A comprehensive DICOM editing tool that allows you to browse, edit, and manage DICOM studies locally and integrate with Azure DICOM Service for cloud-based DICOM workflows.

## ✨ Features

### 📁 Local DICOM Management
- **Study Browser**: Browse local DICOM studies with series and image counts `(2 series | 23 images)`
- **Tag Editor**: Edit individual DICOM tags with comprehensive validation and protection
- **Tag Deletion**: Delete non-critical DICOM tags with built-in protection for essential tags
- **Study Organization**: Automatic organization of studies in folder structures with series
- **Large File Support**: Handle large DICOM files up to 500MB with optimized processing

### ☁️ Azure DICOM Service Integration
- **Fetch All Studies**: Retrieve all studies from Azure DICOM service
- **Search by UID**: Find specific studies using Study Instance UID
- **Download Studies**: Download remote studies to local storage with proper folder structure
- **Upload Studies**: Push local studies to Azure DICOM service using STOW-RS protocol
- **Azure Authentication**: Secure authentication using service principal credentials
- **Real-time Logging**: Monitor Azure operations with detailed application logs

### 🎯 Advanced DICOM Editing
- **Tag Count Display**: Shows total tags per file `(59 tags)` in edit view
- **Protected Tags**: Prevents deletion of critical DICOM tags (SOPClassUID, PatientID, etc.)
- **Value Truncation**: Smart truncation of large tag values for better UI performance
- **Search & Filter**: Real-time search through DICOM tags by description
- **Validation**: Input validation and error handling for tag modifications

### 🖥️ Modern Web Interface
- **Responsive Design**: Clean, modern interface that works on all screen sizes
- **Session Management**: Runtime configuration with session-based settings
- **Flash Messaging**: Clear user feedback for all operations
- **Utility Functions**: Built-in log viewer and settings management
- **Debug Support**: Full VSCode debugging integration with launch configurations

### 🔧 Development & Operations
- **Error Handling**: Comprehensive error handling with detailed logging
- **Sample Data**: Built-in sample data loading for testing
- **Settings Management**: Runtime configuration without restart
- **Log Management**: Application logging with file rotation
- **Development Tools**: Hot reload, debug support, and error tracking

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- Azure DICOM Service (optional, for cloud integration)
- Service Principal with DICOM service access (for Azure features)

### Configuration

Create a `.env` file in the project root with your Azure credentials:
```env
# Local DICOM storage location
DICOM_ROOT=./dicoms

# Azure DICOM Service Configuration (optional)
AZURE_DICOM_ENDPOINT=https://your-dicom.azurehealthcareapis.com
AZURE_TENANT_ID=your-tenant-id
AZURE_DICOM_CLIENT_ID=your-client-id
AZURE_DICOM_SECRET=your-client-secret

# Flask Configuration (optional)
FLASK_DEBUG=1
FLASK_RUN_PORT=5001
```

### Installation

1. **Clone the repository**:
```bash
git clone https://github.com/Matthieudewit/dicom-editor.git
cd dicom-editor
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Setup DICOM data**:
   - Create a `dicoms` folder or use your preferred location
   - Extract `sample_dicom.zip` for test data, or
   - Use "Load Sample Data" button in the web interface

4. **Run the application**:
```bash
python app.py
```

5. **Access the interface**:
   - Open http://localhost:5001 in your browser
   - Use the settings page to configure paths and Azure credentials at runtime

## 📖 User Guide

### Basic Workflow

1. **🏠 Main Dashboard**
   - View all local studies with series/image counts
   - Access utility functions (Logs, Settings)
   - Search for specific studies by UID

2. **☁️ Azure Integration**
   - **Fetch All**: Click "Fetch Studies from DICOM Service" to see all remote studies
   - **Search Specific**: Enter a Study Instance UID to find a particular study
   - **Download**: Click "[Download to Local]" to download studies for editing

3. **✏️ Editing Workflow**
   - **Study Level**: Click "[Edit study]" to modify patient/study information
   - **File Level**: Click individual DICOM files to edit specific tags
   - **Tag Management**: Add, modify, or delete DICOM tags with protection

4. **💾 Save & Upload**
   - Changes are saved automatically to local files
   - Use "[Upload to DICOM]" to push edited studies back to Azure
   - Monitor operations via the logs viewer

### Advanced Features

#### 🔍 DICOM Tag Editing
- **Search Tags**: Use the search box to filter tags by description
- **Protected Tags**: Critical tags (SOPClassUID, PatientID, etc.) cannot be deleted
- **Large Values**: Values over 1000 characters are truncated in display but fully editable
- **Validation**: Input validation prevents invalid modifications

#### ⚙️ Settings Management
- **Runtime Config**: Change settings without restarting the application
- **Session Based**: Settings apply to current session only
- **Reset Option**: Restore original .env file values anytime

#### 📊 Monitoring & Debugging
- **Application Logs**: View real-time application logs and errors
- **Flash Messages**: Clear feedback for all user actions
- **VSCode Integration**: Full debugging support with breakpoints

## 📁 File Structure

The application organizes DICOM data in a structured format:

```
dicom-editor/
├── app.py                 # Main Flask application
├── config.py             # Configuration management
├── requirements.txt      # Python dependencies
├── .env                  # Environment variables (create this)
├── .vscode/              # VSCode debug configuration
│   ├── launch.json
│   ├── tasks.json
│   └── settings.json
├── dicoms/               # Local DICOM storage (configurable)
│   ├── Study_Name_1/     # Individual study folders
│   │   ├── series-00000/ # Series organized by number
│   │   │   ├── image-00000.dcm
│   │   │   ├── image-00001.dcm
│   │   │   └── ...
│   │   ├── series-00001/
│   │   │   └── ...
│   │   └── ...
│   └── Study_Name_2/
│       └── ...
├── static/               # CSS and frontend assets
│   └── styles.css
├── templates/            # HTML templates
│   ├── select.html       # Main dashboard
│   ├── edit_study.html   # Study-level editor
│   ├── edit_file.html    # DICOM tag editor
│   ├── settings.html     # Configuration page
│   └── logfile.html      # Log viewer
└── dicom_editor.log      # Application logs
```

## 🔧 Development

### VSCode Setup
The project includes complete VSCode debugging configuration:

1. **Debug Configuration**: Pre-configured launch.json for Flask debugging
2. **Tasks**: Build and run tasks in tasks.json
3. **Settings**: Python interpreter and formatting settings

### Key Components

- **Flask Backend**: RESTful API with session management
- **PyDICOM**: DICOM file parsing and manipulation
- **Azure SDK**: Integration with Azure Health Data Services
- **Jinja2 Templates**: Server-side rendering with modern CSS
- **Request Handling**: Support for large files up to 500MB

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with appropriate tests
4. Submit a pull request

## 🛠️ Troubleshooting

### Common Issues

#### **413 Request Entity Too Large**
- The application supports files up to 500MB
- For larger files, consider processing in smaller chunks
- Check your web server configuration if using a proxy

#### **Azure Authentication Errors**
- Verify your service principal has DICOM Data Contributor role
- Check that all Azure credentials are correctly configured
- Use the Settings page to verify configuration at runtime

#### **DICOM File Reading Errors**
- Ensure files are valid DICOM format
- Check file permissions in the DICOM root directory
- Use PyDICOM's force=True flag for non-standard files

#### **Performance Issues**
- Large DICOM tag values are automatically truncated for display
- Consider organizing studies with fewer files per series
- Monitor application logs for performance bottlenecks

### Getting Help

- **Application Logs**: Use the "View Logs" button for detailed error information
- **Debug Mode**: Enable Flask debug mode for detailed error pages
- **VSCode Debugging**: Use breakpoints to troubleshoot issues step-by-step

## 📄 License

This project is licensed under the MIT License. See the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [PyDICOM](https://pydicom.github.io/) for DICOM processing
- [Flask](https://flask.palletsprojects.com/) for the web framework
- [Azure SDK](https://azure.github.io/azure-sdk-for-python/) for cloud integration
- DICOM standards compliance through healthcare industry best practices