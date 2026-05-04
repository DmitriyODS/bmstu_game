"""Политика блокировок карточек у судей и фоновой sweeper.

Каждая взятая судьёй карточка имеет два таймштампа:

- ``checked_by_at`` — момент последнего heartbeat (продлевается фронтом).
- ``checked_lock_started_at`` — момент первого захвата (НЕ продлевается).

Карточка считается «протухшей» и должна быть отдана обратно в общий пул, если:

- с момента последнего heartbeat прошло больше ``STALE_HEARTBEAT_SECONDS``
  (судья ушёл, вкладку закрыл, сеть упала), ИЛИ
- с момента первого захвата прошло больше ``MAX_LOCK_LIFETIME_SECONDS``
  (судья «висит» на одной карточке, держит её активным heartbeat).
"""
from datetime import datetime, timedelta

import eventlet

from app.models import db, TeamAnswer

# Если последний heartbeat был раньше — карточка протухла.
STALE_HEARTBEAT_SECONDS = 30
# Если первый захват был раньше — карточка протухла независимо от heartbeat.
MAX_LOCK_LIFETIME_SECONDS = 180
# Период работы фонового sweeper'а.
SWEEP_INTERVAL_SECONDS = 15

_sweeper_started = False


def release_stale_locks():
    """Снять блокировки с карточек, которые либо давно не пинговались,
    либо удерживаются дольше потолка. Возвращает кол-во освобождённых строк."""
    now = datetime.utcnow()
    stale_before = now - timedelta(seconds=STALE_HEARTBEAT_SECONDS)
    lifetime_before = now - timedelta(seconds=MAX_LOCK_LIFETIME_SECONDS)
    n = (TeamAnswer.query
         .filter(TeamAnswer.checked_by.isnot(None),
                 TeamAnswer.is_correct.is_(None),
                 db.or_(
                     TeamAnswer.checked_by_at < stale_before,
                     db.and_(
                         TeamAnswer.checked_lock_started_at.isnot(None),
                         TeamAnswer.checked_lock_started_at < lifetime_before,
                     ),
                 ))
         .update({'checked_by': None,
                  'checked_by_at': None,
                  'checked_lock_started_at': None},
                 synchronize_session=False))
    if n:
        db.session.commit()
    else:
        db.session.rollback()
    return n


def start_sweeper(app):
    """Запустить фонового sweeper'а один раз на процесс.
    Вызывать после инициализации приложения; повторные вызовы игнорируются."""
    global _sweeper_started
    if _sweeper_started:
        return
    _sweeper_started = True

    def _loop():
        while True:
            eventlet.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                with app.app_context():
                    release_stale_locks()
            except Exception:
                # Падение свипера не должно убивать процесс — следующий тик попробует снова.
                try:
                    db.session.rollback()
                except Exception:
                    pass

    eventlet.spawn(_loop)
