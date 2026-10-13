"""Хранилище медиафайлов квизов: локальная папка или S3.

В полях квизов лежит адрес вида /static/uploads/<ключ> — он одинаков для обоих
бэкендов, поэтому переезд на S3 не требует правки данных: достаточно перенести
файлы с теми же ключами (flask storage-push-s3).
"""
import io
import mimetypes
import os
import re
import uuid

from flask import Response, abort, current_app, redirect, request, send_from_directory

URL_PREFIX = '/static/uploads/'
IMAGE_EXTS = ('jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'bmp', 'tiff', 'tif')
AUDIO_EXTS = ('mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac')
KIND_DIRS = {'image': 'images', 'audio': 'audio'}
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_SIDE = 3840
DEFAULT_LIMIT_BYTES = 5 * 1024 ** 3
_URL_RE = re.compile(r'/static/uploads/[^\s)"\'<>]+')


class StorageError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ── Бэкенды ────────────────────────────────────────────────────────────────────

class LocalBackend:
    label = 'Локальный диск'

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def _path(self, key):
        path = os.path.realpath(os.path.join(self.root, *key.split('/')))
        if not path.startswith(self.root + os.sep):
            raise StorageError('Недопустимый путь файла')
        return path

    def save(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)

    def read(self, key):
        try:
            with open(self._path(key), 'rb') as f:
                return f.read()
        except OSError:
            return None

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except OSError:
            pass

    def list(self):
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, self.root).replace(os.sep, '/'), os.path.getsize(full)

    def response(self, key):
        return send_from_directory(self.root, key, max_age=7 * 24 * 3600)


class S3Backend:
    label = 'S3'

    def __init__(self, env):
        import boto3
        from botocore.config import Config
        self.bucket = env['S3_BUCKET']
        self.prefix = (env.get('S3_PREFIX') or '').strip('/')
        self.public_url = (env.get('S3_PUBLIC_URL') or '').rstrip('/')
        self.client = boto3.client(
            's3',
            endpoint_url=env.get('S3_ENDPOINT_URL') or None,
            region_name=env.get('S3_REGION') or None,
            aws_access_key_id=env.get('S3_ACCESS_KEY') or None,
            aws_secret_access_key=env.get('S3_SECRET_KEY') or None,
            config=Config(connect_timeout=5, read_timeout=30, retries={'max_attempts': 2}),
        )

    def _key(self, key):
        return f'{self.prefix}/{key}' if self.prefix else key

    def save(self, key, data):
        self.client.put_object(
            Bucket=self.bucket, Key=self._key(key), Body=data,
            ContentType=mimetypes.guess_type(key)[0] or 'application/octet-stream')

    def read(self, key):
        from botocore.exceptions import ClientError
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(key))['Body'].read()
        except ClientError:
            return None

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def list(self):
        skip = len(self.prefix) + 1 if self.prefix else 0
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key('')):
            for obj in page.get('Contents', []):
                yield obj['Key'][skip:], obj['Size']

    def response(self, key):
        # S3_PUBLIC_URL задан — отдаём напрямую из бакета (нужен публичный доступ
        # на чтение и CORS). Иначе проксируем: адрес остаётся своим, CSP и
        # предзагрузка медиа на презентации работают без настройки бакета.
        if self.public_url:
            return redirect(f'{self.public_url}/{self._key(key)}')
        from botocore.exceptions import ClientError
        kwargs = {}
        if request.headers.get('Range'):
            kwargs['Range'] = request.headers['Range']
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(key), **kwargs)
        except ClientError as e:
            code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
            abort(416 if code == 416 else 404)
        headers = {
            'Content-Length': str(obj['ContentLength']),
            'Accept-Ranges': 'bytes',
            'Cache-Control': 'public, max-age=604800',
        }
        if obj.get('ContentRange'):
            headers['Content-Range'] = obj['ContentRange']
        if obj.get('ETag'):
            headers['ETag'] = obj['ETag']
        return Response(obj['Body'].iter_chunks(64 * 1024),
                        status=206 if obj.get('ContentRange') else 200, headers=headers,
                        mimetype=mimetypes.guess_type(key)[0] or 'application/octet-stream')


def local_root():
    return os.environ.get('STORAGE_DIR') or os.path.join(current_app.root_path, 'static', 'uploads')


def get_backend():
    backend = current_app.extensions.get('quiz_storage')
    if backend is None:
        if os.environ.get('S3_BUCKET'):
            backend = S3Backend(os.environ)
        else:
            backend = LocalBackend(local_root())
        current_app.extensions['quiz_storage'] = backend
    return backend


def init_storage(app):
    # Правило конкретнее, чем /static/<path>, поэтому медиа всегда идут через бэкенд.
    @app.route(URL_PREFIX + '<path:key>')
    def storage_file(key):
        return get_backend().response(key)

    @app.cli.command('storage-push-s3')
    def storage_push_s3():
        """Скопировать локальные медиафайлы в S3 (нужны переменные S3_*)."""
        local, s3 = LocalBackend(local_root()), S3Backend(os.environ)
        for key, _size in local.list():
            s3.save(key, local.read(key))
            print(key)

    @app.cli.command('storage-recompress')
    def storage_recompress():
        """Пережать в WebP картинки, загруженные до появления сжатия."""
        print(recompress_images())

    def startup():
        with app.app_context():
            from app.models import db
            try:
                added = sync_storage()
                if added:
                    app.logger.info('Хранилище: учтено файлов — %s', added)
                done, failed = recompress_images()
                if done or failed:
                    app.logger.info('Хранилище: пережато в WebP — %s, не удалось — %s', done, failed)
            except Exception as e:
                db.session.rollback()
                app.logger.warning('Хранилище: сверка или сжатие файлов не выполнены: %s', e)

    # В фоне: сжатие старых картинок может идти минуты и не должно задерживать запуск.
    import eventlet
    eventlet.spawn(startup)


# ── Учёт места ─────────────────────────────────────────────────────────────────

def storage_limit():
    try:
        return int(os.environ.get('STORAGE_LIMIT_BYTES') or DEFAULT_LIMIT_BYTES)
    except ValueError:
        return DEFAULT_LIMIT_BYTES


def storage_used():
    from app.models import db, StoredFile
    return int(db.session.query(db.func.coalesce(db.func.sum(StoredFile.size), 0)).scalar())


def storage_full():
    return storage_used() >= storage_limit()


def human_size(n):
    n = float(n or 0)
    for unit in ('Б', 'КБ', 'МБ'):
        if n < 1024:
            return f'{n:.0f} {unit}' if unit == 'Б' else f'{n:.1f} {unit}'.replace('.', ',')
        n /= 1024
    return f'{n:.2f} ГБ'.replace('.', ',')


# ── Сохранение ─────────────────────────────────────────────────────────────────

def url_to_key(url):
    if not url or not isinstance(url, str) or not url.startswith(URL_PREFIX):
        return None
    return url[len(URL_PREFIX):].split('?', 1)[0]


def kind_of(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in AUDIO_EXTS:
        return 'audio'
    return None


def _encode_webp(frames, durations, loop, scale, quality):
    out = []
    for frame in frames:
        if scale < 1:
            size = (max(1, int(frame.width * scale)), max(1, int(frame.height * scale)))
            from PIL import Image
            frame = frame.resize(size, Image.LANCZOS)
        out.append(frame)
    buf = io.BytesIO()
    if len(out) > 1:
        out[0].save(buf, 'WEBP', save_all=True, append_images=out[1:], duration=durations,
                    loop=loop, quality=quality, method=4)
    else:
        out[0].save(buf, 'WEBP', quality=quality, method=4)
    return buf.getvalue()


def to_webp(data):
    """Любая картинка → WebP не больше MAX_IMAGE_BYTES (анимация сохраняется)."""
    from PIL import Image, ImageOps, ImageSequence
    img = Image.open(io.BytesIO(data))
    animated = getattr(img, 'is_animated', False)
    if img.format == 'WEBP' and len(data) <= MAX_IMAGE_BYTES:
        return data

    def prepare(frame):
        if not animated:
            frame = ImageOps.exif_transpose(frame)
        alpha = frame.mode in ('RGBA', 'LA', 'PA') or 'transparency' in frame.info
        return frame.convert('RGBA' if alpha or animated else 'RGB')

    if animated:
        frames, durations = [], []
        for frame in ImageSequence.Iterator(img):
            durations.append(frame.info.get('duration', 100))
            frames.append(prepare(frame))
        loop = img.info.get('loop', 0)
    else:
        frames, durations, loop = [prepare(img)], None, 0

    scale = min(1.0, MAX_IMAGE_SIDE / max(frames[0].size))
    while True:
        for quality in (88, 78, 66, 52):
            out = _encode_webp(frames, durations, loop, scale, quality)
            if len(out) <= MAX_IMAGE_BYTES:
                return out
        scale *= 0.75
        if max(frames[0].size) * scale < 64:
            raise ValueError('image cannot be compressed')


def _convert_image(data):
    try:
        # Сжатие нагружает процессор: уводим в поток, чтобы не замирали сокеты игры.
        from eventlet import tpool
        return tpool.execute(to_webp, data)
    except ImportError:
        return to_webp(data)


def quiz_folder(quiz):
    from app.models import db, StorageFolder
    folder = StorageFolder.query.filter_by(quiz_id=quiz.id).first()
    if not folder:
        folder = StorageFolder(name=quiz.title, quiz_id=quiz.id)
        db.session.add(folder)
        db.session.flush()
    return folder


def store_bytes(data, filename, kind, quiz=None, folder=None):
    """Положить файл в хранилище и завести запись. Коммит — на вызывающем."""
    from app.models import db, StoredFile
    filename = os.path.basename((filename or '').replace('\\', '/')) or 'file'
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in (IMAGE_EXTS if kind == 'image' else AUDIO_EXTS):
        raise StorageError('Неподдерживаемый тип файла. Картинки: JPG, PNG, WebP, GIF; '
                           'звук: MP3, WAV, OGG, M4A, AAC, FLAC')
    if not data:
        raise StorageError('Файл пустой')
    if kind == 'image':
        try:
            data = _convert_image(data)
        except Exception:
            raise StorageError('Не удалось обработать изображение. Загрузите JPG, PNG, WebP или GIF')
        ext = 'webp'
        filename = filename.rsplit('.', 1)[0] + '.webp'
    if storage_used() + len(data) > storage_limit():
        raise StorageError(
            f'Хранилище заполнено (лимит {human_size(storage_limit())}). '
            'Удалите ненужные файлы в разделе «Файлы квизов»', 507)
    if folder is None and quiz is not None:
        folder = quiz_folder(quiz)
    key = f"{quiz.id if quiz is not None else 'library'}/{KIND_DIRS[kind]}/{uuid.uuid4()}.{ext}"
    get_backend().save(key, data)
    stored = StoredFile(folder_id=folder.id if folder else None, kind=kind,
                        original_name=filename[:512], storage_key=key, size=len(data))
    db.session.add(stored)
    db.session.flush()
    return stored


def save_upload(file_storage, kind, quiz=None, folder=None):
    if not file_storage or not file_storage.filename:
        raise StorageError('Файл не выбран')
    return store_bytes(file_storage.read(), file_storage.filename, kind, quiz=quiz, folder=folder)


def read_url(url):
    key = url_to_key(url)
    return get_backend().read(key) if key else None


# ── Использование файлов ───────────────────────────────────────────────────────

def file_usage():
    """{адрес файла: [{'quiz_id', 'quiz', 'where'}]} по всем квизам."""
    from app.models import Quiz
    usage = {}

    def add(url, quiz, where):
        if url_to_key(url):
            refs = usage.setdefault(url, [])
            if not any(r['quiz_id'] == quiz.id and r['where'] == where for r in refs):
                refs.append({'quiz_id': quiz.id, 'quiz': quiz.title, 'where': where})

    def add_text(text, quiz, where):
        if text and URL_PREFIX in text:
            for url in _URL_RE.findall(text):
                add(url, quiz, where)

    for quiz in Quiz.query.all():
        add(quiz.splash_image, quiz, 'заставка квиза')
        add(quiz.bg_image, quiz, 'фон слайдов')
        add(quiz.sound_start_path, quiz, 'звук старта')
        add(quiz.sound_mid_path, quiz, 'звук предупреждения')
        add(quiz.sound_end_path, quiz, 'звук конца времени')
        tour_no = 0
        for tour in quiz.tours:
            if tour.is_slide:
                where = f'слайд «{tour.title}»'
                add(tour.splash_image, quiz, where)
                add(tour.slide_audio_path, quiz, where)
                add_text(tour.slide_text, quiz, where)
                continue
            tour_no += 1
            add(tour.splash_image, quiz, f'заставка тура {tour_no}')
            for i, q in enumerate(tour.questions, 1):
                where = f'тур {tour_no}, вопрос {i}'
                add(q.image_path, quiz, where)
                add(q.audio_path, quiz, where)
                add(q.answer_audio_path, quiz, where)
                add_text(q.text, quiz, where)
                add_text(q.correct_answer, quiz, where)
    return usage


def delete_stored(stored):
    from app.models import db
    get_backend().delete(stored.storage_key)
    db.session.delete(stored)


def release_quiz_folder(quiz):
    """Перед удалением квиза: пустая папка удаляется, непустая остаётся с его названием."""
    from app.models import db, StorageFolder
    for folder in StorageFolder.query.filter_by(quiz_id=quiz.id).all():
        if folder.files:
            folder.name = quiz.title
            folder.quiz_id = None
        else:
            db.session.delete(folder)


def sync_storage():
    """Завести записи для файлов, которые лежат в хранилище, но ещё не учтены."""
    from app.models import db, Quiz, Tour, Question, StoredFile
    known = {key for (key,) in db.session.query(StoredFile.storage_key).all()}
    names = {}
    for q in Question.query.filter(db.or_(Question.audio_path.isnot(None),
                                          Question.answer_audio_path.isnot(None))).all():
        names[q.audio_path] = q.audio_original_name
        names[q.answer_audio_path] = q.answer_audio_original_name
    for t in Tour.query.filter(Tour.slide_audio_path.isnot(None)).all():
        names[t.slide_audio_path] = t.slide_audio_original_name
    quizzes = {quiz.id: quiz for quiz in Quiz.query.all()}
    added = 0
    for key, size in get_backend().list():
        kind = kind_of(key)
        if key in known or not kind:
            continue
        quiz = quizzes.get(key.split('/', 1)[0])
        db.session.add(StoredFile(
            folder_id=quiz_folder(quiz).id if quiz else None, kind=kind,
            original_name=(names.get(URL_PREFIX + key) or key.rsplit('/', 1)[-1])[:512],
            storage_key=key, size=size))
        added += 1
    db.session.commit()
    return added


def _replace_url(old, new):
    """Заменить адрес файла во всех полях квизов, где он может встретиться."""
    from app.models import db, Quiz, Tour, Question
    for column in (Quiz.splash_image, Quiz.bg_image, Tour.splash_image, Question.image_path):
        db.session.query(column.class_).filter(column == old).update(
            {column.key: new}, synchronize_session=False)
    for column in (Tour.slide_text, Question.text, Question.correct_answer):
        db.session.query(column.class_).filter(column.contains(old, autoescape=True)).update(
            {column.key: db.func.replace(column, old, new)}, synchronize_session=False)


def recompress_images():
    """Старые картинки (не WebP или больше 3 МБ) → WebP с обновлением ссылок в квизах."""
    from app.models import db, StoredFile
    pending = [f.id for f in StoredFile.query.filter_by(kind='image').all()
               if not f.storage_key.lower().endswith('.webp') or f.size > MAX_IMAGE_BYTES]
    backend = get_backend()
    done = failed = 0
    for file_id in pending:
        # Блокировка строки: при двух процессах (reloader, перезапуск) файл берёт только один.
        stored = (StoredFile.query.filter_by(id=file_id)
                  .with_for_update(skip_locked=True).first())
        if not stored:
            db.session.rollback()
            continue
        old_key = stored.storage_key
        try:
            data = backend.read(old_key)
            if data is None:
                raise ValueError('file is missing')
            data = _convert_image(data)
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning('Не удалось пережать %s: %s', old_key, e)
            failed += 1
            continue
        new_key = old_key.rsplit('.', 1)[0] + '.webp'
        backend.save(new_key, data)
        stored.storage_key = new_key
        stored.size = len(data)
        stored.original_name = (stored.original_name.rsplit('.', 1)[0] + '.webp')[:512]
        if new_key != old_key:
            _replace_url(URL_PREFIX + old_key, URL_PREFIX + new_key)
        db.session.commit()
        if new_key != old_key:
            backend.delete(old_key)
        done += 1
    return done, failed
