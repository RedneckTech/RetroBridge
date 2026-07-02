from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

import os

from retrobridge.jobs import jobs_bp
from retrobridge.jobs.forms import JobUploadForm
from retrobridge.jobs.utils import (
    cancel_job, check_rate_limit, create_job, get_device_choices,
    get_job_or_403, get_user_quota, load_output_content,
)
from retrobridge.models import Job


@jobs_bp.route('/dashboard')
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
    _, devices = get_device_choices(current_app.db_session)
    return render_template('jobs/dashboard.html', jobs=jobs, devices=devices)


@jobs_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    from flask import current_app

    form = JobUploadForm()
    _, devices = get_device_choices(current_app.db_session)
    form.device_id.choices = get_device_choices(current_app.db_session)[0]

    if form.validate_on_submit():
        file = form.file.data
        device_id = form.device_id.data

        rate_limited, max_per_hour = check_rate_limit(
            current_app.db_session, current_user.id)
        if rate_limited:
            flash(
                f'Rate limit reached: {max_per_hour} jobs per hour. '
                'Please wait before submitting another job.',
                'danger',
            )
            return render_template('jobs/new.html', form=form,
                                   devices=devices)

        _, _, exceeded = get_user_quota(current_app.db_session, current_user)
        if exceeded:
            flash('You have reached your maximum number of queued/running jobs.', 'danger')
            return render_template('jobs/new.html', form=form,
                                   devices=devices)

        filename = file.filename or 'program.bin'
        try:
            job = create_job(
                current_app.db_session, current_user.id, device_id,
                filename, file, current_app.config['UPLOAD_DIR'],
                priority=form.priority.data or 0,
            )
        except ValueError as e:
            flash(str(e), 'danger')
            return render_template('jobs/new.html', form=form,
                                   devices=devices)

        flash(f'Job #{job.id} submitted successfully.', 'success')
        return redirect(url_for('jobs.detail', job_id=job.id))

    return render_template('jobs/new.html', form=form, devices=devices)


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
