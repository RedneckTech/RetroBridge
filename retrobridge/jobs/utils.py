"""Job utility functions — create, query, cancel, and rate-limit jobs."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.utils import secure_filename

from retrobridge.models import Job

ALLOWED_EXTENSIONS = {'bin', 'hex', 'obj', 'asm', 's', 'txt'}
TEXT_EXTENSIONS = {'txt', 'asm', 's', 'hex'}
BINARY_EXTENSIONS = {'bin', 'obj'}

# Signatures of modern executable formats — reject these as they are
# clearly not vintage minicomputer programs.
_REJECT_SIGNATURES = (
    (0, b'\x7fELF', 'ELF executable'),
    (0, b'MZ', 'DOS/PE executable'),
    (0, b'\xcf\xfa\xed\xfe', 'Mach-O 64-bit executable'),
    (0, b'\xce\xfa\xed\xfe', 'Mach-O 32-bit executable'),
    (0, b'\xfe\xed\xfa\xce', 'Mach-O 64-bit (reverse)'),
    (0, b'\xfe\xed\xfa\xcf', 'Mach-O 32-bit (reverse)'),
    (0, b'\xca\xfe\xba\xbe', 'Mach-O universal binary'),
    (0, b'\xbe\xba\xfe\xca', 'Mach-O universal (reverse)'),
    (0, b'\x00\x00\x01\x00', 'Windows icon'),
    (0, b'PK\x03\x04', 'ZIP archive'),
    (0, b'\x1f\x8b', 'gzip archive'),
    (0, b'Rar!\x1a\x07', 'RAR archive'),
    (0, b'\xed\xab\xee\xdb', 'RPM package'),
    (0, b'BZh', 'bzip2 archive'),
    (0, b'\x89PNG', 'PNG image'),
    (0, b'\xff\xd8\xff', 'JPEG image'),
    (0, b'GIF8', 'GIF image'),
    (0, b'%PDF', 'PDF document'),
    (0, b'\xd0\xcf\x11\xe0', 'OLE2/MS Office document'),
)

_MIN_UPLOAD_READ = 1024


def validate_file_content(file_storage, filename):
    """Validate uploaded file content against allowed types.

    Checks performed:
      1. Reject files with modern executable/archive/image signatures
         regardless of extension.
      2. For text-extension files (``.txt``, ``.asm``, ``.s``, ``.hex``),
         verify the content is plain text (no null bytes,
         ASCII-compatible).
      3. For ``.hex`` files, verify the first non-whitespace character
         is ``:`` (Intel HEX format) or the file is ASCII text.

    Returns ``None`` on success.  Raises ``ValueError`` with a
    human-readable message on rejection.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f'Unsupported file type: .{ext}')

    try:
        file_storage.seek(0)
        header = file_storage.read(_MIN_UPLOAD_READ)
        file_storage.seek(0)
    except Exception:
        raise ValueError('Unable to read file content')

    if not header:
        raise ValueError('File is empty')

    # --- Check for modern executable / archive / image signatures ---
    for offset, sig, label in _REJECT_SIGNATURES:
        if len(header) >= offset + len(sig):
            if header[offset:offset + len(sig)] == sig:
                raise ValueError(f'File appears to be a {label} — not allowed')

    # --- Text extension checks ---
    if ext in TEXT_EXTENSIONS:
        # Detect binary content: null bytes or high-bit bytes without
        # any printable ASCII structure.
        if b'\x00' in header:
            raise ValueError(
                f'File has a .{ext} extension but contains binary data '
                '(null bytes detected). Only plain text is accepted '
                'for this file type.'
            )
        try:
            header.decode('ascii')
        except UnicodeDecodeError:
            text = header.decode('utf-8', errors='replace')
            if '\ufffd' in text:
                raise ValueError(
                    f'File has a .{ext} extension but contains non-text '
                    'data. Only plain ASCII text is accepted for this '
                    'file type.'
                )

        # Intel HEX specific: first non-whitespace char must be ':'
        if ext == 'hex':
            stripped = header.lstrip()
            if stripped and stripped[0:1] != b':':
                raise ValueError(
                    'Intel HEX files must begin with a colon (:). '
                    'The uploaded file does not appear to be in Intel '
                    'HEX format.'
                )



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

    max_jobs = user.max_queued_jobs
    if user.patreon_tier:
        from retrobridge.integrations.patreon import get_tier_limits
        tier_jobs, _ = get_tier_limits(user.patreon_tier)
        if tier_jobs and tier_jobs > max_jobs:
            max_jobs = tier_jobs

    return (
        queued_running,
        max_jobs,
        queued_running >= max_jobs,
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
               upload_dir, priority=0, newline_mode='',
               pre_transfer_cmds='', post_transfer_cmds=''):
    safe_name = secure_filename(filename or 'program.bin')

    validate_file_content(file_obj, safe_name)

    from retrobridge.admin.settings_utils import get_int
    max_size = get_int('MAX_UPLOAD_SIZE_BYTES')
    if max_size > 0:
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)
        if size > max_size:
            raise ValueError(
                f'File size ({size} bytes) exceeds maximum '
                f'({max_size} bytes).'
            )

    job = Job(
        user_id=user_id,
        device_id=device_id,
        original_filename=safe_name,
        status='queued',
        priority=priority or 0,
        override_newline_mode=newline_mode or None,
        override_pre_transfer_cmds=pre_transfer_cmds or None,
        override_post_transfer_cmds=post_transfer_cmds or None,
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

    if job.status in ('completed', 'failed', 'canceled'):
        return False, 'Job already finished'

    if job.cancel_requested:
        return False, 'Cancellation already requested'

    if job.status == 'queued':
        job.cancel_requested = True
        job.status = 'canceled'
        db_session.commit()
        return True, 'Job canceled'

    if job.status == 'running' and is_admin:
        job.cancel_requested = True
        db_session.commit()
        return True, 'Cancellation requested — worker will stop shortly'

    return False, 'Cannot cancel a running job'


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


def get_device_stats(db_session):
    from retrobridge.models import Device, DevicePort, TerminalSession
    devices = db_session.query(Device).filter_by(is_enabled=True).order_by(Device.name).all()
    stats = []
    for d in devices:
        ports = db_session.query(DevicePort).filter_by(device_id=d.id).all()
        job_ports = [p for p in ports if p.purpose == 'job_queue']
        interactive_ports = [p for p in ports if p.purpose == 'interactive' and p.is_enabled]
        active_sessions = db_session.query(TerminalSession).filter_by(
            device_id=d.id, status='active').count()
        queue_count = db_session.query(Job).filter_by(
            device_id=d.id, status='queued').count()
        running_count = db_session.query(Job).filter_by(
            device_id=d.id, status='running').count()
        stats.append({
            'id': d.id,
            'name': d.name,
            'display_name': d.display_name or d.name,
            'is_enabled': d.is_enabled,
            'queue_count': queue_count,
            'running_count': running_count,
            'interactive_ports': len(interactive_ports),
            'interactive_available': max(0, len(interactive_ports) - active_sessions),
            'job_ports': len(job_ports),
            'ports': [{
                'label': p.port_label,
                'purpose': p.purpose,
                'baud': p.baud,
                'transport': p.transport or 'serial',
                'is_enabled': p.is_enabled,
                'pre_cmds': p.pre_transfer_cmds,
                'post_cmds': p.post_transfer_cmds,
                'newline_mode': p.newline_mode,
                'transfer_protocol': p.transfer_protocol,
            } for p in ports],
        })
    return stats
