#!/usr/bin/env bash
# Деплой на прод: rsync кода → docker compose up --build → проверка здоровья.
# Вход на сервер — только по SSH-ключу. Секреты живут в /opt/bmstu_quiz/.env
# на сервере и в репозиторий/rsync не попадают.
set -euo pipefail

SERVER="${DEPLOY_SERVER:-root@37.230.112.9}"
DOMAIN="${DEPLOY_DOMAIN:-game.bmstu.kodass.ru}"
REMOTE_DIR="/opt/bmstu_quiz"

cd "$(dirname "$0")"

if [[ -n $(git status --porcelain) ]]; then
    echo "⚠  Есть незакоммиченные изменения — деплоится текущее состояние рабочей папки."
fi

echo "→ Копируем код на $SERVER:$REMOTE_DIR ..."
rsync -az --delete \
    --exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude 'node_modules/' \
    --exclude '.env' --exclude '__pycache__/' --exclude '.idea/' --exclude '.DS_Store' \
    --exclude 'app/static/uploads/' --exclude 'app/static/css/output.css' \
    ./ "$SERVER:$REMOTE_DIR/"

echo "→ Собираем и перезапускаем контейнеры ..."
ssh "$SERVER" DOMAIN="$DOMAIN" REMOTE_DIR="$REMOTE_DIR" bash -s <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"
test -f .env || { echo "✗ Нет $REMOTE_DIR/.env — сначала первичная настройка сервера"; exit 1; }
chmod 600 .env

# nginx: обновляем конфиг из репозитория, только если он валиден.
sed "s/__DOMAIN__/$DOMAIN/g" deploy/nginx.conf > /etc/nginx/sites-available/bmstu_quiz
if nginx -t 2>/dev/null; then systemctl reload nginx; else nginx -t; exit 1; fi

docker compose up --build -d --remove-orphans
docker image prune -f >/dev/null

echo "→ Проверка здоровья ..."
for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:5000/login"; then
        echo "  ✓ приложение отвечает"; break
    fi
    sleep 2
    [ "$i" = 30 ] && { echo "  ✗ приложение не поднялось"; docker compose logs --tail 50 web; exit 1; }
done
docker compose ps --format "table {{.Name}}\t{{.Status}}"
REMOTE

code=$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/login" || true)
echo "✓ Деплой завершён: https://$DOMAIN (HTTP $code)"
