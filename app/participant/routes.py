import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, request, flash, session, jsonify, current_app
from app.participant import participant_bp
from app.models import db, Quiz, Team, TeamAnswer, GameState, Question
from app.scoring import matching_token


def _get_active_quiz():
    return Quiz.query.filter_by(is_active=True).first()


def _get_team(quiz_id=None):
    team_id = session.get('team_id')
    if not team_id:
        return None
    team = Team.query.get(team_id)
    # Сессия от прошлого квиза не должна выдавать себя за команду в новом.
    if team and quiz_id and team.quiz_id != quiz_id:
        return None
    return team


@participant_bp.route('/play')
def play():
    quiz = _get_active_quiz()
    if not quiz:
        return render_template('participant/no_quiz.html')
    return redirect(url_for('participant.play_quiz', quiz_id=quiz.id))


@participant_bp.route('/play/<quiz_id>')
def play_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    gs = GameState.query.filter_by(quiz_id=quiz_id).first()
    team = _get_team(quiz_id)

    # Restore session by token in cookie
    token = request.cookies.get('session_token')
    if not team and token:
        team = Team.query.filter_by(session_token=token, quiz_id=quiz_id).first()
        if team:
            session['team_id'] = team.id

    # Уже отправленный ответ на текущий вопрос — чтобы после перезагрузки
    # страницы участник видел свой выбор, а не пустую форму.
    current_answer = None
    if team and gs and gs.current_question_id:
        ans = TeamAnswer.query.filter_by(
            team_id=team.id,
            question_id=gs.current_question_id
        ).first()
        if ans:
            current_answer = {
                'question_id': ans.question_id,
                'answer_text': ans.answer_text,
                'selected_options': ans.selected_options or [],
                'matching_pairs': [
                    {'left_id': p['left_id'], 'right_id': matching_token(p['right_id'])}
                    for p in (ans.matching_pairs or [])
                    if isinstance(p, dict) and p.get('left_id') and p.get('right_id')
                ],
            }

    return render_template('participant/play.html',
                           quiz=quiz, gs=gs, team=team,
                           current_answer=current_answer)


@participant_bp.route('/play/register', methods=['POST'])
def register():
    quiz_id = request.form.get('quiz_id')
    quiz = Quiz.query.get_or_404(quiz_id)
    gs = GameState.query.filter_by(quiz_id=quiz_id).first()

    team = _get_team(quiz_id)

    if team:
        # Update name if registration is open
        if gs and gs.registration_open:
            new_name = request.form.get('name', '').strip()[:256]
            if new_name and new_name != team.name:
                team.name = new_name
                db.session.commit()
                from app.sockets.utils import broadcast
                broadcast('team_name_updated', {'team_id': team.id, 'name': team.name}, quiz_id)
        return redirect(url_for('participant.play_quiz', quiz_id=quiz_id))

    name = request.form.get('name', '').strip()[:256]
    if not name:
        flash('Введите название команды', 'error')
        return redirect(url_for('participant.play_quiz', quiz_id=quiz_id))

    token = str(uuid.uuid4())
    team = Team(quiz_id=quiz_id, name=name, session_token=token)
    db.session.add(team)
    db.session.commit()

    session['team_id'] = team.id

    from app.sockets.utils import broadcast
    broadcast('team_registered', {'team_id': team.id, 'name': team.name}, quiz_id)

    resp = redirect(url_for('participant.play_quiz', quiz_id=quiz_id))
    resp.set_cookie('session_token', token, max_age=60*60*24*30, httponly=True, samesite='Lax',
                    secure=current_app.config.get('SESSION_COOKIE_SECURE', False))
    return resp


@participant_bp.route('/play/submit', methods=['POST'])
def submit_answer():
    data = request.json or {}
    team = _get_team()
    if not team:
        return jsonify({'error': 'not_registered'}), 403

    question_id = data.get('question_id')
    question = Question.query.get_or_404(question_id)

    # Ответ принимается только пока вопрос на экране: после «Показать ответ»
    # или перехода на другой экран таймер сброшен, и без этой проверки
    # можно было бы переотправить ответ, уже зная правильный.
    gs = GameState.query.filter_by(quiz_id=team.quiz_id).first()
    if (not gs or not team.quiz.is_active or gs.current_screen != 'question'
            or gs.current_question_id != question_id):
        return jsonify({'error': 'question_not_active'}), 400

    if gs.timer_started_at and gs.timer_seconds:
        elapsed = (datetime.utcnow() - gs.timer_started_at).total_seconds()
        if elapsed > gs.timer_seconds:
            return jsonify({'error': 'time_is_up'}), 400

    # Upsert answer
    answer = TeamAnswer.query.filter_by(team_id=team.id, question_id=question_id).first()
    if not answer:
        answer = TeamAnswer(team_id=team.id, question_id=question_id)
        db.session.add(answer)

    answer.submitted_at = datetime.utcnow()

    if question.answer_type in ('single_choice', 'multiple_choice'):
        option_ids = {o.id for o in question.answer_options}
        selected = [i for i in (data.get('selected_options') or []) if i in option_ids]
        if question.answer_type == 'single_choice':
            selected = selected[:1]
        answer.selected_options = selected
        answer.answer_text = None
    elif question.answer_type == 'matching':
        # Правые части приходят под непрозрачными токенами — переводим обратно в id.
        item_ids = {m.id for m in question.matching_items}
        by_token = {matching_token(i): i for i in item_ids}
        pairs = []
        for pair in data.get('matching_pairs') or []:
            if not isinstance(pair, dict):
                continue
            left_id = pair.get('left_id')
            right_id = by_token.get(pair.get('right_id'))
            if left_id in item_ids and right_id:
                pairs.append({'left_id': left_id, 'right_id': right_id})
        answer.matching_pairs = pairs
        answer.answer_text = None
    else:
        answer.answer_text = str(data.get('answer_text') or '')[:2000]
        answer.selected_options = None

    # Auto-check
    if question.auto_check and question.answer_type in ('single_choice', 'multiple_choice'):
        correct_ids = {o.id for o in question.answer_options if o.is_correct}
        submitted = set(answer.selected_options or [])
        answer.is_correct = bool(submitted) and submitted == correct_ids
        answer.score = question.points if answer.is_correct else 0
        answer.auto_checked = True
    else:
        answer.is_correct = None
        answer.score = 0
        answer.auto_checked = False

    # Пересдача — сбрасываем блокировку/аудит, чтобы ответ сразу попал в очередь судей.
    answer.checked_by = None
    answer.checked_by_at = None
    answer.checked_lock_started_at = None

    db.session.commit()

    from app.sockets.utils import broadcast
    broadcast('answer_submitted',
              {'team_id': team.id, 'team_name': team.name, 'question_id': question_id},
              team.quiz_id)

    return jsonify({'ok': True, 'is_correct': answer.is_correct, 'score': answer.score})
