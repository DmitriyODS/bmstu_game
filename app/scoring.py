def rank_scores(rows):
    """Сортирует [{'team_name', 'score', ...}] по убыванию баллов и проставляет place.
    Команды с равными баллами делят место (1, 2, 2, 4)."""
    rows.sort(key=lambda r: (-r['score'], r.get('team_name') or ''))
    for i, r in enumerate(rows):
        if i > 0 and r['score'] == rows[i - 1]['score']:
            r['place'] = rows[i - 1]['place']
        else:
            r['place'] = i + 1
    return rows


def matching_token(item_id):
    """Непрозрачный id правой части пары. Пока ответ не показан, участники не должны
    видеть, какая правая часть принадлежит какой левой (у них общий MatchingItem.id)."""
    import hashlib
    import hmac
    from flask import current_app
    key = current_app.config['SECRET_KEY'].encode()
    return 'r' + hmac.new(key, item_id.encode(), hashlib.sha256).hexdigest()[:16]


ANSWER_TYPE_LABELS = {
    'single_choice': 'Один вариант',
    'multiple_choice': 'Несколько вариантов',
    'short_text': 'Короткий текст',
    'long_text': 'Длинный текст',
    'matching': 'Сопоставление',
}


def question_stats(quiz):
    """Статистика по каждому вопросу квиза (слайды пропускаются)."""
    from app.models import db, Team, TeamAnswer, Tour, Question

    agg = {
        qid: (total, checked, correct, score_sum)
        for qid, total, checked, correct, score_sum in (
            db.session.query(
                TeamAnswer.question_id,
                db.func.count(TeamAnswer.id),
                db.func.count(TeamAnswer.is_correct),
                db.func.count(db.case((TeamAnswer.is_correct.is_(True), 1))),
                db.func.coalesce(db.func.sum(TeamAnswer.score), 0),
            )
            .join(Question, Question.id == TeamAnswer.question_id)
            .join(Tour, Tour.id == Question.tour_id)
            .filter(Tour.quiz_id == quiz.id)
            .group_by(TeamAnswer.question_id)
            .all()
        )
    }
    teams_count = Team.query.filter_by(quiz_id=quiz.id).count()

    rows = []
    tour_num = 0
    for tour in quiz.tours:
        if tour.is_slide:
            continue
        tour_num += 1
        for q_num, q in enumerate(tour.questions, 1):
            total, checked, correct, score_sum = agg.get(q.id, (0, 0, 0, 0))
            rows.append({
                'id': q.id,
                'label': f'Т{tour_num}.В{q_num}',
                'tour_title': tour.title,
                'text': (q.text or '').strip(),
                'answer_type': ANSWER_TYPE_LABELS.get(q.answer_type, q.answer_type),
                'points': q.points,
                'answered': total,
                'not_answered': max(0, teams_count - total),
                'checked': checked,
                'unchecked': total - checked,
                'correct': correct,
                # Доля верных среди проверенных — непроверенные не тянут её вниз.
                'correct_pct': round(100 * correct / checked) if checked else None,
                'avg_score': round(score_sum / total, 2) if total else None,
            })
    return rows, teams_count
