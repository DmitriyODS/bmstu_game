import os
from flask import Flask, redirect, url_for
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

socketio = SocketIO()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'postgresql://quiz:quiz@db:5432/quiz'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = int(
        os.environ.get('MAX_CONTENT_LENGTH', 52428800)
    )

    from app.models import db
    db.init_app(app)

    from app.auth import init_login
    init_login(app)

    socketio.init_app(app, cors_allowed_origins='*', async_mode='eventlet')

    # Blueprints
    from app.auth_routes import auth_bp
    app.register_blueprint(auth_bp)

    from app.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.judge import judge_bp
    app.register_blueprint(judge_bp, url_prefix='/judge')

    from app.participant import participant_bp
    app.register_blueprint(participant_bp)

    from app.presentation import presentation_bp
    app.register_blueprint(presentation_bp)

    # Register socket handlers
    from app.sockets import admin as admin_sockets  # noqa
    from app.sockets import judge as judge_sockets  # noqa
    from app.sockets import participant as participant_sockets  # noqa
    from app.sockets import presentation as presentation_sockets  # noqa

    @app.route('/')
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            if current_user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('judge.index'))
        return redirect(url_for('auth.login'))

    with app.app_context():
        _init_db(app)

    return app


def _init_db(app):
    from app.models import db, User
    import os

    db.create_all()

    # Create default admin if not exists
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', role='admin')
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin'))
        db.session.add(admin)
        db.session.commit()
