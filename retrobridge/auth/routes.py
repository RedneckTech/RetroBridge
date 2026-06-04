from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from retrobridge.auth import auth_bp
from retrobridge.auth.forms import LoginForm, RegistrationForm, ProfileForm
from retrobridge.models import User


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('jobs.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        from flask import current_app
        user = current_app.db_session.query(User).filter_by(
            username=form.username.data
        ).first()

        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember_me.data)
            from datetime import datetime, timezone
            user.last_login = datetime.now(timezone.utc)
            current_app.db_session.commit()
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('jobs.dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('jobs.dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        from flask import current_app
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
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        from flask import current_app
        current_user.email = form.email.data
        current_user.full_name = form.full_name.data
        if form.new_password.data:
            current_user.password_hash = generate_password_hash(form.new_password.data)
        current_app.db_session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)
