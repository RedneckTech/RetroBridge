from functools import wraps

from flask import abort
from flask_login import current_user

from retrobridge.models import User


def load_user(user_id):
    from flask import current_app
    return current_app.db_session.get(User, int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
