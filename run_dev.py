import os
import eventlet
eventlet.monkey_patch()

from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    socketio.run(
        app,
        debug=True,
        use_reloader=True,
        host='0.0.0.0',
        # На macOS порт 5000 занят AirPlay Receiver — можно переопределить через PORT.
        port=int(os.environ.get('PORT', 5000)),

    )
