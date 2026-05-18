ALTER TABLE questions
    ADD COLUMN IF NOT EXISTS answer_audio_path VARCHAR(512),
    ADD COLUMN IF NOT EXISTS answer_audio_original_name VARCHAR(512);
