ALTER TABLE tours
    ADD COLUMN IF NOT EXISTS sound_start_path VARCHAR(512),
    ADD COLUMN IF NOT EXISTS sound_mid_path VARCHAR(512),
    ADD COLUMN IF NOT EXISTS sound_mid_seconds INT,
    ADD COLUMN IF NOT EXISTS sound_end_path VARCHAR(512);

ALTER TABLE questions
    DROP COLUMN IF EXISTS sound_start_path,
    DROP COLUMN IF EXISTS sound_mid_path,
    DROP COLUMN IF EXISTS sound_mid_seconds,
    DROP COLUMN IF EXISTS sound_end_path;
