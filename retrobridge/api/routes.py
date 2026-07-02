import json
import os
import time

from flask import jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user

from retrobridge.api import api_bp
from retrobridge.models import Job, Device, DevicePort, TerminalSession, User


@api_bp.route('/jobs')
@login_required
def list_jobs():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = current_app.db_session.query(Job)
    if not current_user.is_admin:
        query = query.filter_by(user_id=current_user.id)

    query = query.order_by(Job.created_at.desc())
    total = query.count()
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'jobs': [{
            'id': j.id,
            'status': j.status,
            'device_id': j.device_id,
            'original_filename': j.original_filename,
            'created_at': j.created_at.isoformat() if j.created_at else None,
            'priority': j.priority,
        } for j in jobs],
        'total': total,
        'pages': (total + per_page - 1) // per_page,
        'current_page': page,
    })


@api_bp.route('/jobs/<int:job_id>/status')
@login_required
def job_status(job_id):
    from flask import current_app
    job = current_app.db_session.get(Job, job_id)
    if not job or (job.user_id != current_user.id and not current_user.is_admin):
        return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'id': job.id,
        'status': job.status,
        'device': job.device.name if job.device else None,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'runtime_seconds': job.runtime_seconds,
        'error_message': job.error_message,
    })


@api_bp.route('/jobs/<int:job_id>/output')
@login_required
def job_output(job_id):
    from flask import current_app
    job = current_app.db_session.get(Job, job_id)
    if not job or (job.user_id != current_user.id and not current_user.is_admin):
        return jsonify({'error': 'Not found'}), 404

    if not job.output_path:
        return jsonify({'lines': []})

    try:
        with open(job.output_path, 'r') as f:
            tail = request.args.get('tail', type=int)
            if tail:
                lines = f.readlines()
                lines = lines[-tail:] if len(lines) > tail else lines
            else:
                lines = f.readlines()
    except FileNotFoundError:
        lines = []

    return jsonify({'lines': [l.rstrip('\n') for l in lines]})


@api_bp.route('/devices')
@login_required
def list_devices():
    from flask import current_app
    devices = current_app.db_session.query(Device).filter_by(is_enabled=True).all()

    result = []
    for d in devices:
        interactive_ports = [p for p in d.ports if p.purpose == 'interactive' and p.is_enabled]
        active_sessions = (
            current_app.db_session.query(TerminalSession)
            .filter_by(device_id=d.id, status='active')
            .count()
        )
        queue_length = (
            current_app.db_session.query(Job)
            .filter_by(device_id=d.id, status='queued')
            .count()
        )
        running_jobs = (
            current_app.db_session.query(Job)
            .filter_by(device_id=d.id, status='running')
            .count()
        )

        result.append({
            'id': d.id,
            'name': d.name,
            'display_name': d.display_name,
            'is_enabled': d.is_enabled,
            'interactive_ports_available': len(interactive_ports) - active_sessions,
            'interactive_ports_total': len(interactive_ports),
            'queue_length': queue_length,
            'running_jobs': running_jobs,
        })

    return jsonify({'devices': result})


@api_bp.route('/devices/<int:device_id>/ports')
@login_required
def device_ports(device_id):
    from flask import current_app
    device = current_app.db_session.get(Device, device_id)
    if not device:
        return jsonify({'error': 'Not found'}), 404

    ports = []
    for p in device.ports:
        in_use = (
            current_app.db_session.query(TerminalSession)
            .filter_by(port_id=p.id, status='active')
            .count() > 0
        ) if p.purpose == 'interactive' else False

        ports.append({
            'id': p.id,
            'label': p.port_label,
            'purpose': p.purpose,
            'is_enabled': p.is_enabled,
            'in_use': in_use,
            'baud': p.baud,
            'parity': p.parity,
            'flow_control': p.flow_control,
        })

    return jsonify({'ports': ports})


@api_bp.route('/jobs', methods=['POST'])
@login_required
def create_job():
    from flask import current_app, redirect, url_for
    # This is handled by the jobs blueprint upload form
    # API-based upload would go here
    return jsonify({'error': 'Use the web upload form at /jobs/new'}), 400


@api_bp.route('/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def cancel_job(job_id):
    from flask import current_app
    job = current_app.db_session.get(Job, job_id)
    if not job or (job.user_id != current_user.id and not current_user.is_admin):
        return jsonify({'success': False, 'message': 'Not found'}), 404

    if job.status == 'queued':
        job.status = 'canceled'
        current_app.db_session.commit()
        return jsonify({'success': True, 'message': 'Job canceled'})
    elif job.status == 'running' and current_user.is_admin:
        job.status = 'canceled'
        current_app.db_session.commit()
        return jsonify({'success': True, 'message': 'Job force-canceled'})

    return jsonify({'success': False, 'message': 'Cannot cancel running job'}), 400


@api_bp.route('/sessions/active')
@login_required
def active_sessions():
    from flask import current_app
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    sessions = current_app.db_session.query(TerminalSession).filter_by(status='active').all()
    return jsonify({
        'sessions': [{
            'id': s.id,
            'user': s.user.username,
            'device': s.device.name if s.device else None,
            'port': s.port.port_label if s.port else None,
            'connected_at': s.connected_at.isoformat() if s.connected_at else None,
            'duration': s.duration_seconds,
        } for s in sessions],
    })


@api_bp.route('/sessions/<int:session_id>/disconnect', methods=['POST'])
@login_required
def disconnect_session(session_id):
    from flask import current_app
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    session = current_app.db_session.get(TerminalSession, session_id)
    if not session or session.status != 'active':
        return jsonify({'success': False, 'message': 'Session not found or not active'}), 404

    session.status = 'disconnected'
    session.disconnect_reason = 'admin_force'
    from datetime import datetime, timezone
    session.disconnected_at = datetime.now(timezone.utc)
    current_app.db_session.commit()

    return jsonify({'success': True, 'message': 'Session terminated'})


@api_bp.route('/admin/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def admin_cancel_job(job_id):
    from flask import current_app
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    job = current_app.db_session.get(Job, job_id)
    if not job:
        return jsonify({'success': False, 'message': 'Job not found'}), 404

    job.status = 'canceled'
    current_app.db_session.commit()
    return jsonify({'success': True, 'message': 'Job force-canceled'})


@api_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    from flask import current_app
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    if user_id == current_user.id:
        return jsonify({'success': False, 'message': 'Cannot delete self'}), 400

    from retrobridge.models import User
    user = current_app.db_session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'message': 'User not found'}), 404

    current_app.db_session.delete(user)
    current_app.db_session.commit()
    return jsonify({'success': True})


@api_bp.route('/jobs/<int:job_id>/events')
@login_required
def job_events(job_id):
    """Server-Sent Events stream for live job status and output updates."""
    from flask import current_app

    job = current_app.db_session.get(Job, job_id)
    if not job or (job.user_id != current_user.id and not current_user.is_admin):
        return jsonify({'error': 'Not found'}), 404

    def _job_status_data(j):
        return {
            'id': j.id,
            'status': j.status,
            'device': j.device.name if j.device else None,
            'created_at': j.created_at.isoformat() if j.created_at else None,
            'started_at': j.started_at.isoformat() if j.started_at else None,
            'finished_at': j.finished_at.isoformat() if j.finished_at else None,
            'runtime_seconds': j.runtime_seconds,
            'error_message': j.error_message,
            'exit_code': j.exit_code,
            'output_path': bool(j.output_path),
        }

    def generate():
        last_status = job.status
        last_output_size = 0
        poll_interval = 2

        while True:
            current_app.db_session.refresh(job)

            if job.status != last_status:
                last_status = job.status
                yield f"event: status\ndata: {json.dumps(_job_status_data(job))}\n\n"

            if job.output_path:
                try:
                    current_size = os.path.getsize(job.output_path)
                except OSError:
                    current_size = last_output_size

                if current_size > last_output_size:
                    try:
                        with open(job.output_path, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_output_size)
                            new_text = f.read(current_size - last_output_size)
                            last_output_size = current_size
                            yield f"event: output\ndata: {json.dumps({'text': new_text})}\n\n"
                    except OSError:
                        pass

            if job.status in ('completed', 'failed', 'canceled'):
                yield f"event: done\ndata: {json.dumps({'status': job.status})}\n\n"
                return

            yield f": heartbeat\n\n"
            time.sleep(poll_interval)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@api_bp.route('/check-username')
def check_username():
    """Check if a username is available. Public endpoint (no auth needed)."""
    from flask import current_app
    username = request.args.get('username', '').strip()
    if not username or len(username) < 2:
        return jsonify({'available': False, 'message': 'Too short'})
    existing = current_app.db_session.query(User).filter_by(
        username=username).first()
    if existing:
        return jsonify({'available': False, 'message': 'Username taken'})
    return jsonify({'available': True, 'message': 'Available'})
