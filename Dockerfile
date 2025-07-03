# Use an official Python image
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y wget curl unzip gnupg2 libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 libxss1 libappindicator3-1 libasound2 xdg-utils fonts-liberation libu2f-udev chromium chromium-driver && \
    apt-get clean

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Expose port
EXPOSE 10000

# Run app using gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]
