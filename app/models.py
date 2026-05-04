import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def gen_uuid():
    return str(uuid.uuid4())


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='judge')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Quiz(db.Model):
    __tablename__ = 'quizzes'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    title = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text)
    splash_image = db.Column(db.String(512))
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(16), nullable=False, default='draft')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sound_start_path = db.Column(db.String(512))
    sound_mid_path = db.Column(db.String(512))
    sound_mid_seconds = db.Column(db.Integer)
    sound_end_path = db.Column(db.String(512))

    tours = db.relationship('Tour', backref='quiz', cascade='all, delete-orphan',
                            order_by='Tour.order')
    teams = db.relationship('Team', backref='quiz', cascade='all, delete-orphan')
    game_state = db.relationship('GameState', backref='quiz', uselist=False,
                                  cascade='all, delete-orphan')


class Tour(db.Model):
    __tablename__ = 'tours'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    quiz_id = db.Column(db.String(36), db.ForeignKey('quizzes.id'), nullable=False)
    title = db.Column(db.String(256), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    splash_image = db.Column(db.String(512))

    is_slide = db.Column(db.Boolean, nullable=False, default=False)
    slide_text = db.Column(db.Text)
    slide_audio_path = db.Column(db.String(512))
    slide_audio_original_name = db.Column(db.String(512))

    questions = db.relationship('Question', backref='tour', cascade='all, delete-orphan',
                                 order_by='Question.order')


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    tour_id = db.Column(db.String(36), db.ForeignKey('tours.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)
    question_type = db.Column(db.String(16), nullable=False, default='text')
    answer_type = db.Column(db.String(16), nullable=False, default='short_text')
    text = db.Column(db.Text)
    image_path = db.Column(db.String(512))
    audio_path = db.Column(db.String(512))
    audio_original_name = db.Column(db.String(512))
    audio_trim_start = db.Column(db.Float, nullable=False, default=0.0)
    audio_trim_end = db.Column(db.Float)
    time_seconds = db.Column(db.Integer, nullable=False, default=60)
    points = db.Column(db.Integer, nullable=False, default=1)
    auto_check = db.Column(db.Boolean, nullable=False, default=False)
    correct_answer = db.Column(db.Text)

    answer_options = db.relationship('AnswerOption', backref='question',
                                      cascade='all, delete-orphan',
                                      order_by='AnswerOption.order')
    matching_items = db.relationship('MatchingItem', backref='question',
                                      cascade='all, delete-orphan',
                                      order_by='MatchingItem.order')


class AnswerOption(db.Model):
    __tablename__ = 'answer_options'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    question_id = db.Column(db.String(36), db.ForeignKey('questions.id'), nullable=False)
    text = db.Column(db.String(512), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    order = db.Column(db.Integer, nullable=False, default=0)


class MatchingItem(db.Model):
    __tablename__ = 'matching_items'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    question_id = db.Column(db.String(36), db.ForeignKey('questions.id'), nullable=False)
    left_text = db.Column(db.String(512), nullable=False)
    right_text = db.Column(db.String(512), nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    quiz_id = db.Column(db.String(36), db.ForeignKey('quizzes.id'), nullable=False)
    name = db.Column(db.String(256), nullable=False)
    session_token = db.Column(db.String(128), unique=True, nullable=False)
    registered_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    answers = db.relationship('TeamAnswer', backref='team', cascade='all, delete-orphan')


class TeamAnswer(db.Model):
    __tablename__ = 'team_answers'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    team_id = db.Column(db.String(36), db.ForeignKey('teams.id'), nullable=False)
    question_id = db.Column(db.String(36), db.ForeignKey('questions.id'), nullable=False)
    answer_text = db.Column(db.Text)
    selected_options = db.Column(db.JSON)
    matching_pairs = db.Column(db.JSON)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_correct = db.Column(db.Boolean)
    score = db.Column(db.Integer, nullable=False, default=0)
    auto_checked = db.Column(db.Boolean, nullable=False, default=False)
    checked_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    checked_by_at = db.Column(db.DateTime)

    question = db.relationship('Question', backref='answers')
    checker = db.relationship('User', foreign_keys=[checked_by])

    __table_args__ = (
        db.UniqueConstraint('team_id', 'question_id', name='uq_team_question'),
    )


class GameState(db.Model):
    __tablename__ = 'game_states'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    quiz_id = db.Column(db.String(36), db.ForeignKey('quizzes.id'))
    current_screen = db.Column(db.String(32), nullable=False, default='splash')
    current_tour_id = db.Column(db.String(36), db.ForeignKey('tours.id'), nullable=True)
    current_question_id = db.Column(db.String(36), db.ForeignKey('questions.id'), nullable=True)
    timer_started_at = db.Column(db.DateTime, nullable=True)
    timer_seconds = db.Column(db.Integer, nullable=True)
    registration_open = db.Column(db.Boolean, nullable=False, default=False)

    current_tour = db.relationship('Tour', foreign_keys=[current_tour_id])
    current_question = db.relationship('Question', foreign_keys=[current_question_id])
