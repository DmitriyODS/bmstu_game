-- Add audio trim fields and original filename for questions
ALTER TABLE questions
    ADD COLUMN IF NOT EXISTS audio_original_name VARCHAR(512),
    ADD COLUMN IF NOT EXISTS audio_trim_start FLOAT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS audio_trim_end FLOAT;
