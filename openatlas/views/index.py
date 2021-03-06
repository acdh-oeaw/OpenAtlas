from typing import Dict, Tuple, Union

from flask import flash, g, render_template, request, session, url_for
from flask_babel import format_number, lazy_gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import InputRequired

from openatlas import app, logger
from openatlas.api.v02.resources.error import MethodNotAllowedError
from openatlas.models.content import Content
from openatlas.models.entity import Entity
from openatlas.models.user import User
from openatlas.util.changelog import Changelog
from openatlas.util.display import bookmark_toggle, format_date, link, uc_first
from openatlas.util.table import Table
from openatlas.util.util import required_group, send_mail


class FeedbackForm(FlaskForm):  # type: ignore
    subject = SelectField(_('subject'),
                          render_kw={'autofocus': True},
                          choices=(('suggestion', _('suggestion')),
                                   ('question', _('question')),
                                   ('problem', _('problem'))))
    description = TextAreaField(_('description'), [InputRequired()])
    save = SubmitField(_('send'))


@app.route('/')
@app.route('/overview')
def index() -> str:
    tables = {'overview': Table(paging=False, defs=[{'className': 'dt-body-right', 'targets': 1}]),
              'bookmarks': Table(['name', 'class', 'first', 'last'],
                                 defs=[{'className': 'dt-body-right', 'targets': [2, 3]}]),
              'notes': Table(['name', 'class', 'first', 'last', _('note')],
                             defs=[{'className': 'dt-body-right', 'targets': [2, 3]}]),
              'latest': Table(order=[[4, 'desc']],
                              defs=[{'className': 'dt-body-right', 'targets': [2, 3]}])}
    if current_user.is_authenticated and hasattr(current_user, 'bookmarks'):
        for entity_id in current_user.bookmarks:
            entity = Entity.get_by_id(entity_id)
            tables['bookmarks'].rows.append([link(entity),
                                             g.classes[entity.class_.code].name,
                                             entity.first,
                                             entity.last,
                                             bookmark_toggle(entity.id, True)])
        for entity_id, text in User.get_notes().items():
            entity = Entity.get_by_id(entity_id)
            tables['notes'].rows.append([link(entity),
                                         g.classes[entity.class_.code].name,
                                         entity.first,
                                         entity.last,
                                         text])
        for name, count in Entity.get_overview_counts().items():
            if count:
                tables['overview'].rows.append([
                    uc_first(_(name)) if name in ['find', 'human remains'] else link(
                        _(name), url_for(name + '_index')),
                    format_number(count)])
        for entity in Entity.get_latest(8):
            tables['latest'].rows.append([
                link(entity),
                g.classes[entity.class_.code].name,
                entity.first,
                entity.last,
                format_date(entity.created),
                link(logger.get_log_for_advanced_view(entity.id)['creator'])])
    return render_template('index/index.html',
                           intro=Content.get_translation('intro'),
                           tables=tables)


@app.route('/index/setlocale/<language>')
def set_locale(language: str) -> Response:
    session['language'] = language
    if hasattr(current_user, 'id') and current_user.id:
        current_user.settings['language'] = language
        current_user.update_language()
    return redirect(request.referrer)


@app.route('/overview/feedback', methods=['POST', 'GET'])
@required_group('readonly')
def index_feedback() -> Union[str, Response]:
    form = FeedbackForm()
    if form.validate_on_submit() and session['settings']['mail']:  # pragma: no cover
        subject = uc_first(form.subject.data) + ' from ' + session['settings']['site_name']
        user = current_user
        body = form.subject.data + ' from ' + user.username + ' (' + str(user.id) + ') '
        body += user.email + ' at ' + request.headers['Host'] + "\n\n" + form.description.data
        if send_mail(subject, body, session['settings']['mail_recipients_feedback']):
            flash(_('info feedback thanks'), 'info')
        else:
            flash(_('error mail send'), 'error')
        return redirect(url_for('index'))
    return render_template('index/feedback.html', form=form)


@app.route('/overview/content/<item>')
def index_content(item: str) -> str:
    return render_template('index/content.html', text=Content.get_translation(item), title=item)


@app.errorhandler(400)
def bad_request(e: Exception) -> Tuple[Union[Dict[str, str], str], int]:  # pragma: no cover
    return render_template('400.html', e=e), 400


@app.errorhandler(403)
def forbidden(e: Exception) -> Tuple[Union[Dict[str, str], str], int]:
    return render_template('403.html', e=e), 403


@app.errorhandler(404)
def page_not_found(e: Exception) -> Tuple[Union[Dict[str, str], str], int]:
    return render_template('404.html', e=e), 404


@app.errorhandler(405)  # pragma: no cover
def method_not_allowed(e: Exception) -> Tuple[Union[Dict[str, str], str], int]:
    raise MethodNotAllowedError


@app.errorhandler(418)
def invalid_id(e: Exception) -> Tuple[str, int]:
    return render_template('418.html', e=e), 418


@app.errorhandler(422)
def unprocessable_entity(e: Exception) -> Tuple[str, int]:
    return render_template('422.html', e=e), 422


@app.route('/changelog')
def index_changelog() -> str:
    return render_template('index/changelog.html', versions=Changelog.versions)


@app.route('/unsubscribe/<code>')
def index_unsubscribe(code: str) -> str:
    user = User.get_by_unsubscribe_code(code)
    text = _('unsubscribe link not valid')
    if user:  # pragma: no cover
        user.settings['newsletter'] = ''
        user.unsubscribe_code = ''
        user.update()
        user.remove_newsletter()
        text = _('You have successfully unsubscribed. You can subscribe again in your Profile.')
    return render_template('index/unsubscribe.html', text=text)
