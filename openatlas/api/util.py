from typing import Any

from flask import send_file, send_from_directory
from flask_cors import cross_origin

from openatlas import app
from openatlas.api.v02.resources.error import AccessDeniedError
from openatlas.api.v02.resources.parser import default_parser
from openatlas.models.entity import Entity
from openatlas.models.node import Node
from openatlas.util.util import api_access


@app.route('/api/display/<path:filename>', strict_slashes=False)
@api_access()  # type: ignore
@cross_origin(origins=app.config['CORS_ALLOWANCE'], methods=['GET'])
def display_file_api(filename: str) -> Any:  # pragma: no cover
    parser = default_parser.parse_args()
    from pathlib import Path as Pathlib_path
    entity = Entity.get_by_id(int(Pathlib_path(filename).stem), nodes=True)
    license_ = None
    # If img has no license, it will not displayed
    for node in entity.nodes:
        if node.root and node.root[-1] == Node.get_hierarchy('License').id:
            license_ = node.name
    if license_:
        if parser['download']:
            return send_file(str(app.config['UPLOAD_DIR']) + '/' + filename, as_attachment=True)
        return send_from_directory(app.config['UPLOAD_DIR'], filename)
    raise AccessDeniedError
