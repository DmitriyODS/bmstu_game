from datetime import datetime, timedelta
from flask import render_template, jsonify, request
from flask_login import current_user
from app.judge import judge_bp
from app.auth import judge_required
from app.models import db, Quiz, Tour, Question, Team, TeamAnswer, GameState


@judge_bp.route('/')
@judge_required
def index():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return render_template('judge/no_quiz.html')
    tours = quiz.tours
    return render_template('judge/judge.html', quiz=quiz, tours=tours)


@judge_bp.route('/next-card')
@judge_required
def next_card():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return jsonify({'answer': None})

    tour_id = request.args.get('tour_id')
    question_id = request.args.get('question_id')

    # Release timed-out locks (60s)
    timeout = datetime.utcnow() - timedelta(seconds=60)
    TeamAnswer.query.filter(
        TeamAnswer.checked_by.isnot(None),
        TeamAnswer.checked_by_at < timeout
    ).update({'checked_by': None, 'checked_by_at': None})
    db.session.flush()

    q = TeamAnswer.query.join(Question).join(Tour).filter(
        Tour.quiz_id == quiz.id,
        TeamAnswer.is_correct.is_(None),
        TeamAnswer.checked_by.is_(None),
    )
    if tour_id:
        q = q.filter(Tour.id == tour_id)
    if question_id:
        q = q.filter(TeamAnswer.question_id == question_id)

    answer = q.first()
    if not answer:
        db.session.commit()
        return jsonify({'answer': None})

    answer.checked_by = current_user.id
    answer.checked_by_at = datetime.utcnow()
    db.session.commit()

    team = Team.query.get(answer.team_id)
    question = answer.question
    return jsonify({'answer': _answer_dict(answer, team, question)})


@judge_bp.route('/check/<answer_id>', methods=['POST'])
@judge_required
def check_answer(answer_id):
    answer = TeamAnswer.query.get_or_404(answer_id)
    data = request.json or {}
    is_correct = data.get('is_correct')
    score = data.get('score')

    answer.is_correct = is_correct
    if score is not None:
        answer.score = int(score)
    else:
        question = answer.question
        answer.score = question.points if is_correct else 0
    answer.checked_by = current_user.id
    answer.checked_by_at = datetime.utcnow()
    db.session.commit()

    from app import socketio
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        socketio.emit('answer_checked',
                      {'answer_id': answer.id, 'is_correct': is_correct, 'score': answer.score},
                      room=quiz.id)
        _emit_scores(socketio, quiz)

    return jsonify({'ok': True})


@judge_bp.route('/answers')
@judge_required
def answers_table():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return jsonify({'answers': []})

    tour_id = request.args.get('tour_id')
    question_id = request.args.get('question_id')
    only_unchecked = request.args.get('unchecked') == '1'

    q = TeamAnswer.query.join(Question).join(Tour).filter(Tour.quiz_id == quiz.id)
    if tour_id:
        q = q.filter(Tour.id == tour_id)
    if question_id:
        q = q.filter(TeamAnswer.question_id == question_id)
    if only_unchecked:
        q = q.filter(TeamAnswer.is_correct.is_(None))

    answers = q.all()
    result = []
    for ans in answers:
        team = Team.query.get(ans.team_id)
        result.append(_answer_dict(ans, team, ans.question))
    return jsonify({'answers': result})


def _answer_dict(answer, team, question):
    answer_display = answer.answer_text
    if answer.selected_options:
        from app.models import AnswerOption
        opts = AnswerOption.query.filter(AnswerOption.id.in_(answer.selected_options)).all()
        answer_display = ', '.join(o.text for o in opts)
    elif answer.matching_pairs:
        answer_display = str(answer.matching_pairs)

    return {
        'id': answer.id,
        'team_id': answer.team_id,
        'team_name': team.name if team else '?',
        'question_id': answer.question_id,
        'question_text': question.text[:80] if question.text else '',
        'question_points': question.points,
        'answer_type': question.answer_type,
        'answer_text': answer.answer_text,
        'selected_options': answer.selected_options,
        'matching_pairs': answer.matching_pairs,
        'answer_display': answer_display,
        'correct_answer': question.correct_answer,
        'is_correct': answer.is_correct,
        'score': answer.score,
        'auto_checked': answer.auto_checked,
        'submitted_at': str(answer.submitted_at),
    }


def _emit_scores(socketio, quiz):
    teams = Team.query.filter_by(quiz_id=quiz.id).all()
    scores = []
    for team in teams:
        total = sum(a.score for a in team.answers if a.score)
        scores.append({'team_id': team.id, 'team_name': team.name, 'score': total})
    from app.sockets.utils import broadcast
    broadcast('scores_updated', {'scores': scores}, quiz.id)
