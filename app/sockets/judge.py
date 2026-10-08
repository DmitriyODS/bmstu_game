from flask_login import current_user
from flask_socketio import join_room

from app import socketio
from app.models import Quiz


@socketio.on('connect', namespace='/judge')
def on_connect():
    if not current_user.is_authenticated or current_user.role not in ('admin', 'judge'):
        return False
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        join_room(quiz.id)
        join_room('judges')


@socketio.on('disconnect', namespace='/judge')
def on_disconnect():
    # Карточку при обрыве сокета НЕ освобождаем: короткий сбой сети (смена
    # Wi-Fi, сон вкладки) разрывает сокет, а судья продолжает смотреть на
    # карточку — её тут же забирал другой судья, и один ответ проверяли дважды.
    # Закрытие вкладки ловят pagehide/visibilitychange (явный release), а
    # пропавшего судью — протухший heartbeat (см. app/judge/locks.py).
    pass
