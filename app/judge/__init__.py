from flask import Blueprint

judge_bp = Blueprint('judge', __name__, template_folder='templates')

from app.judge import routes  # noqa
