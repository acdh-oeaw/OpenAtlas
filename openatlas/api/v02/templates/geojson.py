from typing import Dict, Type

from flask_restful import fields
from flask_restful.fields import List, String


class GeoJson:

    @staticmethod
    def geojson_template(show: Dict[str, str]) -> Dict[str, Type[String]]:
        title = {'title': fields.String}

        relations = {'label': fields.String,
                     'relationTo': fields.String,
                     'relationType': fields.String}

        depictions = {'@id': fields.String,
                      'title': fields.String,
                      'license': fields.String,
                      'url': fields.String}

        links = {'type': fields.String,
                 'identifier': fields.String,
                 'reference_system': fields.String}

        types = {'identifier': fields.String,
                 'label': fields.String,
                 'description': fields.String,
                 'hierarchy': fields.String}

        names = {'alias': fields.String}

        start = {'earliest': fields.String,
                 'latest': fields.String}

        end = {'earliest': fields.String,
               'latest': fields.String}

        description = {'value': fields.String}

        timespans = {'start': fields.Nested(start),
                     'end': fields.Nested(end)}

        when = {'timespans': fields.List(fields.Nested(timespans))}

        feature = {'@id': fields.String,
                   'type': fields.String,
                   'crmClass': fields.String,
                   'properties': fields.Nested(title),
                   'description': fields.List(fields.Nested(description))
                   }

        if 'when' in show:
            feature['when'] = fields.Nested(when)

        if 'types' in show:
            feature['types'] = fields.List(fields.Nested(types))

        if 'relations' in show:
            feature['relations'] = fields.List(fields.Nested(relations))

        if 'names' in show:
            feature['names'] = fields.List(fields.Nested(names))

        if 'links' in show:
            feature['links'] = fields.List(fields.Nested(links))

        # if 'geometry' in show:
        feature['geometry'] = fields.Raw

        if 'depictions' in show:
            feature['depictions'] = fields.List(fields.Nested(depictions))

        entity_json = {'@context': fields.String,
                       'type': fields.String,
                       'features': fields.List(fields.Nested(feature))}
        return entity_json

    @staticmethod
    def pagination(show: Dict[str, str]) -> Dict[str, List]:
        page_index = {"page": fields.Integer,
                      "start_id": fields.Integer
                      }
        pagination_model = {"entities": fields.Integer,
                            "entity_per_page": fields.Integer,
                            "index": fields.List(fields.Nested(page_index)),
                            "total_pages": fields.Integer
                            }

        pagination = {"result": fields.List(fields.Nested(GeoJson.geojson_template(show))),
                      "pagination": fields.List(fields.Nested(pagination_model))
                      }

        return pagination
