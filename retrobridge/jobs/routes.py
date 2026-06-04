from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from retrobridge.jobs import jobs_bp
from retrobridge.jobs.forms import JobUploadForm
from retrobridge.models import Device, Job


@jobs_bp.route('/')
@login_required
def dashboard():
    from flask import current_app
    jobs = (
        current_app.db_session.query(Job)
        .filter_by(user_id=current_user.id)
        .order_by(Job.created_at.desc())
        .limit(50)
        .all()
    )
    devices = current_app.db_session.query(Device).filter_by(is_enabled=True).all()
    return render_template('jobs/dashboard.html', jobs=jobs, devices=devices)


@jobs_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    from flask import current_app
    form = JobUploadForm()
    devices = current_app.db_session.query(Device).filter_by(is_enabled=True).all()
    form.device_id.choices = [(d.id, d.display_name or d.name) for d in devices]

    if form.validate_on_submit():
        file = form.file.data
        filename = secure_filename(file.filename or 'program.bin')
        device_id = form.device_id.data

        # Check quota
        queued_running = (
            current_app.db_session.query(Job)
            .filter_by(user_id=current_user.id)
            .filter(Job.status.in_(['queued', 'running']))
            .count()
        )
        if queued_running >= current_user.max_queued_jobs:
            flash('You have reached your maximum number of queued/running jobs.', 'danger')
            return render_template('jobs/new.html', form=form, devices=devices)

        job = Job(
            user_id=current_user.id,
            device_id=device_id,
            original_filename=filename,
            status='queued',
        )
        current_app.db_session.add(job)
        current_app.db_session.flush()

        upload_dir = current_app.config['UPLOAD_DIR']
        from pathlib import Path
        job_dir = Path(upload_dir) / f'job-{job.id}'
        job_dir.mkdir(parents=True, exist_ok=True)
        file_path = job_dir / filename
        file.save(str(file_path))

        job.stored_filename = str(file_path.relative_to(upload_dir))
        job.file_size_bytes = file_path.stat().st_size
        current_app.db_session.commit()

        flash(f'Job #{job.id} submitted successfully.', 'success')
        return redirect(url_for('jobs.detail', job_id=job.id))

    return render_template('jobs/new.html', form=form, devices=devices)


@jobs_bp.route('/<int:job_id>')
@login_required
def detail(job_id):
    from flask import current_app
    job = current_app.db_session.get(Job, job_id)
    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('jobs.dashboard'))

    if job.user_id != current_user.id and not current_user.is_admin:
        from flask import abort
        abort(403)

    return render_template('jobs/detail.html', job=job)


@jobs_bp.route('/<int:job_id>/download')
@login_required
def download(job_id):
    from flask import current_app, send_from_directory
    job = current_app.db_session.get(Job, job_id)
    if not job or (job.user_id != current_user.id and not current_user.is_admin):
        from flask import abort
        abort(403)

    if not job.output_path:
        flash('No output available for this job.', 'warning')
        return redirect(url_for('jobs.detail', job_id=job.id))

    import os
    directory = os.path.dirname(job.output_path)
    filename = os.path.basename(job.output_path)
    return send_from_directory(directory, filename, as_attachment=True,
                               download_name=f'job-{job.id}-output.log')


@jobs_bp.route('/<int:job_id>/cancel', methods=['POST'])
@login_required
def cancel(job_id):
    from flask import current_app
    job = current_app.db_session.get(Job, job_id)
    if not job or job.user_id != current_user.id:
        from flask import abort
        abort(403)

    if job.status == 'queued':
        job.status = 'canceled'
        current_app.db_session.commit()
        flash('Job canceled.', 'info')
    else:
        flash('Cannot cancel a running or completed job.', 'warning')

    return redirect(url_for('jobs.detail', job_id=job.id))
