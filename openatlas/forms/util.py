from __future__ import annotations

import ast
from typing import Any

from flask import g
from flask_babel import lazy_gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField

from openatlas import app


def get_form_settings(form: Any, profile: bool = False) -> dict[str, str]:
    settings = {}
    for field in form:
        if field.type in ['CSRFTokenField', 'HiddenField', 'SubmitField']:
            continue
        if profile and field.name in current_user.settings:
            value = current_user.settings[field.name]
        elif field.name in g.settings:
            value = g.settings[field.name]
        else:
            value = ''  # pragma: no cover - if missing setting after an update
        if field.type in ['StringField', 'IntegerField']:
            settings[field.label.text] = value
        if field.type == 'BooleanField':
            settings[field.label.text] = str(_('on') if value else _('off'))
        if field.type == 'SelectField':
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            settings[field.label.text] = dict(field.choices).get(value)
        if field.name in [
                'mail_recipients_feedback',
                'file_upload_allowed_extension']:
            settings[field.label.text] = '<br>'.join(value)
    return settings


def convert(value: str) -> list[int]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    ids = ast.literal_eval(value)
    return ids if isinstance(ids, list) else [int(ids)]


def set_form_settings(form: Any, profile: bool = False) -> None:
    for field in form:
        if field.type in ['CSRFTokenField', 'HiddenField', 'SubmitField']:
            continue
        if profile and field.name == 'name':
            field.data = current_user.real_name
            continue
        if profile and field.name == 'email':
            field.data = current_user.email
            continue
        if profile and field.name in current_user.settings:
            field.data = current_user.settings[field.name]
            continue
        if field.name in ['log_level']:
            field.data = int(g.settings[field.name])
            continue
        if field.name in [
                'mail_recipients_feedback',
                'file_upload_allowed_extension']:
            for item in g.settings[field.name]:
                field.append_entry(item)
            continue
        if field.name not in g.settings:  # pragma: no cover
            field.data = ''  # If missing setting after an update
            continue
        field.data = g.settings[field.name]


class GlobalSearchForm(FlaskForm):
    term = StringField('')


@app.context_processor
def inject_template_functions() -> dict[str, str | GlobalSearchForm]:
    return {'search_form': GlobalSearchForm(prefix='global')}
