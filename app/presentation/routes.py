import io
from flask import render_template, redirect, url_for, send_file
from app.presentation import presentation_bp
from app.models import Quiz, GameState, Team


@presentation_bp.route('/screen')
def screen():
    quiz = Quiz.query.filter_by(is_active=True).first()
    if not quiz:
        return render_template('presentation/no_quiz.html')
    gs = GameState.query.filter_by(quiz_id=quiz.id).first()
    teams = Team.query.filter_by(quiz_id=quiz.id).order_by(Team.registered_at).all()
    from app import public_base_url
    # Короткий адрес для ручного ввода: /play сам перенаправит на активный квиз.
    join_url = public_base_url().split('://', 1)[-1] + '/play'
    return render_template('presentation/screen.html', quiz=quiz, gs=gs, teams=teams,
                           join_url=join_url)


@presentation_bp.route('/api/qr/<quiz_id>')
def qr_code(quiz_id):
    import qrcode
    from flask import request
    from app import public_base_url
    base_url = public_base_url()
    url = f"{base_url}/play/{quiz_id}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')
