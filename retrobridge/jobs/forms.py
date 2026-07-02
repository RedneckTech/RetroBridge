from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileRequired, FileSize
from wtforms import (
    FileField, IntegerField, SelectField, StringField, SubmitField, TextAreaField,
)
from wtforms.validators import DataRequired, NumberRange, Optional


def allowed_file_extensions():
    return ['bin', 'hex', 'obj', 'asm', 's', 'txt']


def max_upload_size():
    from flask import current_app
    from retrobridge.admin.settings_utils import get_int
    val = get_int('MAX_UPLOAD_SIZE_BYTES')
    return val if val > 0 else 8 * 1024 * 1024


class JobUploadForm(FlaskForm):
    device_id = SelectField('Target Device', coerce=int, validators=[DataRequired()])
    file = FileField('Program File', validators=[
        FileRequired(message='Please select a file to upload.'),
        FileAllowed(allowed_file_extensions(),
                     'Invalid file type. Allowed: .bin, .hex, .obj, .asm, .s, .txt'),
    ])
    priority = IntegerField('Priority', validators=[
        Optional(), NumberRange(min=0, max=9),
    ], default=0)
    newline_mode = SelectField('Newline Mode', choices=[
        ('', 'Use port default'),
        ('crlf', 'CR+LF (Windows/DOS)'),
        ('cr', 'CR (Classic Mac)'),
        ('lf', 'LF (Unix)'),
    ], default='', validators=[Optional()])
    pre_transfer_cmds = TextAreaField('Pre-Transfer Commands (override)',
                                       validators=[Optional()])
    post_transfer_cmds = TextAreaField('Post-Transfer Commands (override)',
                                        validators=[Optional()])
    submit = SubmitField('Submit Job')
