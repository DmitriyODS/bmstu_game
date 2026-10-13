from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='templates')

from app.admin import routes  # noqa
from app.admin import files  # noqa


@admin_bp.context_processor
def inject_active_quiz():
    from app.models import Quiz
    active_quiz = Quiz.query.filter_by(is_active=True).first()
    # Квиз, на примере которого ознакомительный тур показывает конструктор.
    tour_quiz = active_quiz or Quiz.query.order_by(Quiz.created_at.desc()).first()
    from app.storage import storage_full
    return {'active_quiz': active_quiz, 'tour_quiz': tour_quiz, 'storage_full': storage_full()}
