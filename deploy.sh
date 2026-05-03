#!/usr/bin/env bash
set -e

SERVER="ubuntu@171.22.180.77"
REMOTE_DIR="~/bmstu_quiz"

# Пушим локальные изменения на GitHub
# Проверяем только tracked-изменения (не untracked)
if [[ $(git status --porcelain | grep -v '^??') ]]; then
    echo "⚠  Есть незакоммиченные изменения — сначала сделай commit."
    git status --short | grep -v '^??'
    exit 1
fi

echo "→ Пушим в GitHub..."
git push origin main

# Деплоим на сервер
echo "→ Деплоим на $SERVER..."
ssh "$SERVER" bash -s <<'REMOTE'
set -e
cd ~/bmstu_quiz
echo "  git pull..."
git pull origin main
echo "  docker compose up --build -d..."
docker compose up --build -d
echo "  ✓ Готово. Контейнеры:"
docker compose ps --format "table {{.Name}}\t{{.Status}}"
REMOTE

echo "✓ Деплой завершён."
