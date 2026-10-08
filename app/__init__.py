import os
from flask import Flask, redirect, url_for
from flask_socketio import SocketIO
from dotenv import load_dotenv

load_dotenv()

socketio = SocketIO()


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    if app.config['SECRET_KEY'] in ('dev-secret-key', 'change-me-to-random-secret'):
        app.logger.warning('SECRET_KEY не задан: сессии админа и судей можно подделать. '
                           'Укажите случайный SECRET_KEY в .env')
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # COOKIE_SECURE=1 на проде за HTTPS: cookie не уходят по незашифрованному HTTP.
    secure_cookies = os.environ.get('COOKIE_SECURE') == '1'
    app.config['SESSION_COOKIE_SECURE'] = secure_cookies
    app.config['REMEMBER_COOKIE_SECURE'] = secure_cookies
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 'postgresql://quiz:quiz@db:5432/quiz'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = int(
        os.environ.get('MAX_CONTENT_LENGTH', 52428800)
    )

    # За nginx/реверс-прокси: доверяем X-Forwarded-* (схема, хост), иначе
    # QR-код и редиректы строятся на внутренний адрес контейнера.
    if os.environ.get('TRUST_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    from app.models import db
    db.init_app(app)

    from app.auth import init_login
    init_login(app)

    from app.csrf import init_csrf
    init_csrf(app)

    # На проде — только свой домен (SOCKETIO_CORS_ORIGINS=https://...), чтобы чужой
    # сайт не мог открыть сокет от имени залогиненного админа/судьи.
    cors = os.environ.get('SOCKETIO_CORS_ORIGINS', '*')
    socketio.init_app(app, async_mode='eventlet',
                      cors_allowed_origins=cors if cors == '*' else cors.split(','))

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

    # Фоновой sweeper отпускает протухшие блокировки судей независимо от
    # того, дёргает ли кто-нибудь /judge/next-card.
    from app.judge.locks import start_sweeper
    start_sweeper(app)

    from app.sockets.admin import resume_running_timer
    resume_running_timer(app)

    return app


def _init_db(app):
    from app.models import db, User
    import os
    from sqlalchemy import text

    db.create_all()

    # Apply SQL migrations in order
    with db.engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename VARCHAR(256) PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.commit()

        migrations_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith('.sql'):
                continue
            row = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE filename = :f"),
                {'f': filename}
            ).fetchone()
            if row:
                continue
            with open(os.path.join(migrations_dir, filename), 'r') as f:
                sql = f.read()
            for stmt in sql.split(';'):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {'f': filename}
            )
            conn.commit()

    # Create default admin if not exists
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin = User.query.filter_by(username=admin_username).first()
    if not admin:
        admin = User(username=admin_username, role='admin')
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin'))
        db.session.add(admin)
        db.session.commit()


def public_base_url():
    """Адрес, по которому участники открывают игру (для QR). PUBLIC_BASE_URL
    нужен, когда ведущий открывает админку по localhost, а телефоны — по IP/домену."""
    from flask import request
    return (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')
