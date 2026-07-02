"""Job utility functions — create, query, cancel, and rate-limit jobs."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.utils import secure_filename

from retrobridge.models import Job


def job_status_dict(job):
    return {
        'id': job.id,
        'status': job.status,
        'device': job.device.name if job.device else None,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'runtime_seconds': job.runtime_seconds,
        'error_message': job.error_message,
        'exit_code': job.exit_code,
        'output_path': bool(job.output_path),
    }


def load_output_content(job):
    if not job.output_path:
        return ''
    try:
        with open(job.output_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def get_user_quota(db_session, user):
    queued_running = (
        db_session.query(Job)
        .filter_by(user_id=user.id)
        .filter(Job.status.in_(['queued', 'running']))
        .count()
    )
    return (
        queued_running,
        user.max_queued_jobs,
        queued_running >= user.max_queued_jobs,
    )


def check_rate_limit(db_session, user_id):
    from retrobridge.admin.settings_utils import get_int
    max_per_hour = get_int('MAX_JOBS_PER_HOUR')
    if max_per_hour <= 0:
        return False, 0

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_count = (
        db_session.query(Job)
        .filter_by(user_id=user_id)
        .filter(Job.created_at >= hour_ago)
        .count()
    )
    return recent_count >= max_per_hour, max_per_hour


def create_job(db_session, user_id, device_id, filename, file_obj,
               upload_dir, priority=0):
    safe_name = secure_filename(filename or 'program.bin')
    job = Job(
        user_id=user_id,
        device_id=device_id,
        original_filename=safe_name,
        status='queued',
        priority=priority or 0,
    )
    db_session.add(job)
    db_session.flush()

    job_dir = Path(upload_dir) / f'job-{job.id}'
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / safe_name
    file_obj.save(str(file_path))

    job.stored_filename = str(file_path.relative_to(upload_dir))
    job.file_size_bytes = file_path.stat().st_size
    db_session.commit()

    return job


def cancel_job(db_session, job_id, user_id, is_admin=False):
    job = db_session.get(Job, job_id)
    if not job:
        return False, 'Job not found'

    if job.user_id != user_id and not is_admin:
        return False, 'Not authorized'

    if job.status == 'queued':
        job.status = 'canceled'
        db_session.commit()
        return True, 'Job canceled'

    if job.status == 'running' and is_admin:
        job.status = 'canceled'
        db_session.commit()
        return True, 'Job force-canceled'

    return False, 'Cannot cancel a running or completed job'


def get_job_or_403(db_session, job_id, user_id, is_admin=False):
    job = db_session.get(Job, job_id)
    if not job:
        return None, 404
    if job.user_id != user_id and not is_admin:
        return None, 403
    return job, None


def get_device_choices(db_session):
    from retrobridge.models import Device
    devices = db_session.query(Device).filter_by(is_enabled=True).all()
    return [(d.id, d.display_name or d.name) for d in devices], devices


def read_output_tail(output_path, tail=None):
    try:
        with open(output_path, 'r') as f:
            lines = f.readlines()
            if tail:
                lines = lines[-tail:] if len(lines) > tail else lines
            return [l.rstrip('\n') for l in lines]
    except FileNotFoundError:
        return []
