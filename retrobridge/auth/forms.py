import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField, IntegerField, PasswordField, SelectField, StringField,
    SubmitField, TextAreaField,
)
from wtforms.validators import (
    DataRequired, Email, EqualTo, Length, NumberRange, Optional, ValidationError,
)


def password_complexity(form, field):
    password = field.data or ''
    if not password:
        return
    if not re.search(r'[A-Z]', password):
        raise ValidationError('Password must contain at least one uppercase letter.')
    if not re.search(r'[0-9]', password):
        raise ValidationError('Password must contain at least one digit.')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=64)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Log In')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=128)])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters.'),
        password_complexity,
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match.'),
    ])
    submit = SubmitField('Register')


class ProfileForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[Optional(), Length(max=128)])
    bio = TextAreaField('Bio', validators=[Optional(), Length(max=500)])
    terminal_font_size = IntegerField('Terminal Font Size', validators=[NumberRange(min=10, max=24)], default=14)
    terminal_color_scheme = SelectField('Terminal Theme', choices=[
        ('dark', 'Dark (Green on Black)'),
        ('amber', 'Amber (Amber on Black)'),
        ('light', 'Light (Black on White)'),
        ('cyan', 'Cyan (Cyan on Black)'),
    ], default='dark')
    email_notify_jobs = BooleanField('Email me when my jobs complete')
    email_notify_security = BooleanField('Email me for account security events')
    new_password = PasswordField('New Password', validators=[
        Optional(),
        Length(min=8, message='Password must be at least 8 characters.'),
        password_complexity,
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        EqualTo('new_password', message='Passwords must match.'),
    ])
    submit = SubmitField('Update Profile')
