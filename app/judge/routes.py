from datetime import datetime, timedelta
from flask import render_template, jsonify, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.judge import judge_bp
from app.judge.locks import (
    release_stale_locks,
    MAX_LOCK_LIFETIME_SECONDS,
)
from app.auth import judge_required
from app.models import db, Quiz, Tour, Question, Team, TeamAnswer, GameState, AnswerOption, MatchingItem


@judge_bp.route('/')
@judge_required
def index():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return render_template('judge/no_quiz.html')
    tours = quiz.tours
    tours_data = []
    tour_num = 0
    for t in tours:
        if t.is_slide:
            continue
        tour_num += 1
        tours_data.append({
            'id': t.id,
            'title': t.title,
            'num': tour_num,
            'questions': [
                {'id': q.id, 'text': (q.text or '')[:80], 'num': idx + 1}
                for idx, q in enumerate(t.questions)
            ]
        })
    return render_template('judge/judge.html', quiz=quiz, tours=tours, tours_data=tours_data)


@judge_bp.route('/next-card')
@judge_required
def next_card():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return jsonify({'answer': None})

    tour_id = request.args.get('tour_id')
    question_id = request.args.get('question_id')

    # Release this judge's own pending locks (refresh / new card without judging).
    # Делаем отдельный commit, чтобы освобождение стало видно другим транзакциям
    # немедленно — иначе параллельный SELECT FOR UPDATE SKIP LOCKED у другого
    # судьи не увидит освобождённую строку до конца нашей транзакции.
    n = TeamAnswer.query.filter(
        TeamAnswer.checked_by == current_user.id,
        TeamAnswer.is_correct.is_(None),
    ).update({'checked_by': None,
              'checked_by_at': None,
              'checked_lock_started_at': None},
             synchronize_session=False)
    if n:
        db.session.commit()
    else:
        db.session.rollback()

    # Заодно пробежимся по всем протухшим — на случай если фоновой sweeper
    # ещё не добежал до этого тика.
    release_stale_locks()

    # Атомарный захват: SELECT ... FOR UPDATE SKIP LOCKED — если строка уже
    # захвачена параллельной транзакцией (другим судьёй), пропускаем её.
    q = (TeamAnswer.query
         .join(Question).join(Tour)
         .filter(
             Tour.quiz_id == quiz.id,
             TeamAnswer.is_correct.is_(None),
             TeamAnswer.checked_by.is_(None),
         )
         .order_by(TeamAnswer.submitted_at)
         .with_for_update(skip_locked=True, of=TeamAnswer))
    if tour_id:
        q = q.filter(Tour.id == tour_id)
    if question_id:
        q = q.filter(TeamAnswer.question_id == question_id)

    answer = q.first()
    if not answer:
        db.session.commit()
        return jsonify({'answer': None})

    now = datetime.utcnow()
    answer.checked_by = current_user.id
    answer.checked_by_at = now
    answer.checked_lock_started_at = now
    db.session.commit()

    # После коммита подгружаем связи для рендера (вне FOR UPDATE-транзакции).
    answer = (TeamAnswer.query
              .options(
                  joinedload(TeamAnswer.question).joinedload(Question.answer_options),
                  joinedload(TeamAnswer.question).joinedload(Question.matching_items),
                  joinedload(TeamAnswer.team),
              )
              .filter(TeamAnswer.id == answer.id)
              .first())

    return jsonify({'answer': _answer_dict(answer, answer.team, answer.question)})


@judge_bp.route('/check/<answer_id>', methods=['POST'])
@judge_required
def check_answer(answer_id):
    answer = TeamAnswer.query.get_or_404(answer_id)
    data = request.json or {}
    is_correct = data.get('is_correct')
    score = data.get('score')

    # Защита от перезаписи чужого результата: разрешаем оценивать только если
    # карточка либо ещё за нами (нормальный путь), либо вообще никем не проверена
    # и не заблокирована (карточку у нас увели по таймауту, но никто ещё не успел
    # её оценить — позволяем сохранить результат, чтобы ответ не «потерялся»).
    # Принудительная переоценка из режима таблицы — отдельный кейс ниже.
    force = bool(data.get('force'))
    if not force:
        already_judged_by_other = (
            answer.is_correct is not None
            and answer.checked_by
            and answer.checked_by != current_user.id
        )
        locked_by_other = (
            answer.checked_by is not None
            and answer.checked_by != current_user.id
            and answer.is_correct is None
        )
        if already_judged_by_other or locked_by_other:
            return jsonify({
                'ok': False,
                'error': 'taken_by_other',
                'is_correct': answer.is_correct,
                'score': answer.score,
            }), 409

    answer.is_correct = bool(is_correct) if is_correct is not None else None
    if score is not None and score != '':
        try:
            answer.score = max(0, int(score))
        except (TypeError, ValueError):
            question = answer.question
            answer.score = question.points if is_correct else 0
    else:
        question = answer.question
        answer.score = question.points if is_correct else 0
    answer.auto_checked = False
    answer.checked_by = current_user.id
    answer.checked_by_at = datetime.utcnow()
    # После оценки lock-started уже не нужен — обнуляем, чтобы счётчик начался
    # заново при ручной переоценке через таблицу.
    answer.checked_lock_started_at = None
    db.session.commit()

    from app import socketio
    from app.sockets.utils import broadcast
    quiz = Quiz.query.filter_by(is_active=True).first()
    if quiz:
        broadcast('answer_checked',
                  {'answer_id': answer.id, 'is_correct': answer.is_correct, 'score': answer.score},
                  quiz.id)
        _emit_scores(socketio, quiz)

    return jsonify({'ok': True, 'is_correct': answer.is_correct, 'score': answer.score})


@judge_bp.route('/heartbeat/<answer_id>', methods=['POST'])
@judge_required
def heartbeat(answer_id):
    """Frontend periodically pings — keeps the lock fresh while the card is on screen.
    Возвращает ok=false, если карточка больше не наша (упёрлись в потолок жизни
    блокировки или её увели). Фронт по этому сигналу подгружает следующую."""
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=MAX_LOCK_LIFETIME_SECONDS)
    updated = (TeamAnswer.query
               .filter(TeamAnswer.id == answer_id,
                       TeamAnswer.checked_by == current_user.id,
                       TeamAnswer.is_correct.is_(None),
                       db.or_(
                           TeamAnswer.checked_lock_started_at.is_(None),
                           TeamAnswer.checked_lock_started_at >= cutoff,
                       ))
               .update({'checked_by_at': now},
                       synchronize_session=False))
    db.session.commit()
    return jsonify({'ok': bool(updated)})


@judge_bp.route('/release/<answer_id>', methods=['POST'])
@judge_required
def release_card(answer_id):
    """Явное освобождение карточки судьёй (закрытие вкладки, переключение режима,
    уход на другую вкладку). Снимаем блокировку только если она ещё за нами и
    карточка не оценена — чужие/уже проверенные не трогаем."""
    (TeamAnswer.query
     .filter(TeamAnswer.id == answer_id,
             TeamAnswer.checked_by == current_user.id,
             TeamAnswer.is_correct.is_(None))
     .update({'checked_by': None,
              'checked_by_at': None,
              'checked_lock_started_at': None},
             synchronize_session=False))
    db.session.commit()
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

    q = (TeamAnswer.query
         .join(Question).join(Tour)
         .options(
             joinedload(TeamAnswer.question).joinedload(Question.answer_options),
             joinedload(TeamAnswer.question).joinedload(Question.matching_items),
             joinedload(TeamAnswer.team),
         )
         .filter(Tour.quiz_id == quiz.id)
         .order_by(TeamAnswer.submitted_at.desc()))
    if tour_id:
        q = q.filter(Tour.id == tour_id)
    if question_id:
        q = q.filter(TeamAnswer.question_id == question_id)
    if only_unchecked:
        q = q.filter(TeamAnswer.is_correct.is_(None))

    answers = q.all()
    result = [_answer_dict(ans, ans.team, ans.question) for ans in answers]
    return jsonify({'answers': result})


@judge_bp.route('/results')
@judge_required
def results():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return jsonify({'tours': [], 'total': []})

    teams = Team.query.filter_by(quiz_id=quiz.id).order_by(Team.name).all()
    team_map = {t.id: t.name for t in teams}

    tours_result = []
    total_scores = {t.id: 0 for t in teams}

    regular_tours = [t for t in quiz.tours if not t.is_slide]
    for tour_num, tour in enumerate(regular_tours, 1):
        q_ids = {q.id for q in tour.questions}
        answers = (TeamAnswer.query
                   .filter(TeamAnswer.question_id.in_(q_ids))
                   .all()) if q_ids else []

        team_scores = {t.id: 0 for t in teams}
        for ans in answers:
            if ans.score:
                team_scores[ans.team_id] = team_scores.get(ans.team_id, 0) + ans.score
                total_scores[ans.team_id] = total_scores.get(ans.team_id, 0) + ans.score

        rows = sorted(
            [{'team_id': tid, 'team_name': team_map.get(tid, '?'), 'score': sc}
             for tid, sc in team_scores.items()],
            key=lambda x: -x['score']
        )
        for i, r in enumerate(rows):
            r['place'] = i + 1

        tours_result.append({'tour_num': tour_num, 'tour_title': tour.title, 'scores': rows})

    total_rows = sorted(
        [{'team_id': tid, 'team_name': team_map.get(tid, '?'), 'score': sc}
         for tid, sc in total_scores.items()],
        key=lambda x: -x['score']
    )
    for i, r in enumerate(total_rows):
        r['place'] = i + 1

    return jsonify({'tours': tours_result, 'total': total_rows})


def _answer_dict(answer, team, question):
    answer_display = (answer.answer_text or '').strip() or None
    correct_pairs_correct = None  # для matching — сравним с пользовательскими

    if question.answer_type in ('single_choice', 'multiple_choice'):
        opts_by_id = {o.id: o for o in question.answer_options}
        chosen_ids = answer.selected_options or []
        chosen = [opts_by_id[i] for i in chosen_ids if i in opts_by_id]
        # сохраняем порядок как в БД для стабильного отображения
        chosen.sort(key=lambda o: o.order)
        answer_display = ', '.join(o.text for o in chosen) if chosen else None

    elif question.answer_type == 'matching':
        items_by_id = {m.id: m for m in question.matching_items}
        pairs = answer.matching_pairs or []
        rendered = []
        for pair in pairs:
            left = items_by_id.get((pair or {}).get('left_id'))
            right = items_by_id.get((pair or {}).get('right_id'))
            if left and right:
                rendered.append({
                    'left_text': left.left_text,
                    'right_text': right.right_text,
                    'is_correct': left.id == right.id,
                })
        if rendered:
            answer_display = '; '.join(
                f"{p['left_text']} → {p['right_text']}" for p in rendered
            )
        correct_pairs_correct = rendered

    # Правильный ответ — человекочитаемое представление
    correct_pairs = None
    if question.answer_type in ('single_choice', 'multiple_choice'):
        correct_display = ', '.join(
            o.text for o in question.answer_options if o.is_correct
        ) or (question.correct_answer or '—')
    elif question.answer_type == 'matching':
        sorted_items = sorted(question.matching_items, key=lambda x: x.order)
        correct_pairs = [{'left_text': m.left_text, 'right_text': m.right_text}
                         for m in sorted_items]
        correct_display = '; '.join(
            f"{m.left_text} → {m.right_text}" for m in sorted_items
        ) or (question.correct_answer or '—')
    else:
        correct_display = question.correct_answer or '—'

    return {
        'id': answer.id,
        'team_id': answer.team_id,
        'team_name': team.name if team else '?',
        'question_id': answer.question_id,
        'question_text': question.text or '',
        'question_text_short': (question.text or '')[:80],
        'question_points': question.points,
        'answer_type': question.answer_type,
        'answer_text': answer.answer_text,
        'selected_options': answer.selected_options,
        'matching_pairs': answer.matching_pairs,
        'matching_rendered': correct_pairs_correct,
        'correct_pairs': correct_pairs,
        'answer_display': answer_display or '(пусто)',
        'correct_display': correct_display,
        'correct_answer': correct_display,  # для совместимости со старыми шаблонами
        'is_correct': answer.is_correct,
        'score': answer.score,
        'auto_checked': answer.auto_checked,
        'submitted_at': str(answer.submitted_at),
    }


def _emit_scores(socketio, quiz):
    rows = (db.session.query(
                Team.id, Team.name,
                db.func.coalesce(db.func.sum(TeamAnswer.score), 0))
            .outerjoin(TeamAnswer, TeamAnswer.team_id == Team.id)
            .filter(Team.quiz_id == quiz.id)
            .group_by(Team.id, Team.name)
            .all())
    scores = [{'team_id': tid, 'team_name': name, 'score': int(score or 0)}
              for tid, name, score in rows]
    scores.sort(key=lambda x: -x['score'])
    for i, s in enumerate(scores):
        s['place'] = i + 1
    from app.sockets.utils import broadcast
    broadcast('scores_updated', {'scores': scores}, quiz.id)
