import eventlet
from datetime import datetime
from flask import request
from flask_login import current_user
from flask_socketio import join_room, emit

from app import socketio
from app.models import db, Quiz, Tour, Question, Team, TeamAnswer, GameState

_timer_greenlets = {}  # quiz_id -> greenlet


@socketio.on('connect', namespace='/admin')
def on_connect():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        join_room(quiz.id)
        gs = GameState.query.filter_by(quiz_id=quiz.id).first()
        if gs:
            _emit_state(gs)


@socketio.on('change_screen', namespace='/admin')
def on_change_screen(data):
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if not gs:
        return

    screen = data.get('screen')
    gs.current_screen = screen

    if screen == 'registration':
        gs.registration_open = True
        socketio.emit('registration_opened', {}, room=quiz.id)
    elif screen == 'question':
        question_id = data.get('question_id')
        if question_id:
            gs.current_question_id = question_id
            q = Question.query.get(question_id)
            if q:
                gs.current_tour_id = q.tour_id
    elif screen == 'tour_splash':
        tour_id = data.get('tour_id')
        if tour_id:
            gs.current_tour_id = tour_id
    elif screen == 'tour_results':
        tour_id = data.get('tour_id')
        if tour_id:
            gs.current_tour_id = tour_id

    db.session.commit()

    payload = _build_screen_payload(gs, quiz)
    socketio.emit('screen_changed', payload, room=quiz.id)


@socketio.on('close_registration', namespace='/admin')
def on_close_registration():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        gs.registration_open = False
        db.session.commit()
        socketio.emit('registration_closed', {}, room=quiz.id)


@socketio.on('start_timer', namespace='/admin')
def on_start_timer(data):
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if not gs:
        return

    question_id = data.get('question_id', gs.current_question_id)
    q = Question.query.get(question_id)
    if not q:
        return

    gs.timer_started_at = datetime.utcnow()
    gs.timer_seconds = q.time_seconds
    db.session.commit()

    socketio.emit('timer_started',
                  {'seconds': q.time_seconds, 'started_at': gs.timer_started_at.isoformat()},
                  room=quiz.id)

    # Play start sound
    if q.sound_start_path:
        socketio.emit('play_sound', {'path': q.sound_start_path, 'event': 'start'}, room=quiz.id)

    # Cancel previous timer
    if quiz.id in _timer_greenlets:
        _timer_greenlets[quiz.id].kill()

    def run_timer(quiz_id, total_seconds, q_id, mid_seconds, sound_mid, sound_end):
        for remaining in range(total_seconds, -1, -1):
            eventlet.sleep(1)
            socketio.emit('timer_tick', {'remaining': remaining}, room=quiz_id)

            if mid_seconds and remaining == mid_seconds and sound_mid:
                socketio.emit('play_sound', {'path': sound_mid, 'event': 'mid'}, room=quiz_id)

            if remaining == 0:
                if sound_end:
                    socketio.emit('play_sound', {'path': sound_end, 'event': 'end'}, room=quiz_id)
                socketio.emit('timer_stopped', {}, room=quiz_id)
                break

    gl = eventlet.spawn(run_timer,
                        quiz.id, q.time_seconds, q.id,
                        q.sound_mid_seconds, q.sound_mid_path, q.sound_end_path)
    _timer_greenlets[quiz.id] = gl


@socketio.on('pause_timer', namespace='/admin')
def on_pause_timer():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    if quiz.id in _timer_greenlets:
        _timer_greenlets[quiz.id].kill()
        del _timer_greenlets[quiz.id]

    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs and gs.timer_started_at and gs.timer_seconds:
        elapsed = int((datetime.utcnow() - gs.timer_started_at).total_seconds())
        remaining = max(0, gs.timer_seconds - elapsed)
        socketio.emit('timer_paused', {'remaining': remaining}, room=quiz.id)


@socketio.on('reset_timer', namespace='/admin')
def on_reset_timer():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    if quiz.id in _timer_greenlets:
        _timer_greenlets[quiz.id].kill()
        del _timer_greenlets[quiz.id]
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        gs.timer_started_at = None
        db.session.commit()
    socketio.emit('timer_stopped', {}, room=quiz.id)


@socketio.on('disconnect', namespace='/admin')
def on_disconnect():
    pass


# ── Helpers ────────────────────────────────────────────────────────────────────

def _emit_state(gs):
    quiz = Quiz.query.get(gs.quiz_id)
    if not quiz:
        return
    payload = _build_screen_payload(gs, quiz)
    emit('screen_changed', payload)


def _build_screen_payload(gs, quiz):
    data = {
        'screen': gs.current_screen,
        'quiz_id': quiz.id,
        'quiz_title': quiz.title,
        'registration_open': gs.registration_open,
    }

    if gs.current_question_id:
        q = Question.query.get(gs.current_question_id)
        if q:
            data['question'] = _question_payload(q)

    if gs.current_tour_id:
        tour = Tour.query.get(gs.current_tour_id)
        if tour:
            data['tour'] = {'id': tour.id, 'title': tour.title, 'splash_image': tour.splash_image}

    if gs.current_screen in ('tour_results', 'game_results'):
        data['scores'] = _calc_scores(quiz, gs.current_tour_id if gs.current_screen == 'tour_results' else None)

    if gs.current_screen == 'teams':
        teams = Team.query.filter_by(quiz_id=quiz.id).all()
        data['teams'] = [{'id': t.id, 'name': t.name} for t in teams]

    return data


def _question_payload(q):
    return {
        'id': q.id,
        'question_type': q.question_type,
        'answer_type': q.answer_type,
        'text': q.text,
        'image_path': q.image_path,
        'audio_path': q.audio_path,
        'time_seconds': q.time_seconds,
        'points': q.points,
        'answer_options': [
            {'id': o.id, 'text': o.text, 'is_correct': o.is_correct}
            for o in q.answer_options
        ],
        'matching_items': [
            {'id': m.id, 'left_text': m.left_text, 'right_text': m.right_text}
            for m in q.matching_items
        ],
        'correct_answer': q.correct_answer,
        'sound_start_path': q.sound_start_path,
        'sound_mid_path': q.sound_mid_path,
        'sound_mid_seconds': q.sound_mid_seconds,
        'sound_end_path': q.sound_end_path,
    }


def _calc_scores(quiz, tour_id=None):
    teams = Team.query.filter_by(quiz_id=quiz.id).all()
    result = []
    for team in teams:
        if tour_id:
            q_ids = {q.id for tour in quiz.tours if tour.id == tour_id for q in tour.questions}
            score = sum(a.score for a in team.answers if a.question_id in q_ids and a.score)
        else:
            score = sum(a.score for a in team.answers if a.score)
        result.append({'team_id': team.id, 'team_name': team.name, 'score': score})
    result.sort(key=lambda x: -x['score'])
    for i, r in enumerate(result):
        r['place'] = i + 1
    return result
