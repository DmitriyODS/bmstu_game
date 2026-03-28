from flask import Blueprint

presentation_bp = Blueprint('presentation', __name__, template_folder='templates')

from app.presentation import routes  # noqa
