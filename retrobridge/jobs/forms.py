from flask_wtf import FlaskForm
from wtforms import FileField, SelectField, IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional
from flask_wtf.file import FileRequired, FileAllowed


def allowed_file_extensions():
    return ['bin', 'hex', 'obj', 'asm', 's', 'txt']


class JobUploadForm(FlaskForm):
    device_id = SelectField('Device', coerce=int, validators=[DataRequired()])
    file = FileField('Program File', validators=[
        FileRequired(),
        FileAllowed(allowed_file_extensions(), 'Invalid file type.'),
    ])
    priority = IntegerField('Priority (0-9)', validators=[Optional(), NumberRange(min=0, max=9)], default=0)
    submit = SubmitField('Submit Job')
