"""WSGI entry point for production deployments using eventlet workers.

Use with gunicorn, for example:

    gunicorn -k eventlet -w 4 -b 127.0.0.1:5000 wsgi_eventlet:app

Monkey-patching must happen before any other imports (socket, threading,
database drivers, etc.) so that the entire application runs on greenlets.
"""
import eventlet
eventlet.monkey_patch()

from retrobridge import create_app  # noqa: E402

app = create_app()
