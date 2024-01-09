import json
from typing import Any, Union

from flask import (
    flash, g, render_template, request, send_from_directory, url_for)
from flask_babel import lazy_gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm
from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from werkzeug.wrappers import Response
from wtforms import TextAreaField
from wtforms.fields.simple import HiddenField
from wtforms.validators import InputRequired

from openatlas import app
from openatlas.display.tab import Tab
from openatlas.display.table import Table
from openatlas.display.util import (
    button, convert_image_to_iiif, format_date, get_file_path, is_authorized,
    required_group)
from openatlas.forms.field import SubmitField, TableField
from openatlas.forms.form import get_table_form
from openatlas.models.annotation import AnnotationImage
from openatlas.models.entity import Entity


@app.route('/download/<path:filename>')
@required_group('readonly')
def download_file(filename: str) -> Any:
    return send_from_directory(
        app.config['UPLOAD_PATH'],
        filename,
        as_attachment=True)


@app.route('/display/<path:filename>')
@required_group('readonly')
def display_file(filename: str) -> Any:
    if request.args.get('size'):
        return send_from_directory(
            app.config['RESIZED_IMAGES'] / request.args.get('size'),
            filename)
    return send_from_directory(app.config['UPLOAD_PATH'], filename)


@app.route('/display_logo/<path:filename>')
def display_logo(filename: str) -> Any:
    return send_from_directory(app.config['UPLOAD_PATH'], filename)


@app.route('/file/set_profile_image/<int:id_>/<int:origin_id>')
def set_profile_image(id_: int, origin_id: int) -> Response:
    Entity.set_profile_image(id_, origin_id)
    return redirect(url_for('view', id_=origin_id))


@app.route('/file/remove_profile_image/<int:entity_id>')
def file_remove_profile_image(entity_id: int) -> Response:
    entity = Entity.get_by_id(entity_id)
    entity.remove_profile_image()
    return redirect(url_for('view', id_=entity.id))


@app.route('/file/add/<int:id_>/<view>', methods=['GET', 'POST'])
@required_group('contributor')
def file_add(id_: int, view: str) -> Union[str, Response]:
    entity = Entity.get_by_id(id_)
    if request.method == 'POST':
        if request.form['checkbox_values']:
            entity.link_string('P67', request.form['checkbox_values'])
        return redirect(f"{url_for('view', id_=entity.id)}#tab-{view}")
    return render_template(
        'content.html',
        content=get_table_form(
            g.view_class_mapping[view],
            entity.get_linked_entities('P67')),
        title=entity.name,
        crumbs=[
            [_(entity.class_.view), url_for('index', view=entity.class_.view)],
            entity,
            f"{_('link')} {_(view)}"])


@app.route('/file/convert_iiif/<int:id_>')
@required_group('contributor')
def make_iiif_available(id_: int) -> Response:
    convert_image_to_iiif(id_)
    return redirect(url_for('view', id_=id_))


@app.route('/view_iiif/<int:id_>')
@required_group('contributor')
def view_iiif(id_: int) -> str:
    return render_template(
        'iiif.html',
        manifest_url=url_for(
            'api.iiif_manifest',
            id_=id_,
            version=g.settings['iiif_version'],
            _external=True))


class AnnotationForm(FlaskForm):
    coordinate = HiddenField(_('coordinates'), validators=[InputRequired()])
    annotation = TextAreaField(_('annotation'))
    annotated_entity = TableField(_('entity'))
    save = SubmitField(_('save'))


@app.route('/annotate_image/<int:id_>', methods=['GET', 'POST'])
@required_group('contributor')
def annotate_image(id_: int) -> Union[str, Response]:
    entity = Entity.get_by_id(id_, types=True, aliases=True)
    if not get_file_path(entity.id):
        return abort(404)
    table = None
    form = AnnotationForm()
    form.annotated_entity.filter_ids = [entity.id]
    if form.validate_on_submit():
        AnnotationImage.insert_annotation_image(
            image_id=id_,
            coordinates=form.coordinate.data,
            entity_id=form.annotated_entity.data,
            annotation=form.annotation.data)
        return redirect(url_for('annotate_image', id_=entity.id))
    if annotations := AnnotationImage.get_by_file(entity.id):
        rows = []
        for item in annotations:
            delete = ''
            if is_authorized('editor') or (
                    is_authorized('contributor')
                    and current_user.id == item['user_id']):
                delete = button(
                    _('delete'),
                    url_for('delete_annotation', id_=item['id']))
            rows.append([
                format_date(item['created']),
                item['annotation'],
                delete])
        table = Table(
            ['date', 'annotation', ''],
            rows=rows,
            order=[[0, 'desc']])
    return render_template(
        'tabs.html',
        tabs={'annotation': Tab(
            'annotation',
            form=form,
            table=table,
            content=render_template(
                'annotate.html',
                entity=entity,
                annotation_list=json.dumps(annotations, default=str)))},
        entity=entity,
        crumbs=[
            [_('file'), url_for('index', view='file')],
            entity,
            _('annotate')])


@app.route('/delete_annotation/<int:id_>')
@required_group('contributor')
def delete_annotation(id_: int) -> Response:
    annotation = AnnotationImage.get_by_id(id_)
    if current_user.group == 'contributor' \
            and annotation['user_id'] != current_user.id:
        abort(403)
    AnnotationImage.delete(id_)
    flash(_('annotation deleted'), 'info')
    return redirect(url_for('annotate_image', id_=annotation['image_id']))
