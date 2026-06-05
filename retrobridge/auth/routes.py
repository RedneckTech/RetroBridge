import json
from datetime import datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from retrobridge.auth import auth_bp
from retrobridge.auth.forms import LoginForm, RegistrationForm, ProfileForm
from retrobridge.models import Job, LoginAttempt, TerminalSession, User

MAX_FAILED_ATTEMPTS = 5
THROTTLE_WINDOW_MINUTES = 15


def _record_attempt(db_session, ip_address, username, success):
    attempt = LoginAttempt(
        ip_address=ip_address,
        username=username,
        success=success,
    )
    db_session.add(attempt)
    db_session.commit()


def _is_throttled(db_session, ip_address):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=THROTTLE_WINDOW_MINUTES)
    count = (
        db_session.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
        .count()
    )
    return count >= MAX_FAILED_ATTEMPTS


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('jobs.dashboard'))

    from flask import current_app
    ip_address = request.remote_addr or '127.0.0.1'

    form = LoginForm()
    if form.validate_on_submit():
        if _is_throttled(current_app.db_session, ip_address):
            flash(
                f'Too many failed login attempts. '
                f'Please try again in {THROTTLE_WINDOW_MINUTES} minutes.',
                'danger',
            )
            return render_template('auth/login.html', form=form)

        user = current_app.db_session.query(User).filter_by(
            username=form.username.data
        ).first()

        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.now(timezone.utc)
            _record_attempt(current_app.db_session, ip_address,
                            form.username.data, success=True)
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('jobs.dashboard'))
        else:
            _record_attempt(current_app.db_session, ip_address,
                            form.username.data, success=False)
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('jobs.dashboard'))

    from flask import current_app
    from retrobridge.admin.settings_utils import get_bool

    if not get_bool('REGISTRATION_OPEN'):
        flash('Registration is currently closed.', 'warning')
        return render_template('auth/register.html', form=RegistrationForm())

    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            full_name=form.full_name.data,
        )
        current_app.db_session.add(user)
        current_app.db_session.commit()
        login_user(user)
        flash('Account created successfully. Welcome!', 'success')
        return redirect(url_for('jobs.dashboard'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    from flask import current_app

    form = ProfileForm(obj=current_user)

    if request.method == 'GET':
        prefs = {}
        if current_user.preferences:
            try:
                prefs = json.loads(current_user.preferences)
            except json.JSONDecodeError:
                pass
        form.terminal_font_size.data = prefs.get('terminal_font_size', 14)
        form.terminal_color_scheme.data = prefs.get('terminal_color_scheme', 'dark')

    if form.validate_on_submit():
        current_user.email = form.email.data
        current_user.full_name = form.full_name.data
        current_user.bio = form.bio.data
        current_user.preferences = json.dumps({
            'terminal_font_size': form.terminal_font_size.data,
            'terminal_color_scheme': form.terminal_color_scheme.data,
        })
        if form.new_password.data:
            current_user.password_hash = generate_password_hash(form.new_password.data)
        current_app.db_session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('auth.profile'))

    # Stats
    total_jobs = current_app.db_session.query(Job).filter_by(
        user_id=current_user.id).count()
    queued_count = current_app.db_session.query(Job).filter_by(
        user_id=current_user.id, status='queued').count()
    running_count = current_app.db_session.query(Job).filter_by(
        user_id=current_user.id, status='running').count()
    completed_count = current_app.db_session.query(Job).filter_by(
        user_id=current_user.id, status='completed').count()
    total_sessions = current_app.db_session.query(TerminalSession).filter_by(
        user_id=current_user.id).count()
    active_sessions = current_app.db_session.query(TerminalSession).filter_by(
        user_id=current_user.id, status='active').count()

    recent_jobs = current_app.db_session.query(Job).filter_by(
        user_id=current_user.id).order_by(Job.created_at.desc()).limit(5).all()
    recent_sessions = current_app.db_session.query(TerminalSession).filter_by(
        user_id=current_user.id).order_by(
        TerminalSession.connected_at.desc()).limit(5).all()

    stats = {
        'total_jobs': total_jobs,
        'queued_count': queued_count,
        'running_count': running_count,
        'completed_count': completed_count,
        'total_sessions': total_sessions,
        'active_sessions': active_sessions,
        'max_queued': current_user.max_queued_jobs,
        'max_sessions': current_user.max_terminal_sessions,
    }

    return render_template('auth/profile.html', form=form, stats=stats,
                           recent_jobs=recent_jobs,
                           recent_sessions=recent_sessions)


@auth_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    from flask import current_app
    user = current_app.db_session.get(User, current_user.id)
    if user:
        logout_user()
        current_app.db_session.delete(user)
        current_app.db_session.commit()
        flash('Your account has been deleted.', 'info')
    return redirect(url_for('auth.login'))
