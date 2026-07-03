"""
Email Notification System
==========================
SMTP-based email sending for job completion and account security
notifications. Configured via AdminSetting table. Disabled when
SMTP host is empty.

All sends happen in background threads to avoid blocking responses.
"""

import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)


def _get_setting(key, default=''):
    from retrobridge.admin.settings_utils import _get_raw
    return _get_raw(key) or default


def send_email(to_address, subject, body_text):
    smtp_host = _get_setting('EMAIL_SMTP_HOST')
    if not smtp_host:
        return

    smtp_port = int(_get_setting('EMAIL_SMTP_PORT') or 587)
    smtp_user = _get_setting('EMAIL_SMTP_USER')
    smtp_password = _get_setting('EMAIL_SMTP_PASSWORD')
    use_tls = _get_setting('EMAIL_USE_TLS') in ('1', 'true', 'yes', 'on')
    from_address = _get_setting('EMAIL_FROM_ADDRESS', 'noreply@retrobridge.local')
    from_name = _get_setting('EMAIL_FROM_NAME', 'RetroBridge')

    def _send():
        try:
            msg = MIMEText(body_text, 'plain', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = formataddr((from_name, from_address))
            msg['To'] = to_address

            if use_tls:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)

            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)

            server.sendmail(from_address, [to_address], msg.as_string())
            server.quit()
            logger.info('Email sent to %s: %s', to_address, subject)
        except Exception:
            logger.exception('Failed to send email to %s', to_address)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def notify_job_completed(user, job):
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
    )


def notify_password_changed(user):
    body = (
        'Your password was changed.\n\n'
        'If you did not do this, contact an administrator immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 Password Changed', body)


def notify_email_changed(user, old_email, new_email):
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
    send_email(old_email, 'RetroBridge \u2014 Email Address Changed', body_old)
    send_email(new_email, 'RetroBridge \u2014 Email Address Updated', body_new)


def notify_new_login(user, ip_address):
    body = (
        f'A new login to your account was detected.\n\n'
        f'  Username:  {user.username}\n'
        f'  IP:        {ip_address}\n\n'
        'If this was not you, change your password immediately.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 New Login Detected', body)


def notify_account_deleted(user):
    body = (
        f'Your RetroBridge account ({user.username}) has been permanently deleted.\n\n'
        '\u2014\nRetroBridge\n'
    )
    send_email(user.email, 'RetroBridge \u2014 Account Deleted', body)
