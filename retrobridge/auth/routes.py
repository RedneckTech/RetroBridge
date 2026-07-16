import json
from datetime import datetime, timedelta, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from retrobridge.auth import auth_bp
from retrobridge.auth.forms import LoginForm, RegistrationForm, ProfileForm
from retrobridge.models import Job, LoginAttempt, TerminalSession, User
from retrobridge.integrations.email import (
    notify_password_changed, notify_email_changed,
    notify_new_login, notify_account_deleted,
)

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

            if user.email_notify_security:
                prior_attempts = (
                    current_app.db_session.query(LoginAttempt)
                    .filter(
                        LoginAttempt.username == user.username,
                        LoginAttempt.success.is_(True),
                        LoginAttempt.ip_address == ip_address,
                    )
                    .count()
                )
                if prior_attempts <= 1:
                    notify_new_login(user, ip_address)

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
        # Check for duplicate username
        existing_user = current_app.db_session.query(User).filter_by(
            username=form.username.data).first()
        if existing_user:
            form.username.errors.append('This username is already taken.')
            return render_template('auth/register.html', form=form)

        # Check for duplicate email
        existing_email = current_app.db_session.query(User).filter_by(
            email=form.email.data).first()
        if existing_email:
            form.email.errors.append('This email is already registered.')
            return render_template('auth/register.html', form=form)

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
    from retrobridge.integrations.patreon import is_enabled as is_patreon_enabled

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
        old_email = current_user.email
        current_user.email = form.email.data
        current_user.full_name = form.full_name.data
        current_user.bio = form.bio.data
        current_user.email_notify_jobs = form.email_notify_jobs.data
        current_user.email_notify_security = form.email_notify_security.data
        current_user.preferences = json.dumps({
            'terminal_font_size': form.terminal_font_size.data,
            'terminal_color_scheme': form.terminal_color_scheme.data,
        })
        if form.new_password.data:
            current_user.password_hash = generate_password_hash(form.new_password.data)
            if current_user.email_notify_security:
                notify_password_changed(current_user)
        if old_email != current_user.email and current_user.email_notify_security:
            notify_email_changed(current_user, old_email, current_user.email)
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
                           recent_sessions=recent_sessions,
                           patreon_enabled=is_patreon_enabled())


@auth_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    from flask import current_app
    user = current_app.db_session.get(User, current_user.id)
    if user:
        if user.email_notify_security:
            notify_account_deleted(user)
        logout_user()
        current_app.db_session.delete(user)
        current_app.db_session.commit()
        flash('Your account has been deleted.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile/patreon/link')
@login_required
def patreon_link():
    from retrobridge.integrations.patreon import is_enabled, get_authorize_url
    if not is_enabled():
        flash('Patreon integration is not configured.', 'warning')
        return redirect(url_for('auth.profile'))
    redirect_uri = url_for('auth.patreon_callback', _external=True)
    state = str(current_user.id)
    return redirect(get_authorize_url(redirect_uri, state=state))


@auth_bp.route('/profile/patreon/callback')
def patreon_callback():
    from flask import current_app
    from retrobridge.integrations.patreon import (
        exchange_code, fetch_patreon_identity, fetch_membership_tier,
    )

    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error:
        flash(f'Patreon authorization failed: {error}', 'danger')
        return redirect(url_for('auth.profile'))

    if not code or not state:
        flash('Invalid Patreon callback parameters.', 'danger')
        return redirect(url_for('auth.profile'))

    try:
        user_id = int(state)
    except (ValueError, TypeError):
        flash('Invalid state parameter.', 'danger')
        return redirect(url_for('auth.profile'))

    user = current_app.db_session.get(User, user_id)
    if not user or user.id != current_user.id:
        flash('Authentication error.', 'danger')
        return redirect(url_for('auth.profile'))

    redirect_uri = url_for('auth.patreon_callback', _external=True)
    tokens = exchange_code(code, redirect_uri)
    if not tokens:
        flash('Failed to exchange Patreon authorization code.', 'danger')
        return redirect(url_for('auth.profile'))

    identity = fetch_patreon_identity(tokens['access_token'])
    if not identity:
        flash('Failed to fetch Patreon profile.', 'danger')
        return redirect(url_for('auth.profile'))

    tier = fetch_membership_tier(tokens['access_token'])

    user.patreon_id = identity['id']
    user.patreon_tier = tier
    user.patreon_access_token = tokens['access_token']
    user.patreon_refresh_token = tokens['refresh_token']
    user.patreon_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=tokens['expires_in'],
    )
    current_app.db_session.commit()

    if tier:
        flash(f'Patreon account linked — tier: {tier}', 'success')
    else:
        flash('Patreon account linked (no active membership found).', 'info')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/profile/patreon/unlink', methods=['POST'])
@login_required
def patreon_unlink():
    from flask import current_app
    from retrobridge.integrations.patreon import unlink_user

    user = current_app.db_session.get(User, current_user.id)
    if user:
        unlink_user(user)
        current_app.db_session.commit()
        flash('Patreon account unlinked.', 'info')
    return redirect(url_for('auth.profile'))
