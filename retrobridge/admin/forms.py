from flask_wtf import FlaskForm
from wtforms import (
    StringField, IntegerField, SelectField, BooleanField, TextAreaField, SubmitField,
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class DeviceForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=32)])
    display_name = StringField('Display Name', validators=[Optional(), Length(max=64)])
    submit = SubmitField('Add Device')


class DevicePortForm(FlaskForm):
    port_label = StringField('Port Label', validators=[DataRequired(), Length(max=32)])
    dev_path = StringField('Device Path', validators=[DataRequired(), Length(max=128)])
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
    max_runtime_seconds = IntegerField('Max Runtime (s)', validators=[DataRequired()], default=300)
    idle_timeout_seconds = IntegerField('Idle Timeout (s)', validators=[DataRequired()], default=5)
    submit = SubmitField('Add Port')


class UserEditForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Length(max=120)])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=128)])
    is_admin = BooleanField('Admin')
    max_queued_jobs = IntegerField('Max Queued Jobs', validators=[DataRequired()], default=3)
    max_terminal_sessions = IntegerField('Max Terminal Sessions', validators=[DataRequired()], default=1)
    submit = SubmitField('Save')


class SettingsForm(FlaskForm):
    MAX_UPLOAD_SIZE_BYTES = StringField('Max Upload Size (bytes)', validators=[Optional()])
    DEFAULT_MAX_QUEUED_JOBS = StringField('Default Max Queued Jobs', validators=[Optional()])
    DEFAULT_MAX_TERMINAL_SESSIONS = StringField('Default Max Terminal Sessions', validators=[Optional()])
    IDLE_SLEEP_SECONDS = StringField('Idle Sleep Seconds', validators=[Optional()])
    MAX_JOBS_PER_HOUR = StringField('Max Jobs Per Hour', validators=[Optional()])
    MAX_TERMINAL_SESSION_SECONDS = StringField('Max Terminal Session Seconds', validators=[Optional()])
    TERMINAL_IDLE_TIMEOUT_SECONDS = StringField('Terminal Idle Timeout (s)', validators=[Optional()])
    submit = SubmitField('Save Settings')
