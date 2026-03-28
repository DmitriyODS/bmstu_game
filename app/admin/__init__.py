from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='templates')

from app.admin import routes  # noqa


@admin_bp.context_processor
def inject_active_quiz():
    from app.models import Quiz
    active_quiz = Quiz.query.filter_by(is_active=True).first()
    return {'active_quiz': active_quiz}
