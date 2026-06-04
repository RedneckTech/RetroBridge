from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from retrobridge.admin import admin_bp
from retrobridge.auth.utils import admin_required
from retrobridge.admin.forms import DeviceForm, DevicePortForm, UserEditForm, SettingsForm
from retrobridge.models import User, Device, DevicePort, Job, TerminalSession, AdminSetting


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    from flask import current_app
    stats = {
        'total_users': current_app.db_session.query(User).count(),
        'total_jobs': current_app.db_session.query(Job).count(),
        'running_jobs': current_app.db_session.query(Job).filter_by(status='running').count(),
        'active_sessions': current_app.db_session.query(TerminalSession).filter_by(status='active').count(),
        'devices': current_app.db_session.query(Device).all(),
    }
    return render_template('admin/dashboard.html', stats=stats)


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = 20
    query = current_app.db_session.query(User).order_by(User.username)
    total = query.count()
    users_list = query.offset((page - 1) * per_page).limit(per_page).all()
    return render_template('admin/users.html', users=users_list, total=total,
                           page=page, pages=(total + per_page - 1) // per_page)


@admin_bp.route('/users/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def edit_user(user_id):
    from flask import current_app
    user = current_app.db_session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users'))

    form = UserEditForm(obj=user)
    if form.validate_on_submit():
        user.email = form.email.data
        user.full_name = form.full_name.data
        user.is_admin = form.is_admin.data
        user.max_queued_jobs = form.max_queued_jobs.data
        user.max_terminal_sessions = form.max_terminal_sessions.data
        current_app.db_session.commit()
        flash('User updated.', 'success')
        return redirect(url_for('admin.users'))

    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    from flask import current_app
    if user_id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))

    user = current_app.db_session.get(User, user_id)
    if user:
        current_app.db_session.delete(user)
        current_app.db_session.commit()
        flash('User deleted.', 'info')

    return redirect(url_for('admin.users'))


@admin_bp.route('/devices')
@login_required
@admin_required
def devices():
    from flask import current_app
    devices_list = current_app.db_session.query(Device).order_by(Device.name).all()
    form = DeviceForm()
    return render_template('admin/devices.html', devices=devices_list, form=form)


@admin_bp.route('/devices', methods=['POST'])
@login_required
@admin_required
def add_device():
    from flask import current_app
    form = DeviceForm()
    if form.validate_on_submit():
        device = Device(
            name=form.name.data,
            display_name=form.display_name.data,
        )
        current_app.db_session.add(device)
        current_app.db_session.commit()
        flash('Device added.', 'success')
    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/ports', methods=['POST'])
@login_required
@admin_required
def add_port(device_id):
    from flask import current_app
    device = current_app.db_session.get(Device, device_id)
    if not device:
        flash('Device not found.', 'danger')
        return redirect(url_for('admin.devices'))

    form = DevicePortForm()
    if form.validate_on_submit():
        port = DevicePort(
            device_id=device_id,
            port_label=form.port_label.data,
            dev_path=form.dev_path.data,
            purpose=form.purpose.data,
            baud=form.baud.data,
            data_bits=form.data_bits.data,
            parity=form.parity.data,
            stop_bits=form.stop_bits.data,
            flow_control=form.flow_control.data,
            newline_mode=form.newline_mode.data,
            max_runtime_seconds=form.max_runtime_seconds.data,
            idle_timeout_seconds=form.idle_timeout_seconds.data,
        )
        current_app.db_session.add(port)
        current_app.db_session.commit()
        flash('Port added.', 'success')

    return redirect(url_for('admin.devices'))


@admin_bp.route('/jobs')
@login_required
@admin_required
def jobs():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status')
    query = current_app.db_session.query(Job).order_by(Job.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    total = query.count()
    jobs_list = query.offset((page - 1) * per_page).limit(per_page).all()
    return render_template('admin/jobs.html', jobs=jobs_list, total=total,
                           page=page, pages=(total + per_page - 1) // per_page)


@admin_bp.route('/sessions')
@login_required
@admin_required
def sessions():
    from flask import current_app
    active = current_app.db_session.query(TerminalSession).filter_by(status='active').all()
    history = (
        current_app.db_session.query(TerminalSession)
        .filter(TerminalSession.status != 'active')
        .order_by(TerminalSession.connected_at.desc())
        .limit(50)
        .all()
    )
    return render_template('admin/sessions.html', active_sessions=active, history=history)


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    from flask import current_app
    settings_list = current_app.db_session.query(AdminSetting).all()
    form = SettingsForm()

    if request.method == 'GET':
        for s in settings_list:
            if s.key in form._fields:
                form._fields[s.key].data = s.value
    elif form.validate_on_submit():
        from retrobridge.models import AdminSetting
        for field_name in form._fields:
            if field_name in ('submit', 'csrf_token'):
                continue
            setting = current_app.db_session.get(AdminSetting, field_name)
            if setting:
                setting.value = form._fields[field_name].data or ''
        current_app.db_session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', settings=settings_list, form=form)
