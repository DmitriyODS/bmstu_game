"""Минимальная CSRF-защита без внешних зависимостей.

Токен живёт в Flask-сессии; base.html кладёт его в <meta name="csrf-token">,
а общий JS сам добавляет его в fetch (заголовок X-CSRFToken) и в POST-формы
(поле csrf_token). Socket.IO сюда не попадает — его обслуживает engineio.
"""
import hmac
import secrets

from flask import session, request, jsonify, flash, redirect

_SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


def csrf_token():
    token = session.get('_csrf')
    if not token:
        token = session['_csrf'] = secrets.token_urlsafe(32)
    return token


def init_csrf(app):
    app.config.setdefault('CSRF_ENABLED', True)
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def _check_csrf():
        if request.method in _SAFE_METHODS or not app.config['CSRF_ENABLED']:
            return None
        sent = (request.headers.get('X-CSRFToken')
                or request.form.get('csrf_token')
                or request.args.get('csrf_token'))
        expected = session.get('_csrf')
        if expected and sent and hmac.compare_digest(sent, expected):
            return None
        if request.headers.get('X-CSRFToken') is not None or request.is_json:
            return jsonify({'error': 'csrf', 'message': 'Сессия устарела — обновите страницу'}), 400
        flash('Сессия устарела — повторите действие', 'warning')
        return redirect(request.referrer or '/')
