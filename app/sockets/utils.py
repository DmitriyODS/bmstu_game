_ALL_NS = ('/admin', '/presentation', '/participant', '/judge')


def broadcast(event, data, room):
    from app import socketio
    for ns in _ALL_NS:
        socketio.emit(event, data, room=room, namespace=ns)


def broadcast_all(event, data):
    """Broadcast to all connected clients in all namespaces (no room filter)."""
    from app import socketio
    for ns in _ALL_NS:
        socketio.emit(event, data, namespace=ns)
