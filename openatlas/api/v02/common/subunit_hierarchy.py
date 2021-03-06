from typing import Any, Dict, List, Optional, Tuple, Union

# from flasgger import swag_from
from flask import Response, jsonify, url_for
from flask_restful import Resource, marshal

from openatlas.api.v02.resources.download import Download
from openatlas.api.v02.resources.error import EntityDoesNotExistError, InvalidSubunitError
from openatlas.api.v02.resources.parser import default_parser
from openatlas.api.v02.templates.nodes import NodeTemplate
from openatlas.models.entity import Entity
from openatlas.models.place import get_structure
from openatlas.util.util import api_access


class GetSubunitHierarchy(Resource):  # type: ignore
    @api_access()  # type: ignore
    # @swag_from("../swagger/subunit_hierarchy.yml", endpoint="subunit_hierarchy")
    def get(self, id_: int) -> Union[Tuple[Resource, int], Response]:
        parser = default_parser.parse_args()
        node = {"nodes": GetSubunitHierarchy.get_subunit_hierarchy(id_)}
        template = NodeTemplate.node_template()
        if parser['count']:
            return jsonify(len(node['nodes']))
        if parser['download']:
            return Download.download(data=node, template=template, name=id_)
        return marshal(node, template), 200

    @staticmethod
    def get_subunit_hierarchy(id_: int) -> List[Dict[str, Any]]:
        try:
            entity = Entity.get_by_id(id_, nodes=True, aliases=True)
        except EntityDoesNotExistError:
            raise EntityDoesNotExistError
        if entity.class_.code in ['E18']:
            return GetSubunitHierarchy.get_subunits_recursive(entity, [])
        else:
            raise InvalidSubunitError

    @staticmethod
    def get_subunits_recursive(entity: Optional[Entity], data: List[Dict[str, Any]]) \
            -> List[Dict[str, Any]]:
        structure = get_structure(entity)
        if structure and structure['subunits']:
            for n in structure['subunits']:
                data.append({'id': n.id, 'label': n.name,
                             'url': url_for('entity', id_=n.id, _external=True)})
        node = get_structure(entity)
        if node:
            for sub_id in node['subunits']:
                GetSubunitHierarchy.get_subunits_recursive(sub_id, data)
        return data
