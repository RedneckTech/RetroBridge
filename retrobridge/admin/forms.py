from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, IntegerField, SelectField, StringField, SubmitField, TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class DeviceForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=32)])
    display_name = StringField('Display Name', validators=[Optional(), Length(max=64)])
    submit = SubmitField('Add Device')


class EditDeviceForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=32)])
    display_name = StringField('Display Name', validators=[Optional(), Length(max=64)])
    is_enabled = BooleanField('Enabled')
    submit = SubmitField('Save Device')


class DevicePortForm(FlaskForm):
    port_label = StringField('Label', validators=[DataRequired(), Length(max=32)])
    transport = SelectField('Transport', choices=[
        ('serial', 'Serial (RS-232)'),
        ('pty', 'PTY (Pseudo-Terminal)'),
        ('tcp', 'TCP (Raw Socket)'),
        ('telnet', 'Telnet'),
        ('rfc2217', 'RFC 2217 (Remote Serial)'),
    ], default='serial')
    dev_path = StringField('Device Path / Address', validators=[DataRequired(), Length(max=256)])
    purpose = SelectField('Purpose', choices=[
        ('job_queue', 'Job Queue'),
        ('interactive', 'Interactive'),
    ], validators=[DataRequired()])
    baud = IntegerField('Baud Rate', validators=[DataRequired()], default=9600)
    data_bits = IntegerField('Data Bits', validators=[DataRequired(), NumberRange(min=5, max=8)], default=8)
    parity = SelectField('Parity', choices=[
        ('N', 'None'), ('E', 'Even'), ('O', 'Odd'), ('M', 'Mark'), ('S', 'Space'),
    ], default='N')
    stop_bits = IntegerField('Stop Bits', validators=[DataRequired(), NumberRange(min=1, max=2)], default=1)
    flow_control = SelectField('Flow Control', choices=[
        ('none', 'None'), ('rtscts', 'RTS/CTS'), ('xonxoff', 'XON/XOFF'),
    ], default='none')
    newline_mode = SelectField('Newline Mode', choices=[
        ('crlf', 'CR+LF'), ('cr', 'CR'), ('lf', 'LF'),
    ], default='crlf')
    transfer_protocol = SelectField('Transfer Protocol', choices=[
        ('xmodem', 'XMODEM (128B)'),
        ('xmodem1k', 'XMODEM-1K'),
        ('ymodem', 'YMODEM'),
        ('kermit', 'Kermit'),
    ], default='xmodem')
    max_concurrent_jobs = IntegerField('Max Concurrent Jobs', validators=[DataRequired(), NumberRange(min=1)], default=1)
    max_runtime_seconds = IntegerField('Max Runtime (s)', validators=[DataRequired()], default=300)
    idle_timeout_seconds = IntegerField('Idle Timeout (s)', validators=[DataRequired()], default=5)
    pre_transfer_cmds = TextAreaField('Pre-Transfer Commands (JSON array)', validators=[Optional()])
    post_transfer_cmds = TextAreaField('Post-Transfer Commands (JSON array)', validators=[Optional()])
    is_enabled = BooleanField('Enabled')
    submit = SubmitField('Save Port')


class UserEditForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('Email', validators=[DataRequired(), Length(max=120)])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=128)])
    password = StringField('Password', validators=[
        Optional(),
        Length(min=8, message='Password must be at least 8 characters.'),
    ])
    is_admin = BooleanField('Admin')
    max_queued_jobs = IntegerField('Max Queued Jobs', validators=[DataRequired()], default=3)
    max_terminal_sessions = IntegerField('Max Terminal Sessions', validators=[DataRequired()], default=1)
    submit = SubmitField('Save')


class SettingsForm(FlaskForm):
    max_upload_size_mb = IntegerField(
        'Max Upload Size (MB)',
        validators=[DataRequired(), NumberRange(min=1, max=1024)],
        default=16,
    )
    default_max_queued_jobs = IntegerField(
        'Default Max Queued Jobs Per User',
        validators=[DataRequired(), NumberRange(min=1, max=100)],
        default=3,
    )
    default_max_terminal_sessions = IntegerField(
        'Default Max Terminal Sessions Per User',
        validators=[DataRequired(), NumberRange(min=1, max=10)],
        default=1,
    )
    max_jobs_per_hour = IntegerField(
        'Max Job Submissions Per User Per Hour',
        validators=[DataRequired(), NumberRange(min=1, max=1000)],
        default=10,
    )
    max_terminal_session_minutes = IntegerField(
        'Max Terminal Session Duration (minutes)',
        validators=[DataRequired(), NumberRange(min=1, max=1440)],
        default=60,
    )
    terminal_idle_timeout_minutes = IntegerField(
        'Terminal Idle Timeout (minutes)',
        validators=[DataRequired(), NumberRange(min=1, max=60)],
        default=5,
    )
    worker_poll_seconds = IntegerField(
        'Worker Poll Interval (seconds)',
        validators=[DataRequired(), NumberRange(min=1, max=300)],
        default=5,
    )
    registration_open = BooleanField('Allow New User Registration')
    maintenance_mode = BooleanField('Maintenance Mode')
    terminal_session_log_enabled = BooleanField('Log Terminal Session Keystrokes/Output')
    email_smtp_host = StringField('SMTP Host', validators=[Optional(), Length(max=128)])
    email_smtp_port = IntegerField('SMTP Port', validators=[Optional(), NumberRange(min=1, max=65535)])
    email_smtp_user = StringField('SMTP Username', validators=[Optional(), Length(max=128)])
    email_smtp_password = StringField('SMTP Password', validators=[Optional(), Length(max=128)])
    email_use_tls = BooleanField('Use STARTTLS')
    email_from_address = StringField('From Address', validators=[Optional(), Length(max=128)])
    email_from_name = StringField('From Name', validators=[Optional(), Length(max=64)])
    submit = SubmitField('Save Settings')
