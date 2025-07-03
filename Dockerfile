FROM python:3.10-slim

# Install dependencies including Chrome
RUN apt-get update && apt-get install -y \
    wget gnupg2 curl unzip fonts-liberation \
    libnss3 libatk-bridge2.0-0 libgtk-3-0 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libasound2 libpangocairo-1.0-0 \
    && wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt install -y ./google-chrome-stable_current_amd64.deb \
    && rm google-chrome-stable_current_amd64.deb

WORKDIR /app
COPY . .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
