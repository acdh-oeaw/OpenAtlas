import os
from datetime import datetime
from subprocess import call
from typing import Any, Optional

from flask import flash, g, render_template, url_for
from flask_babel import lazy_gettext as _
from flask_login import current_user
from werkzeug.exceptions import abort
from werkzeug.utils import redirect, secure_filename
from werkzeug.wrappers import Response

from openatlas import app
from openatlas.database.connect import Transaction
from openatlas.display.display import Display
from openatlas.display.image_processing import resize_image
from openatlas.display.util import (
    button, check_iiif_activation, check_iiif_file_exist,
    convert_image_to_iiif, get_file_path, get_iiif_file_path, link,
    required_group)
from openatlas.display.util2 import is_authorized
from openatlas.forms.entity_form import get_entity_form, process_form_data
from openatlas.forms.manager_base import BaseManager
from openatlas.forms.util import form_crumbs
from openatlas.models.entity import Entity
from openatlas.models.gis import InvalidGeomException
from openatlas.models.reference_system import ReferenceSystem


@app.route('/entity/<int:id_>')
@required_group('readonly')
def view(id_: int) -> str | Response:
    if id_ in g.types:  # Types have their own view
        entity = g.types[id_]
        if not entity.root:
            return redirect(
                f"{url_for('type_index')}"
                f"#menu-tab-{entity.category}_collapse-{id_}")
    elif id_ in g.reference_systems:
        entity = g.reference_systems[id_]
    else:
        entity = Entity.get_by_id(id_, types=True, aliases=True)
        if not entity.class_.view:
            flash(_("This entity can't be viewed directly."), 'error')
            abort(400)
    display = Display(entity)
    return render_template(
        'tabs.html',
        tabs=display.tabs,
        entity=entity,
        gis_data=display.gis_data,
        crumbs=display.crumbs)


@app.route(
    '/reference_system/remove_class/<int:system_id>/<class_name>',
    methods=['GET', 'POST'])
@required_group('manager')
def reference_system_remove_class(system_id: int, class_name: str) -> Response:
    for link_ in g.reference_systems[system_id].get_links('P67'):
        if link_.range.class_.name == class_name:
            abort(403)  # Abort because there are linked entities
    try:
        g.reference_systems[system_id].remove_class(class_name)
        flash(_('info update'), 'info')
    except Exception as e:  # pragma: no cover
        g.logger.log('error', 'database', 'remove class failed', e)
        flash(_('error database'), 'error')
    return redirect(url_for('view', id_=system_id))


@app.route('/insert/<class_>', methods=['GET', 'POST'])
@app.route('/insert/<class_>/<int:origin_id>', methods=['GET', 'POST'])
@required_group('contributor')
def insert(class_: str, origin_id: Optional[int] = None) -> str | Response:
    check_insert_access(class_)
    entity = Entity({'openatlas_class_name': class_})
    origin = Entity.get_by_id(origin_id) if origin_id else None
    form = get_entity_form(entity, origin)
    if form.validate_on_submit():
        # if class_ == 'file':
        #    return redirect(insert_files(manager))
        return redirect(save(entity, origin, form))
    return render_template(
        'entity/insert.html',
        form=form,
        class_name=class_,
        view_name=g.classes[class_].view,
        #gis_data=manager.place_info['gis_data'],
        writable=os.access(app.config['UPLOAD_PATH'], os.W_OK),
        #overlays=manager.place_info['overlays'],
        title=_(g.classes[class_].view),
        crumbs=form_crumbs(entity, origin))


@app.route('/update/<int:id_>', methods=['GET', 'POST'])
@app.route('/update/<int:id_>/<copy>', methods=['GET', 'POST'])
@required_group('contributor')
def update(id_: int, copy: Optional[str] = None) -> str | Response:
    entity = Entity.get_by_id(id_, types=True, aliases=True)
    check_update_access(entity)
    form = get_entity_form(entity)
    if form.validate_on_submit():
        if template := was_modified_template(entity, form):
            return template
        return redirect(save(entity, None, form))
    #if not manager.form.is_submitted():
    #    manager.populate_update()
    #if entity.class_.view in ['artifact', 'place']:
    #    manager.entity.image_id = manager.entity.get_profile_image_id()
    #    if not manager.entity.image_id:
    #        for link_ in manager.entity.get_links('P67', inverse=True):
    #            if link_.domain.class_.view == 'file' \
    #                    and get_base_table_data(link_.domain)[6] \
    #                    in g.display_file_ext:
    #                manager.entity.image_id = link_.domain.id
    #                break
    return render_template(
        'entity/update.html',
        form=form,
        entity=entity,
        class_name=entity.class_.view,
        #gis_data=manager.place_info['gis_data'],
        #overlays=manager.place_info['overlays'],
        title=entity.name,
        #crumbs=manager.get_crumbs()
    )


@app.route('/delete/<int:id_>')
@required_group('contributor')
def delete(id_: int) -> Response:
    if current_user.group == 'contributor':
        info = g.logger.get_log_info(id_)
        if not info['creator'] or info['creator'].id != current_user.id:
            abort(403)
    entity = Entity.get_by_id(id_)
    if not is_authorized(entity.class_.write_access):
        abort(403)
    url = url_for('index', view=entity.class_.view)
    if isinstance(entity, ReferenceSystem):
        if entity.system:
            abort(403)
        if entity.classes:
            flash(_('Deletion not possible if classes are attached'), 'error')
            return redirect(url_for('view', id_=id_))
    elif entity.class_.view in ['artifact', 'place']:
        if entity.get_linked_entities('P46'):
            flash(_('Deletion not possible if subunits exists'), 'error')
            return redirect(url_for('view', id_=id_))
        if entity.class_.name != 'place' \
                and (parent := entity.get_linked_entity('P46', True)):
            url = \
                f"{url_for('view', id_=parent.id)}" \
                f"#tab-{entity.class_.name.replace('_', '-')}"
    elif entity.class_.name == 'source_translation':
        source = entity.get_linked_entity_safe('P73', inverse=True)
        url = f"{url_for('view', id_=source.id)}#tab-text"
    elif entity.class_.name == 'file':
        try:
            delete_files(id_)
        except Exception as e:  # pragma: no cover
            g.logger.log('error', 'file', 'file deletion failed', e)
            flash(_('error file delete'), 'error')
            return redirect(url_for('view', id_=id_))
    entity.delete()
    g.logger.log_user(id_, 'delete')
    flash(_('entity deleted'), 'info')
    return redirect(url)


def check_insert_access(class_: str) -> None:
    if class_ not in g.classes \
            or not g.classes[class_].view \
            or not is_authorized(g.classes[class_].write_access):
        abort(403)


def check_update_access(entity: Entity) -> None:
    check_insert_access(entity.class_.name)
    if entity.class_.view == 'type' and (
            entity.category == 'system'
            or entity.category == 'standard' and not entity.root):
        abort(403)
    if entity.check_too_many_single_type_links():
        abort(422)


def insert_files(manager: BaseManager) -> str:
    filenames = []
    try:
        Transaction.begin()
        entity_name = manager.form.name.data.strip()
        for count, file in enumerate(manager.form.file.data):
            manager.entity = insert('file', file.filename)
            # Add 'a' to prevent emtpy temporary filename, has no side effects
            filename = secure_filename(f'a{file.filename}')
            name = f"{manager.entity.id}.{filename.rsplit('.', 1)[1].lower()}"
            ext = secure_filename(file.filename).rsplit('.', 1)[1].lower()
            path = app.config['UPLOAD_PATH'] / name
            file.save(str(path))
            if f'.{ext}' in g.display_file_ext:
                call(f'exiftran -ai {path}', shell=True)  # Fix rotation
            filenames.append(name)
            if g.settings['image_processing']:
                resize_image(name)
            if (g.settings['iiif_conversion']
                    and check_iiif_activation()
                    and g.settings['iiif_convert_on_upload']):
                convert_image_to_iiif(manager.entity.id, path)
            if len(manager.form.file.data) > 1:
                manager.form.name.data = \
                    f'{entity_name}_{str(count + 1).zfill(2)}'
            manager.process_form()
            manager.update_entity()
            g.logger.log_user(manager.entity.id, 'insert')
        Transaction.commit()
        url = get_redirect_url(manager)
        flash(_('entity created'), 'info')
    except Exception as e:  # pragma: no cover
        Transaction.rollback()
        for filename in filenames:
            (app.config['UPLOAD_PATH'] / filename).unlink()
        g.logger.log('error', 'database', 'transaction failed', e)
        flash(_('error transaction'), 'error')
        url = url_for('index', view=g.classes['file'].view)
    return url


def save(entity: Entity, origin: Entity | None, form: Any) -> str:
    action = 'update' if entity.id else 'insert'
    Transaction.begin()
    try:
        entity = process_form_data(entity, form)
        g.logger.log_user(entity.id, action)
        Transaction.commit()
        url = get_redirect_url(entity)
        flash(
            _('entity created') if action == 'insert' else _('info update'),
            'info')
    except InvalidGeomException as e:
        Transaction.rollback()
        g.logger.log('error', 'database', 'invalid geom', e)
        flash(_('Invalid geom entered'), 'error')
        url = url_for('index', view=entity.class_.view)
        if action == 'update' and entity.id:
            url = url_for(
                'update',
                id_=entity.id,
                origin_id=origin.id if origin else None)
    except Exception as e:
        Transaction.rollback()
        g.logger.log('error', 'database', 'transaction failed', e)
        flash(_('error transaction'), 'error')
        if action == 'update' and entity.id:
            url = url_for(
                'update',
                id_=entity.id,
                origin_id=origin.id if origin else None)
        else:
            url = url_for('type_index') if \
                entity.class_.name in ['administrative_unit', 'type'] else \
                url_for('index', view=entity.class_.view)
    return url


def get_redirect_url(entity: Entity) -> str:
    #if manager.continue_link_id and manager.origin:
    #    return url_for(
    #        'link_update',
    #        id_=manager.continue_link_id,
    #        origin_id=manager.origin.id)
    url = url_for('view', id_=entity.id)
    #if manager.origin and manager.entity.class_.name not in \
    #        ('administrative_unit', 'source_translation', 'type'):
    #    url = \
    #        f"{url_for('view', id_=manager.origin.id)}" \
    #        f"#tab-{manager.entity.class_.view}"
    #    if manager.entity.class_.name == 'file':
    #        url = f"{url_for('view', id_=manager.origin.id)}#tab-file"
    #    elif manager.origin.class_.view \
    #            in ['place', 'feature', 'stratigraphic_unit'] \
    #            and manager.entity.class_.view != 'actor':
    #        url = url_for('view', id_=manager.entity.id)
    #if hasattr(manager.form, 'continue_') \
    #        and manager.form.continue_.data == 'yes':
    #    url = url_for(
    #        'insert',
    #        class_=manager.entity.class_.name,
    #        origin_id=manager.origin.id if manager.origin else None)
    #    if manager.entity.class_.name in ('administrative_unit', 'type') \
    #            and manager.origin:
    #        root_id = manager.origin.root[0] \
    #            if (manager.origin.class_.view == 'type'
    #                and manager.origin.root) else manager.origin.id
    #        super_id = getattr(manager.form, str(root_id)).data
    #        url = url_for(
    #            'insert',
    #            class_=manager.entity.class_.name,
    #            origin_id=str(super_id) if super_id else root_id)
    #elif hasattr(manager.form, 'continue_') \
    #        and manager.form.continue_.data in ['sub', 'human_remains']:
    #    class_ = manager.form.continue_.data
    #    if class_ == 'sub':
    #        match manager.entity.class_.name:
    #            case 'place':
    #                class_ = 'feature'
    #            case 'feature':
    #                class_ = 'stratigraphic_unit'
    #            case 'stratigraphic_unit':
    #                class_ = 'artifact'
    #    url = url_for('insert', class_=class_, origin_id=manager.entity.id)
    return url


def delete_files(id_: int) -> None:
    if path := get_file_path(id_):  # Prevent missing file warning
        path.unlink()
    for resized_path in app.config['RESIZED_IMAGES'].glob(f'**/{id_}.*'):
        resized_path.unlink()
    if g.settings['iiif'] and check_iiif_file_exist(id_):
        if path := get_iiif_file_path(id_):
            path.unlink()


def was_modified_template(entity: Entity, form: Any) -> str | None:
    if not entity.modified \
            or not form.opened.data \
            or entity.modified < \
            datetime.fromtimestamp(float(form.opened.data)):
        return
    del form.save
    g.logger.log('info', 'multi user', 'Overwrite denied')
    flash(
        _('error modified by %(username)s', username=link(
            g.logger.get_log_info(entity.id)['modifier'],
            external=True)) +
        button(_('reload'), url_for('update', id_=entity.id)),
        'error')
    return render_template('entity/update.html', form=form, entity=entity)
