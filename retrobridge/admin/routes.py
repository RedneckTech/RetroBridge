from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from retrobridge.admin import admin_bp
from retrobridge.auth.utils import admin_required
from retrobridge.admin.forms import (
    DeviceForm, DevicePortForm, EditDeviceForm, SettingsForm, UserEditForm,
)
from retrobridge.models import (
    AdminSetting, Device, DevicePort, Job, TerminalSession, User,
)


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


# -- User Management --

def _user_stats(db_session, user):
    return {
        'total_jobs': db_session.query(Job).filter_by(user_id=user.id).count(),
        'running_jobs': db_session.query(Job)
            .filter_by(user_id=user.id, status='running').count(),
        'completed_jobs': db_session.query(Job)
            .filter_by(user_id=user.id, status='completed').count(),
        'active_sessions': db_session.query(TerminalSession)
            .filter_by(user_id=user.id, status='active').count(),
    }


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '').strip()

    query = current_app.db_session.query(User).order_by(User.username)
    if search:
        query = query.filter(
            User.username.ilike(f'%{search}%') |
            User.email.ilike(f'%{search}%')
        )
    total = query.count()
    users_list = query.offset((page - 1) * per_page).limit(per_page).all()

    user_stats = {}
    for u in users_list:
        user_stats[u.id] = _user_stats(current_app.db_session, u)

    return render_template('admin/users.html', users=users_list, total=total,
                           page=page, pages=(total + per_page - 1) // per_page,
                           search=search, user_stats=user_stats)


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    from flask import current_app
    from werkzeug.security import generate_password_hash
    from retrobridge.admin.settings_utils import get_int

    form = UserEditForm()
    form.submit.label.text = 'Create User'
    if form.validate_on_submit():
        existing = current_app.db_session.query(User).filter_by(
            username=form.username.data).first()
        if existing:
            flash('Username already taken.', 'danger')
            return redirect(url_for('admin.users'))

        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            password_hash=generate_password_hash(form.password.data),
            is_admin=form.is_admin.data,
            max_queued_jobs=form.max_queued_jobs.data,
            max_terminal_sessions=form.max_terminal_sessions.data,
        )
        current_app.db_session.add(user)
        current_app.db_session.commit()
        flash('User created.', 'success')
    return redirect(url_for('admin.users'))


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
        user.username = form.username.data
        user.email = form.email.data
        user.full_name = form.full_name.data
        user.is_admin = form.is_admin.data
        user.max_queued_jobs = form.max_queued_jobs.data
        user.max_terminal_sessions = form.max_terminal_sessions.data
        current_app.db_session.commit()
        flash('User updated.', 'success')
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


# -- Device Management --

@admin_bp.route('/devices')
@login_required
@admin_required
def devices():
    from flask import current_app
    devices_list = current_app.db_session.query(Device).order_by(Device.name).all()
    add_form = DeviceForm()
    port_form = DevicePortForm()
    port_form.submit.label.text = 'Add Port'
    return render_template('admin/devices.html', devices=devices_list,
                           add_form=add_form, port_form=port_form)


def _device_stats(db_session, device):
    return {
        'active_sessions': db_session.query(TerminalSession)
            .filter_by(device_id=device.id, status='active').count(),
        'queued_jobs': db_session.query(Job)
            .filter_by(device_id=device.id, status='queued').count(),
        'running_jobs': db_session.query(Job)
            .filter_by(device_id=device.id, status='running').count(),
        'total_ports': len([p for p in device.ports if p.is_enabled]),
    }


# -- Device CRUD --

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


@admin_bp.route('/devices/<int:device_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_device(device_id):
    from flask import current_app
    device = current_app.db_session.get(Device, device_id)
    if not device:
        flash('Device not found.', 'danger')
        return redirect(url_for('admin.devices'))

    form = EditDeviceForm(obj=device)
    if form.validate_on_submit():
        device.name = form.name.data
        device.display_name = form.display_name.data
        device.is_enabled = form.is_enabled.data
        current_app.db_session.commit()
        flash('Device updated.', 'success')
    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_device(device_id):
    from flask import current_app
    device = current_app.db_session.get(Device, device_id)
    if not device:
        flash('Device not found.', 'danger')
        return redirect(url_for('admin.devices'))

    device.is_enabled = not device.is_enabled
    current_app.db_session.commit()
    state = 'enabled' if device.is_enabled else 'disabled'
    flash(f'Device {state}.', 'success')
    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_device(device_id):
    from flask import current_app
    device = current_app.db_session.get(Device, device_id)
    if not device:
        flash('Device not found.', 'danger')
        return redirect(url_for('admin.devices'))

    current_app.db_session.delete(device)
    current_app.db_session.commit()
    flash('Device deleted.', 'info')
    return redirect(url_for('admin.devices'))


# -- Port CRUD --

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
            transfer_protocol=form.transfer_protocol.data,
            max_concurrent_jobs=form.max_concurrent_jobs.data,
            max_runtime_seconds=form.max_runtime_seconds.data,
            idle_timeout_seconds=form.idle_timeout_seconds.data,
            pre_transfer_cmds=form.pre_transfer_cmds.data or None,
            post_transfer_cmds=form.post_transfer_cmds.data or None,
        )
        current_app.db_session.add(port)
        current_app.db_session.commit()
        flash('Port added.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/ports/<int:port_id>/edit',
                methods=['POST'])
@login_required
@admin_required
def edit_port(device_id, port_id):
    from flask import current_app
    port = current_app.db_session.get(DevicePort, port_id)
    if not port or port.device_id != device_id:
        flash('Port not found.', 'danger')
        return redirect(url_for('admin.devices'))

    form = DevicePortForm(obj=port)
    if form.validate_on_submit():
        port.port_label = form.port_label.data
        port.dev_path = form.dev_path.data
        port.purpose = form.purpose.data
        port.baud = form.baud.data
        port.data_bits = form.data_bits.data
        port.parity = form.parity.data
        port.stop_bits = form.stop_bits.data
        port.flow_control = form.flow_control.data
        port.newline_mode = form.newline_mode.data
        port.transfer_protocol = form.transfer_protocol.data
        port.max_concurrent_jobs = form.max_concurrent_jobs.data
        port.max_runtime_seconds = form.max_runtime_seconds.data
        port.idle_timeout_seconds = form.idle_timeout_seconds.data
        port.pre_transfer_cmds = form.pre_transfer_cmds.data or None
        port.post_transfer_cmds = form.post_transfer_cmds.data or None
        port.is_enabled = form.is_enabled.data
        current_app.db_session.commit()
        flash('Port updated.', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')

    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/ports/<int:port_id>/toggle',
                methods=['POST'])
@login_required
@admin_required
def toggle_port(device_id, port_id):
    from flask import current_app
    port = current_app.db_session.get(DevicePort, port_id)
    if not port or port.device_id != device_id:
        flash('Port not found.', 'danger')
        return redirect(url_for('admin.devices'))

    port.is_enabled = not port.is_enabled
    current_app.db_session.commit()
    state = 'enabled' if port.is_enabled else 'disabled'
    flash(f'Port {state}.', 'success')
    return redirect(url_for('admin.devices'))


@admin_bp.route('/devices/<int:device_id>/ports/<int:port_id>/delete',
                methods=['POST'])
@login_required
@admin_required
def delete_port(device_id, port_id):
    from flask import current_app
    port = current_app.db_session.get(DevicePort, port_id)
    if not port or port.device_id != device_id:
        flash('Port not found.', 'danger')
        return redirect(url_for('admin.devices'))

    current_app.db_session.delete(port)
    current_app.db_session.commit()
    flash('Port deleted.', 'info')
    return redirect(url_for('admin.devices'))


@admin_bp.route('/jobs')
@login_required
@admin_required
def jobs():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('search', '').strip()
    device_filter = request.args.get('device_id', '').strip()

    query = current_app.db_session.query(Job).order_by(Job.created_at.desc())

    if status_filter:
        query = query.filter_by(status=status_filter)

    if search:
        query = query.filter(
            Job.original_filename.ilike(f'%{search}%') |
            Job.user.has(username=search)
        )

    if device_filter:
        query = query.filter_by(device_id=int(device_filter))

    total = query.count()
    jobs_list = query.offset((page - 1) * per_page).limit(per_page).all()

    # Status counts for filter tabs
    status_counts = {}
    for s in ('queued', 'running', 'completed', 'failed', 'canceled'):
        status_counts[s] = current_app.db_session.query(Job).filter_by(
            status=s).count()

    devices = current_app.db_session.query(Device).order_by(Device.name).all()

    return render_template('admin/jobs.html', jobs=jobs_list, total=total,
                           page=page, pages=(total + per_page - 1) // per_page,
                           status=status_filter, search=search,
                           device_id=device_filter, devices=devices,
                           status_counts=status_counts,
                           per_page=per_page)


@admin_bp.route('/jobs/bulk-cancel', methods=['POST'])
@login_required
@admin_required
def bulk_cancel_jobs():
    from flask import current_app
    ids = request.form.getlist('job_ids')
    count = 0
    for job_id in ids:
        job = current_app.db_session.get(Job, int(job_id))
        if job and job.status in ('queued', 'running'):
            job.status = 'canceled'
            count += 1
    current_app.db_session.commit()
    flash(f'{count} job(s) canceled.', 'info')
    return redirect(url_for('admin.jobs'))


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


SETTING_MAP = {
    'max_upload_size_mb': ('MAX_UPLOAD_SIZE_BYTES', lambda v: str(v * 1024 * 1024)),
    'default_max_queued_jobs': ('DEFAULT_MAX_QUEUED_JOBS', str),
    'default_max_terminal_sessions': ('DEFAULT_MAX_TERMINAL_SESSIONS', str),
    'max_jobs_per_hour': ('MAX_JOBS_PER_HOUR', str),
    'max_terminal_session_minutes': ('MAX_TERMINAL_SESSION_SECONDS', lambda v: str(v * 60)),
    'terminal_idle_timeout_minutes': ('TERMINAL_IDLE_TIMEOUT_SECONDS', lambda v: str(v * 60)),
    'worker_poll_seconds': ('WORKER_POLL_SECONDS', str),
    'registration_open': ('REGISTRATION_OPEN', lambda v: '1' if v else '0'),
    'maintenance_mode': ('MAINTENANCE_MODE', lambda v: '1' if v else '0'),
}

SETTING_REVERSE = {
    'MAX_UPLOAD_SIZE_BYTES': lambda v: int(v) // (1024 * 1024),
    'DEFAULT_MAX_QUEUED_JOBS': int,
    'DEFAULT_MAX_TERMINAL_SESSIONS': int,
    'MAX_JOBS_PER_HOUR': int,
    'MAX_TERMINAL_SESSION_SECONDS': lambda v: int(v) // 60,
    'TERMINAL_IDLE_TIMEOUT_SECONDS': lambda v: int(v) // 60,
    'WORKER_POLL_SECONDS': int,
    'REGISTRATION_OPEN': lambda v: str(v).lower() in ('1', 'true', 'yes', 'on'),
    'MAINTENANCE_MODE': lambda v: str(v).lower() in ('1', 'true', 'yes', 'on'),
}


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    from flask import current_app
    form = SettingsForm()

    if request.method == 'GET':
        for field_name, (key, _) in SETTING_MAP.items():
            setting = current_app.db_session.get(AdminSetting, key)
            if setting and field_name in form._fields:
                converter = SETTING_REVERSE.get(key, str)
                form._fields[field_name].data = converter(setting.value)
    elif form.validate_on_submit():
        for field_name, (key, formatter) in SETTING_MAP.items():
            if field_name not in form._fields:
                continue
            value = str(formatter(form._fields[field_name].data))
            setting = current_app.db_session.get(AdminSetting, key)
            if setting:
                setting.value = value
            else:
                current_app.db_session.add(AdminSetting(key=key, value=value))
        current_app.db_session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', form=form)
