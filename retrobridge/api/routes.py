import json
import os
import shutil
import time
from pathlib import Path

from flask import jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user

from retrobridge.api import api_bp
from retrobridge.jobs import utils as jobs_utils
from retrobridge.models import Job, Device, DevicePort, TerminalSession, User

MAX_PER_PAGE = 100
MAX_OUTPUT_TAIL = 10000


@api_bp.route('/jobs')
@login_required
def list_jobs():
    from flask import current_app
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), MAX_PER_PAGE)
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1

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
    job, error = jobs_utils.get_job_or_403(current_app.db_session, job_id,
                                            current_user.id, current_user.is_admin)
    if not job:
        return jsonify({'error': 'Forbidden' if error == 403 else 'Not found'}), error

    return jsonify(jobs_utils.job_status_dict(job))


@api_bp.route('/jobs/<int:job_id>/output')
@login_required
def job_output(job_id):
    from flask import current_app
    job, error = jobs_utils.get_job_or_403(current_app.db_session, job_id,
                                            current_user.id, current_user.is_admin)
    if not job:
        return jsonify({'error': 'Forbidden' if error == 403 else 'Not found'}), error

    if not job.output_path:
        return jsonify({'lines': []})

    tail = request.args.get('tail', type=int)
    if tail is not None and tail > MAX_OUTPUT_TAIL:
        tail = MAX_OUTPUT_TAIL
    lines = jobs_utils.read_output_tail(job.output_path, tail)
    return jsonify({'lines': lines})


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
    success, message = jobs_utils.cancel_job(
        current_app.db_session, job_id, current_user.id,
        is_admin=current_user.is_admin,
    )
    if not success:
        status = 404 if message == 'Job not found' else 400
        return jsonify({'success': False, 'message': message}), status
    return jsonify({'success': True, 'message': message})


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


@api_bp.route('/my-sessions')
@login_required
def my_sessions():
    """Return current user's active terminal sessions for dashboard polling."""
    from flask import current_app
    now_utc = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    sessions = (
        current_app.db_session.query(TerminalSession)
        .filter_by(user_id=current_user.id, status='active')
        .all()
    )
    return jsonify({
        'sessions': [{
            'id': s.id,
            'device_id': s.device_id,
            'device_name': s.device.display_name or s.device.name if s.device else None,
            'port_label': s.port.port_label if s.port else None,
            'elapsed_seconds': int((now_utc - (
                s.connected_at.replace(tzinfo=__import__('datetime').timezone.utc)
                if s.connected_at and s.connected_at.tzinfo is None
                else s.connected_at
            )).total_seconds()) if s.connected_at else 0,
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

    from retrobridge.terminal import utils as terminal_utils
    from retrobridge import socketio
    terminal_utils.force_disconnect_session(
        socketio, session_id, db_session=current_app.db_session,
    )

    return jsonify({'success': True, 'message': 'Session terminated'})


@api_bp.route('/admin/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def admin_cancel_job(job_id):
    from flask import current_app
    if not current_user.is_admin:
        return jsonify({'error': 'Forbidden'}), 403

    success, message = jobs_utils.cancel_job(
        current_app.db_session, job_id, current_user.id, is_admin=True,
    )
    if not success:
        return jsonify({'success': False, 'message': message}), 404
    return jsonify({'success': True, 'message': message})


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

    _delete_user_directories(current_app, user.id)

    current_app.db_session.delete(user)
    current_app.db_session.commit()
    return jsonify({'success': True})


def _delete_user_directories(app, user_id):
    """Remove a user's uploads, outputs, and session logs from disk.

    The cascade handles related DB rows; job/session files are tied to those
    IDs, so we enumerate the user's jobs and sessions and delete their dirs.
    """
    jobs = app.db_session.query(Job).filter_by(user_id=user_id).all()
    sessions = app.db_session.query(TerminalSession).filter_by(user_id=user_id).all()
    upload_dir = app.config.get('UPLOAD_DIR')
    output_dir = app.config.get('OUTPUT_DIR')
    session_log_dir = app.config.get('SESSION_LOG_DIR')
    for job in jobs:
        if upload_dir and job.stored_filename:
            p = os.path.join(upload_dir, str(Path(job.stored_filename).parent))
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        if output_dir and job.output_path:
            p = os.path.dirname(job.output_path)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
    for session in sessions:
        if session_log_dir:
            p = os.path.join(session_log_dir, f'session-{session.id}')
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)


@api_bp.route('/jobs/<int:job_id>/events')
@login_required
def job_events(job_id):
    """Server-Sent Events stream for live job status and output updates.

    NOTE: This endpoint holds a response stream open for the duration of the
    job. When running under a synchronous gunicorn worker, that ties up one
    worker thread per connected client. Run the app with an async worker class
    (eventlet/gevent) in production, e.g.:

        gunicorn -k eventlet -w 4 -b 127.0.0.1:5000 wsgi_eventlet:app

    The poll interval and optional maximum connection lifetime are configurable
    via ``JOB_EVENTS_POLL_INTERVAL`` and ``JOB_EVENTS_MAX_LIFETIME``.
    """
    from flask import current_app

    job, error = jobs_utils.get_job_or_403(current_app.db_session, job_id,
                                            current_user.id, current_user.is_admin)
    if not job:
        return jsonify({'error': 'Forbidden' if error == 403 else 'Not found'}), error

    poll_interval = current_app.config.get('JOB_EVENTS_POLL_INTERVAL', 1.0)
    max_lifetime = current_app.config.get('JOB_EVENTS_MAX_LIFETIME')

    # Use eventlet/gevent sleep when available so the greenlet yields instead
    # of blocking an OS thread.
    try:
        from eventlet import sleep as sse_sleep
    except Exception:
        sse_sleep = time.sleep

    def generate():
        last_status = job.status
        last_output_size = 0
        started_at = time.time()

        while True:
            current_app.db_session.refresh(job)

            if job.status != last_status:
                last_status = job.status
                yield f"event: status\ndata: {json.dumps(jobs_utils.job_status_dict(job))}\n\n"

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

            if max_lifetime and (time.time() - started_at) > max_lifetime:
                yield f"event: done\ndata: {json.dumps({'status': job.status, 'reason': 'timeout'})}\n\n"
                return

            yield f": heartbeat\n\n"
            sse_sleep(poll_interval)

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
