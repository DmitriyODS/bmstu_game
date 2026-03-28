from flask import Blueprint

participant_bp = Blueprint('participant', __name__, template_folder='templates')

from app.participant import routes  # noqa
