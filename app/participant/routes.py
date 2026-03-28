import uuid
from datetime import datetime
from flask import render_template, redirect, url_for, request, flash, session, jsonify
from app.participant import participant_bp
from app.models import db, Quiz, Team, TeamAnswer, GameState, Question


def _get_active_quiz():
    return Quiz.query.filter_by(is_active=True).first()


def _get_team():
    team_id = session.get('team_id')
    if team_id:
        return Team.query.get(team_id)
    return None


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
    team = _get_team()

    # Restore session by token in cookie
    token = request.cookies.get('session_token')
    if not team and token:
        team = Team.query.filter_by(session_token=token, quiz_id=quiz_id).first()
        if team:
            session['team_id'] = team.id

    current_answer = None
    if team and gs and gs.current_question_id:
        current_answer = TeamAnswer.query.filter_by(
            team_id=team.id,
            question_id=gs.current_question_id
        ).first()

    return render_template('participant/play.html',
                           quiz=quiz, gs=gs, team=team,
                           current_answer=current_answer)


@participant_bp.route('/play/register', methods=['POST'])
def register():
    quiz_id = request.form.get('quiz_id')
    quiz = Quiz.query.get_or_404(quiz_id)
    gs = GameState.query.filter_by(quiz_id=quiz_id).first()

    team = _get_team()

    if team:
        # Update name if registration is open
        if gs and gs.registration_open:
            new_name = request.form.get('name', '').strip()
            if new_name and new_name != team.name:
                team.name = new_name
                db.session.commit()
                from app import socketio
                socketio.emit('team_name_updated',
                              {'team_id': team.id, 'name': team.name},
                              room=quiz_id)
        return redirect(url_for('participant.play_quiz', quiz_id=quiz_id))

    name = request.form.get('name', '').strip()
    if not name:
        flash('Введите название команды', 'error')
        return redirect(url_for('participant.play_quiz', quiz_id=quiz_id))

    token = str(uuid.uuid4())
    team = Team(quiz_id=quiz_id, name=name, session_token=token)
    db.session.add(team)
    db.session.commit()

    session['team_id'] = team.id

    from app import socketio
    socketio.emit('team_registered',
                  {'team_id': team.id, 'name': team.name},
                  room=quiz_id)

    resp = redirect(url_for('participant.play_quiz', quiz_id=quiz_id))
    resp.set_cookie('session_token', token, max_age=60*60*24*30)
    return resp


@participant_bp.route('/play/submit', methods=['POST'])
def submit_answer():
    data = request.json or {}
    team = _get_team()
    if not team:
        return jsonify({'error': 'Not registered'}), 403

    question_id = data.get('question_id')
    question = Question.query.get_or_404(question_id)

    # Check if timer is still running
    gs = GameState.query.filter_by(quiz_id=team.quiz_id).first()
    if not gs or gs.current_question_id != question_id:
        return jsonify({'error': 'Question not active'}), 400

    if gs.timer_started_at and gs.timer_seconds:
        elapsed = (datetime.utcnow() - gs.timer_started_at).total_seconds()
        if elapsed > gs.timer_seconds:
            return jsonify({'error': 'Time is up'}), 400

    # Upsert answer
    answer = TeamAnswer.query.filter_by(team_id=team.id, question_id=question_id).first()
    if not answer:
        answer = TeamAnswer(team_id=team.id, question_id=question_id)
        db.session.add(answer)

    answer.submitted_at = datetime.utcnow()

    if question.answer_type in ('single_choice', 'multiple_choice'):
        answer.selected_options = data.get('selected_options', [])
        answer.answer_text = None
    elif question.answer_type == 'matching':
        answer.matching_pairs = data.get('matching_pairs', [])
        answer.answer_text = None
    else:
        answer.answer_text = data.get('answer_text', '')
        answer.selected_options = None

    # Auto-check
    if question.auto_check and question.answer_type in ('single_choice', 'multiple_choice'):
        from app.models import AnswerOption
        correct_ids = {o.id for o in question.answer_options if o.is_correct}
        submitted = set(answer.selected_options or [])
        answer.is_correct = submitted == correct_ids
        answer.score = question.points if answer.is_correct else 0
        answer.auto_checked = True
    else:
        answer.is_correct = None
        answer.score = 0
        answer.auto_checked = False

    db.session.commit()

    from app import socketio
    socketio.emit('answer_submitted',
                  {'team_id': team.id, 'question_id': question_id},
                  room=team.quiz_id)

    return jsonify({'ok': True, 'is_correct': answer.is_correct, 'score': answer.score})
