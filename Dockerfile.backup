# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Tesseract OCR and pdf2image
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements first (for better caching)
COPY backend/requirements.txt ./requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_sm

# Copy all application code
COPY backend ./backend
COPY frontend ./frontend

# Expose port (Railway will set PORT env variable)
EXPOSE 8000

# Start the application from backend directory
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
