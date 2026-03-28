from flask import request, session
from flask_socketio import join_room, emit

from app import socketio
from app.models import Quiz, Team, GameState
from app.sockets.admin import _build_screen_payload


@socketio.on('connect', namespace='/participant')
def on_connect():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return

    join_room(quiz.id)

    team_id = session.get('team_id')
    if team_id:
        team = Team.query.get(team_id)
        if team:
            join_room(f'team_{team_id}')

    # Send current state
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        payload = _build_screen_payload(gs, quiz)
        emit('screen_changed', payload)


@socketio.on('disconnect', namespace='/participant')
def on_disconnect():
    pass
