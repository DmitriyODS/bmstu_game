from flask import render_template, redirect, url_for, request, flash, jsonify
from app.admin import admin_bp
from app.auth import admin_required
from app.models import db, Quiz, Tour, Question, StorageFolder, StoredFile
from app import storage
from app.storage import StorageError

# Куда можно подставить файл из хранилища: поле → (тип файла, поле с именем файла).
_ATTACH_TARGETS = {
    'quiz': (Quiz, {
        'splash_image': ('image', None),
        'bg_image': ('image', None),
        'sound_start_path': ('audio', None),
        'sound_mid_path': ('audio', None),
        'sound_end_path': ('audio', None),
    }),
    'tour': (Tour, {
        'splash_image': ('image', None),
        'slide_audio_path': ('audio', 'slide_audio_original_name'),
    }),
    'question': (Question, {
        'image_path': ('image', None),
        'audio_path': ('audio', 'audio_original_name'),
        'answer_audio_path': ('audio', 'answer_audio_original_name'),
    }),
}


def _folder_title(folder):
    return folder.quiz.title if folder.quiz else folder.name


def _folders():
    folders = StorageFolder.query.all()
    # Сначала папки квизов, затем пользовательские — по алфавиту.
    return sorted(folders, key=lambda f: (f.quiz_id is None, _folder_title(f).lower()))


def _file_dict(f, usage=None):
    data = {
        'id': f.id,
        'url': f.url,
        'name': f.original_name,
        'kind': f.kind,
        'size': storage.human_size(f.size),
        'folder_id': f.folder_id,
    }
    if usage is not None:
        data['usage'] = usage.get(f.url, [])
    return data


@admin_bp.route('/files')
@admin_required
def files():
    folder_id = request.args.get('folder', 'all')
    kind = request.args.get('kind', '')
    only_unused = request.args.get('unused') == '1'
    search = request.args.get('q', '').strip()

    query = StoredFile.query
    current = None
    if folder_id == 'none':
        query = query.filter(StoredFile.folder_id.is_(None))
    elif folder_id != 'all':
        current = StorageFolder.query.get_or_404(folder_id)
        query = query.filter_by(folder_id=current.id)
    if kind in ('image', 'audio'):
        query = query.filter_by(kind=kind)
    if search:
        query = query.filter(StoredFile.original_name.ilike(f'%{search}%'))
    items = query.order_by(StoredFile.created_at.desc()).all()

    usage = storage.file_usage()
    if only_unused:
        items = [f for f in items if f.url not in usage]

    stats = dict(db.session.query(StoredFile.folder_id, db.func.count(StoredFile.id))
                 .group_by(StoredFile.folder_id).all())
    used, limit = storage.storage_used(), storage.storage_limit()
    return render_template(
        'admin/files.html', items=items, usage=usage, folders=_folders(), current=current,
        folder_id=folder_id, kind=kind, only_unused=only_unused, search=search,
        folder_title=_folder_title, counts=stats, total_count=sum(stats.values()),
        used=used, limit=limit, human_size=storage.human_size,
        percent=min(100, round(used * 100 / limit)) if limit else 100,
        backend_label=storage.get_backend().label)


@admin_bp.route('/files/list')
@admin_required
def files_list():
    """Данные для окна «Выбрать из хранилища» в конструкторе."""
    kind = request.args.get('kind')
    query = StoredFile.query
    if kind in ('image', 'audio'):
        query = query.filter_by(kind=kind)
    return jsonify({
        'folders': [{'id': f.id, 'name': _folder_title(f), 'quiz_id': f.quiz_id} for f in _folders()],
        'files': [_file_dict(f) for f in query.order_by(StoredFile.created_at.desc()).all()],
    })


@admin_bp.route('/files/upload', methods=['POST'])
@admin_required
def files_upload():
    folder = StorageFolder.query.get(request.form.get('folder_id') or '')
    saved, errors = 0, []
    for f in request.files.getlist('files'):
        kind = storage.kind_of(f.filename or '')
        try:
            if not kind:
                raise StorageError('неподдерживаемый тип файла')
            storage.save_upload(f, kind, quiz=folder.quiz if folder else None, folder=folder)
            db.session.commit()
            saved += 1
        except StorageError as e:
            db.session.rollback()
            errors.append(f'{f.filename}: {e.message}')
            if e.status == 507:
                break
    return jsonify({'saved': saved, 'errors': errors})


@admin_bp.route('/files/folders', methods=['POST'])
@admin_required
def files_folder_create():
    name = request.form.get('name', '').strip()[:256]
    if not name:
        flash('Введите название папки', 'error')
        return redirect(url_for('admin.files'))
    folder = StorageFolder(name=name)
    db.session.add(folder)
    db.session.commit()
    return redirect(url_for('admin.files', folder=folder.id))


@admin_bp.route('/files/folders/<folder_id>/rename', methods=['POST'])
@admin_required
def files_folder_rename(folder_id):
    folder = StorageFolder.query.get_or_404(folder_id)
    name = request.form.get('name', '').strip()[:256]
    if folder.quiz_id:
        flash('Папка квиза называется так же, как квиз', 'error')
    elif not name:
        flash('Введите название папки', 'error')
    else:
        folder.name = name
        db.session.commit()
    return redirect(url_for('admin.files', folder=folder.id))


@admin_bp.route('/files/folders/<folder_id>/delete', methods=['POST'])
@admin_required
def files_folder_delete(folder_id):
    folder = StorageFolder.query.get_or_404(folder_id)
    if folder.quiz_id:
        flash('Папку существующего квиза удалить нельзя', 'error')
        return redirect(url_for('admin.files', folder=folder.id))
    moved = len(folder.files)
    for f in list(folder.files):
        f.folder_id = None
    db.session.delete(folder)
    db.session.commit()
    flash('Папка удалена' + (f'. Файлы ({moved}) перенесены в «Без папки»' if moved else ''), 'success')
    return redirect(url_for('admin.files', folder='none' if moved else 'all'))


@admin_bp.route('/files/move', methods=['POST'])
@admin_required
def files_move():
    data = request.json or {}
    folder_id = data.get('folder_id') or None
    if folder_id and not StorageFolder.query.get(folder_id):
        return jsonify({'error': 'Папка не найдена'}), 404
    ids = [i for i in data.get('ids', []) if isinstance(i, str)]
    moved = 0
    if ids:
        moved = StoredFile.query.filter(StoredFile.id.in_(ids)).update(
            {'folder_id': folder_id}, synchronize_session=False)
    db.session.commit()
    return jsonify({'moved': moved})


@admin_bp.route('/files/delete', methods=['POST'])
@admin_required
def files_delete():
    ids = [i for i in (request.json or {}).get('ids', []) if isinstance(i, str)]
    usage = storage.file_usage()
    deleted, blocked = 0, []
    for f in (StoredFile.query.filter(StoredFile.id.in_(ids)).all() if ids else []):
        if f.url in usage:
            blocked.append({'name': f.original_name,
                            'quizzes': sorted({r['quiz'] for r in usage[f.url]})})
            continue
        storage.delete_stored(f)
        deleted += 1
    db.session.commit()
    return jsonify({'deleted': deleted, 'blocked': blocked})


@admin_bp.route('/files/rescan', methods=['POST'])
@admin_required
def files_rescan():
    try:
        added = storage.sync_storage()
    except Exception as e:
        db.session.rollback()
        flash(f'Не удалось прочитать хранилище: {e}', 'error')
        return redirect(url_for('admin.files'))
    flash(f'Найдено новых файлов: {added}' if added else 'Все файлы уже учтены', 'success')
    return redirect(url_for('admin.files'))


@admin_bp.route('/files/<file_id>/attach', methods=['POST'])
@admin_required
def files_attach(file_id):
    stored = StoredFile.query.get_or_404(file_id)
    data = request.json or {}
    model, fields = _ATTACH_TARGETS.get(data.get('target'), (None, {}))
    kind, name_field = fields.get(data.get('field'), (None, None))
    if not model or not kind:
        return jsonify({'error': 'Неизвестное поле'}), 400
    if stored.kind != kind:
        return jsonify({'error': 'Файл не подходит по типу'}), 400
    obj = model.query.get_or_404(data.get('id') or '')
    setattr(obj, data['field'], stored.url)
    if name_field:
        setattr(obj, name_field, stored.original_name)
    if data['field'] == 'bg_image':
        obj.bg_type = 'image'
    db.session.commit()
    if data['field'] == 'bg_image':
        from app.admin.routes import _broadcast_background
        _broadcast_background(obj)
    return jsonify({'path': stored.url, 'original_name': stored.original_name})
