from flask import request
from flask_socketio import join_room, emit

from app import socketio
from app.models import Quiz, GameState
from app.sockets.admin import _build_screen_payload


@socketio.on('connect', namespace='/presentation')
def on_connect():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return

    join_room(quiz.id)

    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        payload = _build_screen_payload(gs, quiz)
        emit('screen_changed', payload)


@socketio.on('disconnect', namespace='/presentation')
def on_disconnect():
    pass
