from functools import wraps
from flask import redirect, url_for, flash
from flask_login import LoginManager, current_user

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Необходима авторизация'
login_manager.login_message_category = 'warning'


def init_login(app):
    login_manager.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Доступ запрещён', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def judge_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('admin', 'judge'):
            flash('Доступ запрещён', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated
