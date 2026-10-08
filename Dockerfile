FROM python:3.12-slim

WORKDIR /app

# Install Node.js for Tailwind CLI
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Build Tailwind CSS
RUN npx tailwindcss -i ./app/static/css/input.css -o ./app/static/css/output.css --minify \
    && rm -rf node_modules

# Приложение работает не от root. Папка uploads создаётся заранее с нужным
# владельцем — Docker скопирует права в новый именованный volume.
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/app/static/uploads \
    && chown -R app:app /app/app/static/uploads
USER app

EXPOSE 5000

CMD ["python", "-m", "gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "wsgi:app"]
