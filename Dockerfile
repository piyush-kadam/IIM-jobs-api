FROM python:3.10-slim

# Install Chrome dependencies
RUN apt-get update && apt-get install -y \
    wget unzip gnupg curl fonts-liberation libnss3 libxss1 libasound2 libatk1.0-0 libgtk-3-0 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome
RUN wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt install -y ./google-chrome-stable_current_amd64.deb && \
    rm google-chrome-stable_current_amd64.deb

# Set working directory
WORKDIR /app

# Copy code and install Python dependencies
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
EXPOSE 8000

# Start app
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
