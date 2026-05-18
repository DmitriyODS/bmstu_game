import eventlet
from datetime import datetime
from flask import request, current_app
from flask_login import current_user
from flask_socketio import join_room, emit

from app import socketio
from app.models import db, Quiz, Tour, Question, Team, TeamAnswer, GameState

from app.sockets.utils import broadcast as _broadcast

_timer_greenlets = {}  # quiz_id -> greenlet
_audio_pre_timer_greenlets = {}  # quiz_id -> greenlet (плеер играет, потом стартует таймер)


def _cancel_audio_pre_timer(quiz_id):
    gl = _audio_pre_timer_greenlets.pop(quiz_id, None)
    if gl:
        gl.kill()


def _cancel_timer(quiz_id):
    gl = _timer_greenlets.pop(quiz_id, None)
    if gl:
        gl.kill()


def _broadcast_stop_audio(quiz_id):
    socketio.emit('stop_screen_audio', {}, room=quiz_id, namespace='/presentation')
    socketio.emit('stop_screen_audio', {}, room=quiz_id, namespace='/admin')


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
        _broadcast('registration_opened', {}, quiz.id)
    elif screen == 'question':
        question_id = data.get('question_id')
        if question_id:
            gs.current_question_id = question_id
            q = Question.query.get(question_id)
            if q:
                gs.current_tour_id = q.tour_id
    elif screen == 'question_answer':
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
    elif screen == 'custom_slide':
        tour_id = data.get('tour_id')
        if tour_id:
            gs.current_tour_id = tour_id
            gs.current_question_id = None

    # Останавливаем таймер и pre-timer greenlet при любой смене экрана.
    # Аудио на презентации остановит сам screen_changed-обработчик,
    # отдельный stop_screen_audio здесь слать нельзя — он убил бы фоновый
    # трек, который showAnswer запускает на question_answer.
    _cancel_audio_pre_timer(quiz.id)
    _cancel_timer(quiz.id)
    gs.timer_started_at = None
    gs.timer_seconds = None

    db.session.commit()

    payload = _build_screen_payload(gs, quiz)
    _broadcast('screen_changed', payload, quiz.id)


@socketio.on('close_registration', namespace='/admin')
def on_close_registration():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        gs.registration_open = False
        db.session.commit()
        _broadcast('registration_closed', {}, quiz.id)


@socketio.on('start_timer', namespace='/admin')
def on_start_timer(data):
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if not gs:
        return
    question_id = data.get('question_id', gs.current_question_id)
    if not question_id:
        return
    # Ручной старт отменяет висящий pre-timer (если играет аудио).
    _cancel_audio_pre_timer(quiz.id)
    _start_timer_internal(quiz.id, question_id)


def _run_timer_loop(quiz_id, total_seconds, mid_seconds, sound_mid, sound_end):
    # Идём от total_seconds-1 до 0, шлём tick каждую секунду.
    # 'timer_started' уже отправлено с total_seconds, поэтому первый tick = total-1.
    for remaining in range(total_seconds - 1, -1, -1):
        eventlet.sleep(1)
        _broadcast('timer_tick', {'remaining': remaining}, quiz_id)

        if mid_seconds and remaining == mid_seconds and sound_mid:
            _broadcast('play_sound', {'path': sound_mid, 'event': 'mid'}, quiz_id)

        if remaining == 0:
            if sound_end:
                _broadcast('play_sound', {'path': sound_end, 'event': 'end'}, quiz_id)
            _broadcast('timer_stopped', {}, quiz_id)
            break


def _start_timer_internal(quiz_id, question_id, app=None):
    """Запуск таймера. Можно вызвать как из обработчика сокета (с request context),
    так и из greenlet — в этом случае надо передать app для открытия app_context."""
    def _do(quiz_id, question_id):
        quiz = Quiz.query.get(quiz_id)
        if not quiz:
            return
        gs = GameState.query.filter_by(quiz_id=quiz_id).first()
        if not gs:
            return
        q = Question.query.get(question_id)
        if not q:
            return

        # Resume from paused state if same question, otherwise start fresh
        if (gs.timer_started_at is None and gs.timer_seconds
                and gs.current_question_id == question_id):
            start_seconds = gs.timer_seconds
        else:
            start_seconds = q.time_seconds

        gs.timer_started_at = datetime.utcnow()
        gs.timer_seconds = start_seconds
        db.session.commit()

        _broadcast_stop_audio(quiz_id)
        _broadcast('timer_started',
                   {'seconds': start_seconds, 'started_at': gs.timer_started_at.isoformat()},
                   quiz_id)

        if quiz.sound_start_path and start_seconds == q.time_seconds:
            _broadcast('play_sound', {'path': quiz.sound_start_path, 'event': 'start'}, quiz_id)

        _cancel_timer(quiz_id)
        gl = eventlet.spawn(
            _run_timer_loop, quiz_id, start_seconds,
            quiz.sound_mid_seconds, quiz.sound_mid_path, quiz.sound_end_path,
        )
        _timer_greenlets[quiz_id] = gl

    if app is not None:
        with app.app_context():
            _do(quiz_id, question_id)
    else:
        _do(quiz_id, question_id)


@socketio.on('pause_timer', namespace='/admin')
def on_pause_timer():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    # Отменяем и pre-timer (если ещё играет аудио): пауза должна замораживать всё.
    _cancel_audio_pre_timer(quiz.id)
    _cancel_timer(quiz.id)
    _broadcast_stop_audio(quiz.id)

    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs and gs.timer_started_at and gs.timer_seconds:
        elapsed = int((datetime.utcnow() - gs.timer_started_at).total_seconds())
        remaining = max(0, gs.timer_seconds - elapsed)
        gs.timer_seconds = remaining   # save remaining for resume
        gs.timer_started_at = None     # mark as paused
        db.session.commit()
        _broadcast('timer_paused', {'remaining': remaining}, quiz.id)


@socketio.on('reset_timer', namespace='/admin')
def on_reset_timer():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    _cancel_audio_pre_timer(quiz.id)
    _cancel_timer(quiz.id)
    _broadcast_stop_audio(quiz.id)

    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    if gs:
        gs.timer_started_at = None
        gs.timer_seconds = None  # полный сброс — следующий старт начнёт заново
        db.session.commit()
    _broadcast('timer_reset', {}, quiz.id)
    _broadcast('timer_stopped', {}, quiz.id)


@socketio.on('play_audio_then_timer', namespace='/admin')
def on_play_audio_then_timer(data):
    """Атомарно: транслирует play_question_audio на /presentation, ждёт duration_ms,
    потом запускает таймер. Greenlet хранится в _audio_pre_timer_greenlets и может
    быть отменён через stop_screen_audio / reset_timer / pause_timer / change_screen
    / start_timer (ручной старт)."""
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

    duration_ms = int(data.get('duration_ms') or 0)
    audio_payload = {
        'path': data.get('path') or q.audio_path,
        'trim_start': data.get('trim_start') or 0,
        'trim_end': data.get('trim_end'),
    }

    # Если уже есть pre-timer greenlet или таймер — отменяем (пере-старт).
    _cancel_audio_pre_timer(quiz.id)
    _cancel_timer(quiz.id)

    # play_question_audio handler на презентации сам глушит старое аудио в начале,
    # поэтому отдельный stop_screen_audio здесь не нужен.
    socketio.emit('play_question_audio', audio_payload, room=quiz.id, namespace='/presentation')
    # Сообщаем админкам что pre-timer стартовал — для отображения прогресса.
    socketio.emit('audio_pre_timer_started',
                  {'question_id': q.id, 'duration_ms': duration_ms},
                  room=quiz.id, namespace='/admin')

    app = current_app._get_current_object()

    def run_pre_timer(quiz_id, q_id, wait_ms):
        try:
            eventlet.sleep(max(0, wait_ms) / 1000.0)
        except Exception:
            return
        # Аудио проиграно — стартуем штатный таймер.
        # Удаляем себя из словаря чтобы start_timer не убил себя же при pop.
        _audio_pre_timer_greenlets.pop(quiz_id, None)
        socketio.emit('audio_pre_timer_finished', {'question_id': q_id},
                      room=quiz_id, namespace='/admin')
        _start_timer_internal(quiz_id, q_id, app=app)

    gl = eventlet.spawn(run_pre_timer, quiz.id, q.id, duration_ms)
    _audio_pre_timer_greenlets[quiz.id] = gl


@socketio.on('stop_screen_audio', namespace='/admin')
def on_stop_screen_audio():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return
    # Полная отмена: убиваем pre-timer greenlet (если стартует таймер после
    # окончания аудио — отменяем), а таймер не трогаем (если уже идёт — пусть идёт).
    _cancel_audio_pre_timer(quiz.id)
    _broadcast_stop_audio(quiz.id)


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
    timer_active = False
    timer_remaining = None
    if gs.timer_started_at and gs.timer_seconds:
        from datetime import datetime
        elapsed = int((datetime.utcnow() - gs.timer_started_at).total_seconds())
        remaining = gs.timer_seconds - elapsed
        if remaining > 0:
            timer_active = True
            timer_remaining = remaining

    data = {
        'screen': gs.current_screen,
        'quiz_id': quiz.id,
        'quiz_title': quiz.title,
        'registration_open': gs.registration_open,
        'timer_active': timer_active,
        'timer_remaining': timer_remaining,
    }

    if gs.current_question_id:
        q = Question.query.get(gs.current_question_id)
        if q:
            reveal = gs.current_screen == 'question_answer'
            data['question'] = _question_payload(q, reveal_answers=reveal)

    if gs.current_tour_id:
        tour = Tour.query.get(gs.current_tour_id)
        if tour:
            data['tour'] = {'id': tour.id, 'title': tour.title, 'splash_image': tour.splash_image}

    if gs.current_screen == 'custom_slide' and gs.current_tour_id:
        slide = Tour.query.get(gs.current_tour_id)
        if slide and slide.is_slide:
            data['slide'] = {
                'id': slide.id,
                'title': slide.title,
                'text': slide.slide_text,
                'image': slide.splash_image,
                'audio': slide.slide_audio_path,
            }

    if gs.current_screen in ('tour_results', 'game_results'):
        data['scores'] = _calc_scores(quiz, gs.current_tour_id if gs.current_screen == 'tour_results' else None)

    if gs.current_screen == 'teams':
        teams = Team.query.filter_by(quiz_id=quiz.id).all()
        data['teams'] = [{'id': t.id, 'name': t.name} for t in teams]

    return data


def _question_payload(q, reveal_answers=False):
    options_sorted = sorted(q.answer_options, key=lambda o: (o.order, o.id))
    matching_sorted = sorted(q.matching_items, key=lambda m: (m.order, m.id))
    return {
        'id': q.id,
        'question_type': q.question_type,
        'answer_type': q.answer_type,
        'text': q.text,
        'image_path': q.image_path,
        'audio_path': q.audio_path,
        'audio_trim_start': q.audio_trim_start if q.audio_trim_start is not None else 0.0,
        'audio_trim_end': q.audio_trim_end,
        'answer_audio_path': q.answer_audio_path,
        'time_seconds': q.time_seconds,
        'points': q.points,
        'answer_options': [
            {'id': o.id, 'text': o.text, 'order': o.order,
             **({'is_correct': o.is_correct} if reveal_answers else {})}
            for o in options_sorted
        ],
        'matching_items': [
            {'id': m.id, 'left_text': m.left_text, 'right_text': m.right_text, 'order': m.order}
            for m in matching_sorted
        ],
        'correct_answer': q.correct_answer if reveal_answers else None,
        'sound_start_path': q.tour.quiz.sound_start_path if q.tour else None,
        'sound_mid_path': q.tour.quiz.sound_mid_path if q.tour else None,
        'sound_mid_seconds': q.tour.quiz.sound_mid_seconds if q.tour else None,
        'sound_end_path': q.tour.quiz.sound_end_path if q.tour else None,
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
