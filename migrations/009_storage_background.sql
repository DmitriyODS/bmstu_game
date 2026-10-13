-- Хранилище файлов: папки и реестр файлов (локальный диск или S3)
CREATE TABLE IF NOT EXISTS storage_folders (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    quiz_id VARCHAR(36) REFERENCES quizzes(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stored_files (
    id VARCHAR(36) PRIMARY KEY,
    folder_id VARCHAR(36) REFERENCES storage_folders(id) ON DELETE SET NULL,
    kind VARCHAR(8) NOT NULL,
    original_name VARCHAR(512) NOT NULL,
    storage_key VARCHAR(512) NOT NULL UNIQUE,
    size BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Фон слайдов квиза (презентация и экран участника)
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_type VARCHAR(8) NOT NULL DEFAULT 'none';
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_color VARCHAR(7);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_image VARCHAR(512);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_opacity INTEGER NOT NULL DEFAULT 100;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_blur INTEGER NOT NULL DEFAULT 0;
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS bg_text_light BOOLEAN NOT NULL DEFAULT FALSE;
