from flask import session
from flask_socketio import join_room, emit

from app import socketio
from app.models import Quiz


@socketio.on('connect', namespace='/judge')
def on_connect():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        join_room(quiz.id)
        join_room('judges')


@socketio.on('disconnect', namespace='/judge')
def on_disconnect():
    pass
