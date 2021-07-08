from typing import Any, Dict, List, Tuple, Union

from flask import Response, json, jsonify
from flask_restful import Resource, marshal

from openatlas.api.v02.resources.enpoints_util import download
from openatlas.api.v02.resources.parser import gis_parser
from openatlas.api.v02.templates.geometries import GeometriesTemplate
from openatlas.models.gis import Gis


class GetGeometricEntities(Resource):  # type: ignore
    @staticmethod
    def get() -> Union[Tuple[Any, int], Response]:
        parser = gis_parser.parse_args()
        output = {'type': 'FeatureCollection',
                  'features': GetGeometricEntities.get_geometries(parser)}
        if parser['count']:
            return jsonify(len(output['features']))
        if parser['download']:
            return download(output, GeometriesTemplate.geometries_template(), 'geometries')
        return marshal(output, GeometriesTemplate.geometries_template()), 200

    @staticmethod
    def get_geometries(parser: Dict[str, Any]) -> List[Dict[str, Any]]:
        choices = ['gisPointAll', 'gisPointSupers', 'gisPointSubs', 'gisPointSibling',
                   'gisLineAll', 'gisPolygonAll']
        out = []
        for item in choices if parser['geometry'] == 'gisAll' else parser['geometry']:
            for geom in json.loads(Gis.get_all()[item]):
                out.append(geom)
        return out