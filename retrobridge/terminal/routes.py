from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from retrobridge.terminal import terminal_bp
from retrobridge.models import Device, DevicePort, TerminalSession


@terminal_bp.route('/')
@login_required
def index():
    from flask import current_app
    devices = current_app.db_session.query(Device).filter_by(is_enabled=True).all()

    device_list = []
    for d in devices:
        interactive_ports = [p for p in d.ports if p.purpose == 'interactive' and p.is_enabled]
        if not interactive_ports:
            continue
        active_count = (
            current_app.db_session.query(TerminalSession)
            .filter_by(device_id=d.id, status='active')
            .count()
        )
        available = len(interactive_ports) - active_count
        device_list.append({
            'id': d.id,
            'name': d.name,
            'display_name': d.display_name or d.name,
            'available_ports': available,
            'total_ports': len(interactive_ports),
        })

    active_session = (
        current_app.db_session.query(TerminalSession)
        .filter_by(user_id=current_user.id, status='active')
        .first()
    )

    recent_sessions = (
        current_app.db_session.query(TerminalSession)
        .filter_by(user_id=current_user.id)
        .order_by(TerminalSession.connected_at.desc())
        .limit(10)
        .all()
    )

    return render_template('terminal/index.html', devices=device_list,
                           active_session=active_session,
                           recent_sessions=recent_sessions)


@terminal_bp.route('/<int:device_id>')
@login_required
def session(device_id):
    from flask import current_app
    import json

    device = current_app.db_session.get(Device, device_id)
    if not device:
        flash('Device not found.', 'danger')
        return redirect(url_for('terminal.index'))

    interactive_ports = [p for p in device.ports if p.purpose == 'interactive' and p.is_enabled]
    if not interactive_ports:
        flash('No interactive ports available for this device.', 'warning')
        return redirect(url_for('terminal.index'))

    prefs = {}
    if current_user.preferences:
        try:
            prefs = json.loads(current_user.preferences)
        except json.JSONDecodeError:
            pass

    return render_template('terminal/session.html', device=device,
                           terminal_font_size=prefs.get('terminal_font_size', 14),
                           terminal_color_scheme=prefs.get('terminal_color_scheme', 'dark'))
