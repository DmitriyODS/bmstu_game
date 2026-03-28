CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'judge'
);

CREATE TABLE IF NOT EXISTS quizzes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(256) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tours (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    title VARCHAR(256) NOT NULL,
    "order" INT NOT NULL DEFAULT 0,
    splash_image VARCHAR(512)
);

CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tour_id UUID NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    "order" INT NOT NULL DEFAULT 0,
    question_type VARCHAR(16) NOT NULL DEFAULT 'text',
    answer_type VARCHAR(16) NOT NULL DEFAULT 'short_text',
    text TEXT,
    image_path VARCHAR(512),
    audio_path VARCHAR(512),
    time_seconds INT NOT NULL DEFAULT 60,
    points INT NOT NULL DEFAULT 1,
    auto_check BOOLEAN NOT NULL DEFAULT FALSE,
    correct_answer TEXT,
    sound_start_path VARCHAR(512),
    sound_mid_path VARCHAR(512),
    sound_mid_seconds INT,
    sound_end_path VARCHAR(512)
);

CREATE TABLE IF NOT EXISTS answer_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    text VARCHAR(512) NOT NULL,
    is_correct BOOLEAN NOT NULL DEFAULT FALSE,
    "order" INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS matching_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    left_text VARCHAR(512) NOT NULL,
    right_text VARCHAR(512) NOT NULL,
    "order" INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS teams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    name VARCHAR(256) NOT NULL,
    session_token VARCHAR(128) UNIQUE NOT NULL,
    registered_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS team_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    answer_text TEXT,
    selected_options JSONB,
    matching_pairs JSONB,
    submitted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    is_correct BOOLEAN,
    score INT NOT NULL DEFAULT 0,
    auto_checked BOOLEAN NOT NULL DEFAULT FALSE,
    checked_by UUID REFERENCES users(id) ON DELETE SET NULL,
    checked_by_at TIMESTAMP,
    UNIQUE(team_id, question_id)
);

CREATE TABLE IF NOT EXISTS game_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quiz_id UUID REFERENCES quizzes(id) ON DELETE CASCADE,
    current_screen VARCHAR(32) NOT NULL DEFAULT 'splash',
    current_tour_id UUID REFERENCES tours(id) ON DELETE SET NULL,
    current_question_id UUID REFERENCES questions(id) ON DELETE SET NULL,
    timer_started_at TIMESTAMP,
    timer_seconds INT,
    registration_open BOOLEAN NOT NULL DEFAULT FALSE
);
