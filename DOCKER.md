# Docker Setup for DICOM Editor

This document provides instructions for running the DICOM Editor application using Docker.

## Prerequisites

- Docker installed on your system
- Docker Compose (optional, but recommended)

## Quick Start with Docker Compose

1. **Clone the repository** (if you haven't already):
   ```bash
   git clone <repository-url>
   cd dicom-editor
   ```

2. **Create environment file** (optional):
   ```bash
   cp .env.example .env
   # Edit .env with your specific configuration
   ```

3. **Build and run the application**:
   ```bash
   docker-compose up --build
   ```

4. **Access the application**:
   Open your browser and navigate to `http://localhost:5001`

## Manual Docker Commands

### Building the Image

```bash
docker build -t dicom-editor .
```

### Running the Container

```bash
docker run -d \
  --name dicom-editor \
  -p 5001:5001 \
  -v $(pwd)/dicoms:/app/dicoms \
  -v $(pwd)/logs:/app/logs \
  -e FLASK_DEBUG=0 \
  dicom-editor
```

## Volume Mounts

The application uses the following volumes:

- `/app/dicoms` - DICOM files storage
- `/app/logs` - Application logs

Make sure to mount these volumes to persist your data between container restarts.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLASK_DEBUG` | Enable Flask debug mode | `0` |
| `FLASK_RUN_HOST` | Host to bind the Flask app | `0.0.0.0` |
| `FLASK_RUN_PORT` | Port to run the Flask app | `5001` |
| `DICOM_ROOT` | Root directory for DICOM files | `/app/dicoms` |
| `AZURE_DICOM_ENDPOINT` | Azure DICOM service endpoint | None |
| `AZURE_DICOM_CLIENT_ID` | Azure client ID | None |
| `AZURE_DICOM_SECRET` | Azure client secret | None |
| `AZURE_TENANT_ID` | Azure tenant ID | None |

## Azure DICOM Service Integration

If you want to use Azure DICOM service integration:

1. Set up an Azure DICOM service
2. Create a service principal with appropriate permissions
3. Configure the Azure environment variables in your `.env` file or docker-compose.yml

## Health Check

The container includes a health check that verifies the application is running properly. You can check the health status with:

```bash
docker ps
```

Look for the health status in the STATUS column.

## Stopping the Application

### With Docker Compose:
```bash
docker-compose down
```

### With Docker:
```bash
docker stop dicom-editor
docker rm dicom-editor
```

## Troubleshooting

### Check logs:
```bash
# With Docker Compose
docker-compose logs dicom-editor

# With Docker
docker logs dicom-editor
```

### Access container shell:
```bash
# With Docker Compose
docker-compose exec dicom-editor /bin/bash

# With Docker
docker exec -it dicom-editor /bin/bash
```

### Rebuild after changes:
```bash
# With Docker Compose
docker-compose up --build

# With Docker
docker build -t dicom-editor . --no-cache
```

## Security Notes

- The container runs as a non-root user for security
- Make sure to properly configure Azure credentials if using Azure integration
- Consider using Docker secrets for sensitive environment variables in production
