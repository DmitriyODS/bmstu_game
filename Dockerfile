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
RUN npx tailwindcss -i ./app/static/css/input.css -o ./app/static/css/output.css --minify

EXPOSE 5000

CMD ["python", "-m", "gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "wsgi:app"]
