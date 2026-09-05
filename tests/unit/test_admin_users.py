"""Unit tests for admin user management routes."""
from werkzeug.security import check_password_hash, generate_password_hash

from retrobridge.models import User


def _login_admin(client, db_session):
    admin = User(
        username='adminuser',
        email='admin@example.com',
        password_hash=generate_password_hash('Password123'),
        is_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    resp = client.post('/auth/login', data={
        'username': 'adminuser',
        'password': 'Password123',
    }, follow_redirects=True)
    assert resp.status_code == 200
    return admin


def test_edit_user_password(client, db_session):
    _login_admin(client, db_session)
    user = User(
        username='editme',
        email='editme@example.com',
        password_hash=generate_password_hash('OldPass123'),
    )
    db_session.add(user)
    db_session.commit()

    resp = client.post(f'/admin/users/{user.id}', data={
        'username': 'editme',
        'email': 'editme@example.com',
        'full_name': 'Edited',
        'password': 'NewPass456',
        'is_admin': False,
        'max_queued_jobs': 3,
        'max_terminal_sessions': 1,
        'csrf_token': client.get('/admin/users').get_data(as_text=True),
    }, follow_redirects=True)
    assert resp.status_code == 200

    updated = db_session.get(User, user.id)
    assert check_password_hash(updated.password_hash, 'NewPass456')


def test_edit_user_rejects_duplicate_username(client, db_session):
    _login_admin(client, db_session)
    user1 = User(username='user1', email='u1@example.com',
                 password_hash=generate_password_hash('Pass123'))
    user2 = User(username='user2', email='u2@example.com',
                 password_hash=generate_password_hash('Pass123'))
    db_session.add_all([user1, user2])
    db_session.commit()

    # Need a valid CSRF token from the edit page
    edit_page = client.get(f'/admin/users')
    csrf = _extract_csrf(edit_page.get_data(as_text=True))

    resp = client.post(f'/admin/users/{user2.id}', data={
        'username': 'user1',
        'email': 'u2@example.com',
        'full_name': '',
        'password': '',
        'is_admin': False,
        'max_queued_jobs': 3,
        'max_terminal_sessions': 1,
        'csrf_token': csrf,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Username already taken' in resp.data

    updated = db_session.get(User, user2.id)
    assert updated.username == 'user2'


def test_edit_user_rejects_duplicate_email(client, db_session):
    _login_admin(client, db_session)
    user1 = User(username='user1', email='u1@example.com',
                 password_hash=generate_password_hash('Pass123'))
    user2 = User(username='user2', email='u2@example.com',
                 password_hash=generate_password_hash('Pass123'))
    db_session.add_all([user1, user2])
    db_session.commit()

    csrf = _extract_csrf(client.get('/admin/users').get_data(as_text=True))

    resp = client.post(f'/admin/users/{user2.id}', data={
        'username': 'user2',
        'email': 'u1@example.com',
        'full_name': '',
        'password': '',
        'is_admin': False,
        'max_queued_jobs': 3,
        'max_terminal_sessions': 1,
        'csrf_token': csrf,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Email already in use' in resp.data

    updated = db_session.get(User, user2.id)
    assert updated.email == 'u2@example.com'


def _extract_csrf(html):
    import re
    m = re.search(r'name="csrf_token"[^>]+value="([^"]+)"', html)
    return m.group(1) if m else ''
