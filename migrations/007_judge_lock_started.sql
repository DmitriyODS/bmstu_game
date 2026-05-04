-- Жёсткий потолок жизни блокировки судьи: фиксируем момент ПЕРВОГО захвата
-- отдельно от checked_by_at (последний heartbeat). Это позволяет освобождать
-- карточки, на которых судья «висит» вечно за счёт активного heartbeat.
ALTER TABLE team_answers
    ADD COLUMN IF NOT EXISTS checked_lock_started_at TIMESTAMP;

-- Бэкфилл: для уже захваченных, но ещё не проверенных строк считаем, что
-- блокировка стартовала тогда же, когда последний heartbeat — sweeper её
-- освободит за пределами обычного 30-секундного окна.
UPDATE team_answers
   SET checked_lock_started_at = checked_by_at
 WHERE checked_by IS NOT NULL
   AND is_correct IS NULL
   AND checked_lock_started_at IS NULL;
