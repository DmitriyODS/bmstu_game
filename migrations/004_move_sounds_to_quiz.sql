-- Move sound settings from tours to quizzes (quiz-level global sounds)
ALTER TABLE quizzes
    ADD COLUMN IF NOT EXISTS sound_start_path VARCHAR(512),
    ADD COLUMN IF NOT EXISTS sound_mid_path VARCHAR(512),
    ADD COLUMN IF NOT EXISTS sound_mid_seconds INT,
    ADD COLUMN IF NOT EXISTS sound_end_path VARCHAR(512);

ALTER TABLE tours
    DROP COLUMN IF EXISTS sound_start_path,
    DROP COLUMN IF EXISTS sound_mid_path,
    DROP COLUMN IF EXISTS sound_mid_seconds,
    DROP COLUMN IF EXISTS sound_end_path;
