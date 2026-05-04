from flask_login import current_user
from flask_socketio import join_room

from app import socketio
from app.models import Quiz, TeamAnswer, db


@socketio.on('connect', namespace='/judge')
def on_connect():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        join_room(quiz.id)
        join_room('judges')


@socketio.on('disconnect', namespace='/judge')
def on_disconnect():
    """Закрыли вкладку / упало соединение — отдаём незавершённую карточку обратно в пул."""
    if not current_user.is_authenticated:
        return
    TeamAnswer.query.filter(
        TeamAnswer.checked_by == current_user.id,
        TeamAnswer.is_correct.is_(None),
    ).update({'checked_by': None, 'checked_by_at': None},
             synchronize_session=False)
    db.session.commit()
