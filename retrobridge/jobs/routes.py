from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

import os

from retrobridge.jobs import jobs_bp
from retrobridge.jobs.forms import JobUploadForm
from retrobridge.jobs.utils import (
    cancel_job, check_rate_limit, create_job, get_device_choices,
    get_device_stats, get_job_or_403, get_user_quota, load_output_content,
)
from retrobridge.models import Job, TerminalSession


@jobs_bp.route('/dashboard')
@login_required
def dashboard():
    from datetime import datetime, timezone
    from flask import current_app
    jobs = (
        current_app.db_session.query(Job)
        .filter_by(user_id=current_user.id)
        .order_by(Job.created_at.desc())
        .limit(50)
        .all()
    )
    device_stats = get_device_stats(current_app.db_session)

    active_sessions = (
        current_app.db_session.query(TerminalSession)
        .filter_by(user_id=current_user.id, status='active')
        .all()
    )

    now_utc = datetime.now(timezone.utc)
    active_session_info = []
    for s in active_sessions:
        elapsed = 0
        if s.connected_at:
            conn = s.connected_at
            if conn.tzinfo is None:
                conn = conn.replace(tzinfo=timezone.utc)
            elapsed = int((now_utc - conn).total_seconds())
        active_session_info.append({'session': s, 'elapsed': elapsed})

    total = len(jobs)
    completed = sum(1 for j in jobs if j.status == 'completed')
    failed = sum(1 for j in jobs if j.status == 'failed')
    queued = sum(1 for j in jobs if j.status == 'queued')
    running = sum(1 for j in jobs if j.status == 'running')

    stats = {
        'total': total,
        'completed': completed,
        'failed': failed,
        'queued': queued,
        'running': running,
        'success_rate': round(completed / max(total, 1) * 100),
        'active_sessions': len(active_sessions),
        'max_jobs': current_user.max_queued_jobs,
        'max_sessions': current_user.max_terminal_sessions,
    }

    job_elapsed = {}
    for j in jobs:
        if j.status == 'running' and j.started_at:
            started = j.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            job_elapsed[j.id] = int((now_utc - started).total_seconds())
        else:
            job_elapsed[j.id] = j.runtime_seconds

    return render_template('jobs/dashboard.html',
                           jobs=jobs, device_stats=device_stats,
                           active_session_info=active_session_info,
                           stats=stats, job_elapsed=job_elapsed)


@jobs_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    from flask import current_app
    from retrobridge.admin.settings_utils import get_int

    form = JobUploadForm()
    _, devices = get_device_choices(current_app.db_session)
    form.device_id.choices = get_device_choices(current_app.db_session)[0]

    device_stats = get_device_stats(current_app.db_session)
    queued_running, max_quota, _ = get_user_quota(
        current_app.db_session, current_user)
    rate_limited, max_per_hour = check_rate_limit(
        current_app.db_session, current_user.id)
    last_job = (
        current_app.db_session.query(Job)
        .filter_by(user_id=current_user.id)
        .order_by(Job.created_at.desc())
        .first()
    )
    max_upload = get_int('MAX_UPLOAD_SIZE_BYTES') or (8 * 1024 * 1024)

    ctx = dict(
        form=form,
        device_stats=device_stats,
        quota_used=queued_running,
        quota_max=max_quota,
        last_job=last_job,
        max_per_hour=max_per_hour,
        max_upload_bytes=max_upload,
        max_upload_mb=max_upload // (1024 * 1024),
    )

    if form.validate_on_submit():
        file = form.file.data
        device_id = form.device_id.data

        if check_rate_limit(current_app.db_session, current_user.id)[0]:
            flash(
                f'Rate limit reached: {max_per_hour} jobs per hour. '
                'Please wait before submitting another job.',
                'danger',
            )
            return render_template('jobs/new.html', **ctx)

        _, _, exceeded = get_user_quota(current_app.db_session, current_user)
        if exceeded:
            flash('You have reached your maximum number of queued/running jobs.', 'danger')
            return render_template('jobs/new.html', **ctx)

        filename = file.filename or 'program.bin'
        try:
            job = create_job(
                current_app.db_session, current_user.id, device_id,
                filename, file, current_app.config['UPLOAD_DIR'],
                priority=form.priority.data or 0,
                newline_mode=form.newline_mode.data or '',
                pre_transfer_cmds=form.pre_transfer_cmds.data or '',
                post_transfer_cmds=form.post_transfer_cmds.data or '',
            )
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template('jobs/new.html', **ctx)

        flash(f'Job #{job.id} submitted successfully.', 'success')
        return redirect(url_for('jobs.detail', job_id=job.id))

    return render_template('jobs/new.html', **ctx)


@jobs_bp.route('/<int:job_id>')
@login_required
def detail(job_id):
    from flask import current_app
    job, error = get_job_or_403(current_app.db_session, job_id,
                                 current_user.id, current_user.is_admin)
    if not job:
        if error == 404:
            flash('Job not found.', 'danger')
            return redirect(url_for('jobs.dashboard'))
        from flask import abort
        abort(403)

    output_content = load_output_content(job)
    return render_template('jobs/detail.html', job=job,
                           output_content=output_content)


@jobs_bp.route('/<int:job_id>/download')
@login_required
def download(job_id):
    from flask import current_app, send_from_directory
    job, error = get_job_or_403(current_app.db_session, job_id,
                                 current_user.id, current_user.is_admin)
    if not job:
        from flask import abort
        abort(error)

    if not job.output_path:
        flash('No output available for this job.', 'warning')
        return redirect(url_for('jobs.detail', job_id=job.id))

    directory = os.path.dirname(job.output_path)
    filename = os.path.basename(job.output_path)
    return send_from_directory(directory, filename, as_attachment=True,
                               download_name=f'job-{job.id}-output.log')


@jobs_bp.route('/<int:job_id>/cancel', methods=['POST'])
@login_required
def cancel(job_id):
    from flask import current_app
    success, message = cancel_job(current_app.db_session, job_id,
                                   current_user.id)
    if not success:
        if message == 'Not authorized':
            from flask import abort
            abort(403)
        flash(message, 'warning')
    else:
        flash(message, 'info')
    return redirect(url_for('jobs.detail', job_id=job_id))
