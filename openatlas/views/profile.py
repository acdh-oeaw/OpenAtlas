import importlib
import bcrypt

from datetime import timedelta
from flask import flash, g, make_response, render_template, request, session, \
    url_for
from flask_babel import lazy_gettext as _
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from wtforms import BooleanField, PasswordField, validators
from wtforms.validators import InputRequired

from openatlas import app
from openatlas.database.connect import Transaction
from openatlas.display.tab import Tab
from openatlas.display.table import Table
from openatlas.display.util import button, display_info, link
from openatlas.display.util2 import manual, uc_first
from openatlas.forms.display import display_form
from openatlas.forms.field import SubmitField, generate_password_field
from openatlas.forms.setting import DisplayForm, ModulesForm, TokenForm
from openatlas.forms.util import get_form_settings, set_form_settings


class PasswordForm(FlaskForm):
    password_old = PasswordField(_('old password'), [InputRequired()])
    password = PasswordField(_('password'), [InputRequired()])
    password2 = PasswordField(_('repeat password'), [InputRequired()])
    generate_password = generate_password_field()
    show_passwords = BooleanField(_('show passwords'))
    save = SubmitField(_('save'))

    def validate(self, extra_validators: validators = None) -> bool:
        valid = FlaskForm.validate(self)
        hash_ = bcrypt.hashpw(
            self.password_old.data.encode('utf-8'),
            current_user.password.encode('utf-8'))
        if hash_ != current_user.password.encode('utf-8'):
            self.password_old.errors.append(_('error wrong password'))
            valid = False
        if self.password.data != self.password2.data:
            self.password.errors.append(_('error passwords must match'))
            self.password2.errors.append(_('error passwords must match'))
            valid = False
        if self.password_old.data == self.password.data:
            self.password.errors.append(
                _('error new password like old password'))
            valid = False
        if len(self.password.data) < g.settings['minimum_password_length']:
            self.password.errors.append(_('error password too short'))
            valid = False
        return valid


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile_index() -> str:
    tabs = {
        'profile': Tab(
            'profile',
            display_info({
                _('name'): current_user.real_name,
                _('email'): current_user.email,
                _('show email'): str(_('on'))
                if current_user.settings['show_email'] else str(_('off')),
                _('newsletter'): str(_('on'))
                if current_user.settings['newsletter'] else str(_('off'))}),
            buttons=[manual('tools/profile')]),
        'modules': Tab(
            'modules',
            display_info(get_form_settings(ModulesForm(), True)),
            buttons=[manual('tools/profile')]),
        'display': Tab(
            'display',
            display_info(get_form_settings(DisplayForm(), True)),
            buttons=[manual('tools/profile')]),
        'token': Tab(
            'token',
            display_info(get_form_settings(TokenForm(), True)),
            buttons=[manual('tools/profile')])}
    if not app.config['DEMO_MODE']:
        tabs['profile'].buttons += [
            button(_('edit'), url_for('profile_settings', category='profile')),
            button(_('change password'), url_for('profile_password'))]
        tabs['modules'].buttons.append(
            button(
                _('edit'),
                url_for('profile_settings', category='modules')))
        tabs['display'].buttons.append(
            button(_('edit'), url_for('profile_settings', category='display')))
        tabs['token'].buttons.append(
            button(_('generate'), url_for('generate_token')))
        tabs['token'].buttons.append(
            button(_('delete all tokens'), url_for('delete_all_tokens')))
        tabs['token'].table = get_token_table()
    return render_template(
        'tabs.html',
        tabs=tabs,
        title=_('profile'),
        crumbs=[_('profile')])


@app.route('/profile/settings/<category>', methods=['GET', 'POST'])
@login_required
def profile_settings(category: str) -> str | Response:
    form = getattr(
        importlib.import_module('openatlas.forms.setting'),
        f"{uc_first(category)}Form")()
    if form.validate_on_submit():
        settings = {}
        for field in form:
            if field.type in ['CSRFTokenField', 'HiddenField', 'SubmitField']:
                continue
            if field.name == 'name':
                current_user.real_name = field.data
            elif field.name == 'email':
                current_user.email = field.data
            else:
                value = field.data
                if field.type == 'BooleanField':
                    value = 'True' if value else ''
                settings[field.name] = value
        Transaction.begin()
        try:
            current_user.update()
            current_user.update_settings(settings)
            Transaction.commit()
            session['language'] = current_user.settings['language']
            flash(_('info update'), 'info')
        except Exception as e:  # pragma: no cover
            Transaction.rollback()
            g.logger.log('error', 'database', 'transaction failed', e)
            flash(_('error transaction'), 'error')
        return redirect(f"{url_for('profile_index')}#tab-{category}")
    set_form_settings(form, True)
    return render_template(
        'content.html',
        content=display_form(form, manual_page='profile'),
        title=_('profile'),
        crumbs=[
            [_('profile'), f"{url_for('profile_index')}#tab-{category}"],
            _(category)])


@app.route('/profile/generate_token', methods=['GET', 'POST'])
@login_required
def generate_token() -> str | Response:
    form = TokenForm()
    if form.validate_on_submit():
        expiration = form.expiration.data
        token_name = form.token_name.data
        token = None
        Transaction.begin()
        try:
            token = current_user.generate_token(expiration, token_name)
            Transaction.commit()
            flash(_('token stored'), 'info')
        except Exception as e:  # pragma: no cover
            Transaction.rollback()
            g.logger.log('error', 'database', 'transaction failed', e)
            flash(_('error transaction'), 'error')
        response = make_response(redirect(url_for('generate_token')))
        response.set_cookie(
            'jwt_token',
            token,
            httponly=True,
            secure=True,
            max_age=timedelta(seconds=1))
        return response
    token = request.cookies.get('jwt_token')
    form.token_text.data = token
    return render_template(
        'content.html',
        content=display_form(form, manual_page='profile'),
        title=_('profile'),
        crumbs=[
            [_('profile'), f"{url_for('profile_index')}#tab-token"],
            _('token')])


@app.route('/profile/delete_token/<int:id_>')
@login_required
def delete_token(id_: int) -> str | Response:
    current_user.delete_token(id_)
    flash(_('token deleted'), 'info')
    return redirect(url_for('generate_token'))


@app.route('/profile/delete_all_tokens/')
@login_required
def delete_all_tokens() -> str | Response:
    current_user.delete_all_tokens()
    flash(_('all tokens deleted'), 'info')
    return redirect(f"{url_for('profile_index')}#tab-token")


@app.route('/profile/password', methods=['GET', 'POST'])
@login_required
def profile_password() -> str | Response:
    form = PasswordForm()
    if form.validate_on_submit():
        current_user.password = bcrypt.hashpw(
            form.password.data.encode('utf-8'),
            bcrypt.gensalt()).decode('utf-8')
        current_user.update()
        flash(_('info password updated'), 'info')
        return redirect(url_for('profile_index'))
    return render_template(
        'tabs.html',
        tabs={
            'password': Tab(
                'password',
                content=display_form(form, 'password-form'))},
        title=_('profile'),
        crumbs=[
            [_('profile'), url_for('profile_index')],
            _('change password')])


def get_token_table() -> Table:
    table = Table(['name', 'jit', 'valid_from', 'valid_until'])
    for token in current_user.get_tokens():
        table.rows.append([
            token['name'],
            token['jit'],
            token['valid_from'],
            token['valid_until'],
            link(
                _('delete'),
                url_for('delete_token', id_=token['id']))])
    return table
