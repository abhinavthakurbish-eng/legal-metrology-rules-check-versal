# Base image with Python
FROM python:3.11-slim

# System dependency: Tesseract OCR (this is exactly what Vercel can't install -
# a serverless function has no way to run apt-get, but a Docker container can).
# tesseract-ocr-hin = Hindi language pack. Indian product labels are frequently
# bilingual (English + Hindi, as required for many categories under the
# Legal Metrology Rules) - most existing compliance-checking tools in this
# space don't support Hindi/regional-language labels at all, so this is a
# meaningful gap to close.
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-hin \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better Docker layer caching -
# rebuilds are faster if only app code changes, not dependencies)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Make sure runtime folders exist inside the container
RUN mkdir -p uploads generated_reports static/annotated

# Render (and most platforms) inject the port to listen on via $PORT
ENV PORT=5000
EXPOSE 5000

# gunicorn = production WSGI server (Flask's built-in dev server, which
# app.run() uses, is not meant for real traffic/production use).
# Free-tier hosting (Render free, Railway free) usually gives very limited
# RAM (~512MB) - 1 worker (with a couple threads for light concurrency)
# avoids doubling memory usage that OpenCV/numpy/Tesseract already need.
# Timeout is high (180s) because free-tier CPUs are slow/shared, so a single
# OCR request can genuinely take longer than gunicorn's 30s default - without
# this the worker gets killed mid-request, which looks like a random crash.
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 app:app
