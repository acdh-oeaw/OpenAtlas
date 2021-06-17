from typing import Any, Dict, List, Optional, Tuple, Union

from flask import Response
from flask_restful import Resource

from openatlas.api.v02.resources.error import EntityDoesNotExistError, InvalidSubunitError
from openatlas.api.v02.resources.helpers import get_node_dict, resolve_node_parser
from openatlas.api.v02.resources.parser import default_parser
from openatlas.models.entity import Entity
from openatlas.models.place import get_structure


class GetSubunitHierarchy(Resource):  # type: ignore
    @staticmethod
    def get(id_: int) -> Union[Tuple[Resource, int], Response, Dict[str, Any]]:
        return resolve_node_parser({"nodes": GetSubunitHierarchy.get_subunit_hierarchy(id_)},
                                   default_parser.parse_args(), id_)

    @staticmethod
    def get_subunit_hierarchy(id_: int) -> List[Dict[str, Any]]:
        try:
            entity = Entity.get_by_id(id_, nodes=True)
        except EntityDoesNotExistError:
            raise EntityDoesNotExistError
        if not entity.class_.name == 'place' \
                and not entity.class_.name == 'feature' \
                and not entity.class_.name == 'stratigraphic_unit':
            raise InvalidSubunitError
        return GetSubunitHierarchy.get_subunits_recursive(entity, [])

    @staticmethod
    def get_subunits_recursive(
            entity: Optional[Entity],
            data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        structure = get_structure(entity)
        if structure and structure['subunits']:
            for subunit in structure['subunits']:
                data.append(get_node_dict(subunit))
        node = get_structure(entity)
        if node:
            for sub_id in node['subunits']:
                GetSubunitHierarchy.get_subunits_recursive(sub_id, data)
        return data