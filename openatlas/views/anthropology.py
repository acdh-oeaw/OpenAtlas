from typing import Optional, Union

from flask import flash, g, render_template, url_for
from flask_babel import lazy_gettext as _
from flask_wtf import FlaskForm
from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from openatlas import app, logger
from openatlas.forms.form import build_form
from openatlas.models.entity import Entity
from openatlas.models.gis import Gis
from openatlas.models.link import Link
from openatlas.models.reference import Reference
from openatlas.models.user import User
from openatlas.util.display import (add_edit_link, add_remove_link, get_base_table_data,
                                    get_entity_data, get_profile_image_table_link, link)
from openatlas.util.tab import Tab
from openatlas.util.table import Table
from openatlas.util.util import is_authorized, required_group, was_modified


@app.route('/anthropology/<int:id_>')
@required_group('contributor')
def anthropology_index(id_: int) -> str:
    return render_template('anthropology/index.html', entity=Entity.get_by_id(id_))
