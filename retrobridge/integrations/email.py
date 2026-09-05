"""
Email Notification System
==========================
SMTP-based email sending for job completion and account security
notifications. Configured via AdminSetting table. Disabled when
SMTP host is empty.

All sends are dispatched through a bounded thread pool to avoid blocking
responses. Settings are read in the caller's context and passed to the
worker thread so sends work from background workers and Flask routes.
"""

import logging
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)

# Bounded thread pool for outbound email. Limit prevents bursts of events
# from exhausting OS threads or SMTP connections.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='email-sender')


def _get_setting(key, default=''):
    from retrobridge.admin.settings_utils import _get_raw
    return _get_raw(key) or default


def _load_settings():
    """Read all email settings from the current Flask app context."""
    return {
        'smtp_host': _get_setting('EMAIL_SMTP_HOST'),
        'smtp_port': int(_get_setting('EMAIL_SMTP_PORT') or 587),
        'smtp_user': _get_setting('EMAIL_SMTP_USER'),
        'smtp_password': _get_setting('EMAIL_SMTP_PASSWORD'),
        'use_tls': _get_setting('EMAIL_USE_TLS') in ('1', 'true', 'yes', 'on'),
        'use_ssl': _get_setting('EMAIL_USE_SSL') in ('1', 'true', 'yes', 'on'),
        'from_address': _get_setting('EMAIL_FROM_ADDRESS', 'noreply@retrobridge.local'),
        'from_name': _get_setting('EMAIL_FROM_NAME', 'RetroBridge'),
    }


def _load_settings_from_db(session):
    """Read all email settings using a plain SQLAlchemy session (worker-safe)."""
    from retrobridge.models import AdminSetting

    keys = [
        'EMAIL_SMTP_HOST', 'EMAIL_SMTP_PORT', 'EMAIL_SMTP_USER',
        'EMAIL_SMTP_PASSWORD', 'EMAIL_USE_TLS', 'EMAIL_USE_SSL',
        'EMAIL_FROM_ADDRESS', 'EMAIL_FROM_NAME',
    ]
    settings = {}
    for key in keys:
        s = session.get(AdminSetting, key)
        settings[key] = s.value if s else ''

    return {
        'smtp_host': settings['EMAIL_SMTP_HOST'],
        'smtp_port': int(settings['EMAIL_SMTP_PORT'] or 587),
        'smtp_user': settings['EMAIL_SMTP_USER'],
        'smtp_password': settings['EMAIL_SMTP_PASSWORD'],
        'use_tls': settings['EMAIL_USE_TLS'].lower() in ('1', 'true', 'yes', 'on'),
        'use_ssl': settings['EMAIL_USE_SSL'].lower() in ('1', 'true', 'yes', 'on'),
        'from_address': settings['EMAIL_FROM_ADDRESS'] or 'noreply@retrobridge.local',
        'from_name': settings['EMAIL_FROM_NAME'] or 'RetroBridge',
    }


def _send_email(to_address, subject, body_text, settings):
    try:
        msg = MIMEText(body_text, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = formataddr((settings['from_name'], settings['from_address']))
        msg['To'] = to_address

        if settings.get('use_ssl'):
            server = smtplib.SMTP_SSL(
                settings['smtp_host'], settings['smtp_port'], timeout=15
            )
        else:
            server = smtplib.SMTP(
                settings['smtp_host'], settings['smtp_port'], timeout=15
            )

        if settings.get('use_tls'):
            server.starttls()

        if settings['smtp_user'] and settings['smtp_password']:
            server.login(settings['smtp_user'], settings['smtp_password'])

        server.sendmail(settings['from_address'], [to_address], msg.as_string())
        server.quit()
        logger.info('Email sent to %s: %s', to_address, subject)
    except Exception:
        logger.exception('Failed to send email to %s', to_address)


def send_email(to_address, subject, body_text, settings=None):
    if settings is None:
        settings = _load_settings()

    smtp_host = settings.get('smtp_host')
    if not smtp_host:
        return

    _executor.submit(_send_email, to_address, subject, body_text, settings)


def send_email_from_worker(session, to_address, subject, body_text):
    """Worker-safe entry point that reads settings from the provided DB session."""
    settings = _load_settings_from_db(session)
    send_email(to_address, subject, body_text, settings=settings)


def notify_job_completed(user, job, settings=None):
    status_emoji = '\u2705' if job.status == 'completed' else '\u274c'
    status_text = 'completed' if job.status == 'completed' else 'failed'
    runtime = f'{job.runtime_seconds} seconds' if job.runtime_seconds else 'N/A'

    body = (
        f'Your job has {status_text}.\n\n'
        f'  Program:   {job.original_filename}\n'
        f'  Device:    {job.device.display_name or job.device.name if job.device else "N/A"}\n'
        f'  Submitted: {job.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if job.created_at else "N/A"}\n'
        f'  Finished:  {job.finished_at.strftime("%Y-%m-%d %H:%M:%S UTC") if job.finished_at else "N/A"}\n'
        f'  Runtime:   {runtime}\n'
        f'  Status:    {status_emoji} {status_text.title()}\n'
    )

    if job.status == 'failed' and job.error_message:
        body += f'\n  Error: {job.error_message}\n'

    body += '\n\u2014\nRetroBridge \u2014 Bridging modern web workflows to vintage hardware\n'

    send_email(
        user.email,
        f'RetroBridge \u2014 Job #{job.id} {status_text} ({job.original_filename})',
        body,
        settings=settings,
    )


def notify_password_changed(user, settings=None):
    body = (
        'Your password was changed.\n\n'
        'If you did not do this, contact an administrator immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 Password Changed', body,
               settings=settings)


def notify_email_changed(user, old_email, new_email, settings=None):
    body_old = (
        f'Your email address was changed from {old_email} to {new_email}.\n\n'
        'If you did not do this, contact an administrator immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    body_new = (
        f'Your email address for your RetroBridge account ({user.username}) '
        f'was changed to this address.\n\n'
        'If you did not do this, contact an administrator immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(old_email, 'RetroBridge \u2014 Email Address Changed', body_old,
               settings=settings)
    send_email(new_email, 'RetroBridge \u2014 Email Address Updated', body_new,
               settings=settings)


def notify_new_login(user, ip_address, settings=None):
    body = (
        f'A new login to your account was detected.\n\n'
        f'  Username:  {user.username}\n'
        f'  IP:        {ip_address}\n\n'
        'If this was not you, change your password immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 New Login Detected', body,
               settings=settings)


def notify_account_deleted(user, settings=None):
    body = (
        f'Your RetroBridge account ({user.username}) has been permanently deleted.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 Account Deleted', body,
               settings=settings)
