import json
import subprocess
from pathlib import Path
from typing import Any, Union, Optional

from iiif_prezi import factory
from iiif_prezi.factory import ManifestFactory
from flask import g, render_template, request, send_from_directory, url_for
from flask_babel import lazy_gettext as _
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from openatlas import app
from openatlas.display.util import required_group, get_file_path
from openatlas.forms.form import get_table_form
from openatlas.models.entity import Entity


@app.route('/download/<path:filename>')
@required_group('readonly')
def download_file(filename: str) -> Any:
    return send_from_directory(
        app.config['UPLOAD_DIR'],
        filename,
        as_attachment=True)


@app.route('/display/<path:filename>')
@required_group('readonly')
def display_file(filename: str) -> Any:
    if request.args.get('size'):
        return send_from_directory(
            app.config['RESIZED_IMAGES'] / request.args.get('size'),
            filename)
    return send_from_directory(app.config['UPLOAD_DIR'], filename)


@app.route('/display_logo/<path:filename>')
def display_logo(filename: str) -> Any:
    return send_from_directory(app.config['UPLOAD_DIR'], filename)


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


@app.route('/file/iiif/<int:id_>', methods=['GET'])
@required_group('contributor')
def make_iiif_available(id_: int):
    convert_image_to_iiif(id_)
    return redirect(url_for('view', id_=id_))


def convert_image_to_iiif(id_):
    path = Path(app.config['IIIF_DIR']) / app.config['IIIF_PREFIX'] / str(id_)
    command = \
        (f"vips.exe tiffsave {get_file_path(id_)} {path} "
         f"--tile --pyramid --compression deflate "
         f"--tile-width 256 --tile-height 256")
    subprocess.Popen(command, shell=True)


@app.route('/iiif/<int:id_>', methods=['GET'])
@app.route('/iiif/<prefix>/<int:id_>', methods=['GET'])
@required_group('contributor')
def view_iiif(id_: int, prefix: Optional[str] = None):
    fac = ManifestFactory()
    # Where the resources live on the web
    fac.set_base_prezi_uri(request.url)
    # Where the resources live on disk
    image_path = Path(app.config['IIIF_DIR']) / app.config['IIIF_PREFIX']
    fac.set_base_prezi_dir(image_path)

    # Default Image API information
    fac.set_base_image_uri(request.url)
    fac.set_iiif_image_info(2.0, 2)  # Version, ComplianceLevel

    # 'warn' will print warnings, default level
    # 'error' will turn off warnings
    # 'error_on_warning' will make warnings into errors
    fac.set_debug("warn")
    entity = Entity.get_by_id(id_)
    manifest = fac.manifest(label=entity.name)
    manifest.description = entity.description
    mfst = manifest.toJSON(top=True)
    return json.dumps(mfst)
