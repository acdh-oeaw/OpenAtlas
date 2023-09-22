from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING, Union

from flask import abort, g

from openatlas.database.date import Date
from openatlas.database.link import Link as Db
from openatlas.database.tools import Tools
from openatlas.display.util import (
    datetime64_to_timestamp, format_date_part, link, timestamp_to_datetime64)

if TYPE_CHECKING:  # pragma: no cover
    from openatlas.models.entity import Entity
    from openatlas.models.type import Type


class Link:
    object_: Optional[Entity]  # Needed for first/last appearance

    def __init__(
            self,
            row: dict[str, Any],
            domain: Optional[Entity] = None,
            range_: Optional[Entity] = None) -> None:
        from openatlas.models.entity import Entity
        self.id = row['id']
        self.description = row['description']
        self.property = g.properties[row['property_code']]
        self.domain = domain or Entity.get_by_id(row['domain_id'])
        self.range = range_ or Entity.get_by_id(row['range_id'])
        self.type = g.types[row['type_id']] if row['type_id'] else None
        self.types: dict[Entity, None] = {}
        if 'type_id' in row and row['type_id']:
            self.types[g.types[row['type_id']]] = None
        if 'begin_from' in row:
            self.begin_from = timestamp_to_datetime64(row['begin_from'])
            self.begin_to = timestamp_to_datetime64(row['begin_to'])
            self.begin_comment = row['begin_comment']
            self.end_from = timestamp_to_datetime64(row['end_from'])
            self.end_to = timestamp_to_datetime64(row['end_to'])
            self.end_comment = row['end_comment']
            self.first = format_date_part(self.begin_from, 'year') \
                if self.begin_from else None
            self.last = format_date_part(self.end_from, 'year') \
                if self.end_from else None
            self.last = format_date_part(self.end_to, 'year') \
                if self.end_to else self.last

    def update(self) -> None:
        Db.update({
            'id': self.id,
            'property_code': self.property.code,
            'domain_id': self.domain.id,
            'range_id': self.range.id,
            'type_id': self.type.id if self.type else None,
            'description': self.description,
            'begin_from': datetime64_to_timestamp(self.begin_from),
            'begin_to': datetime64_to_timestamp(self.begin_to),
            'begin_comment': self.begin_comment,
            'end_from': datetime64_to_timestamp(self.end_from),
            'end_to': datetime64_to_timestamp(self.end_to),
            'end_comment': self.end_comment})

    def set_dates(self, data: dict[str, Any]) -> None:
        self.begin_from = data['begin_from']
        self.begin_to = data['begin_to']
        self.begin_comment = data['begin_comment']
        self.end_from = data['end_from']
        self.end_to = data['end_to']
        self.end_comment = data['end_comment']

    @staticmethod
    def get_linked_entity(
            id_: int,
            code: str,
            inverse: bool = False,
            types: bool = False) -> Optional[Entity]:
        result = Link.get_linked_entities(
            id_,
            code,
            inverse=inverse,
            types=types)
        if len(result) > 1:  # pragma: no cover
            g.logger.log(
                'error',
                'model',
                f'Multiple linked entities found for {code}')
            abort(400, 'Multiple linked entities found')
        return result[0] if result else None

    @staticmethod
    def get_linked_entities(
            id_: int,
            codes: Union[str, list[str]],
            inverse: bool = False,
            types: bool = False) -> list[Entity]:
        from openatlas.models.entity import Entity
        codes = codes if isinstance(codes, list) else [codes]
        return Entity.get_by_ids(
            Db.get_linked_entities_inverse(id_, codes) if inverse
            else Db.get_linked_entities(id_, codes),
            types=types)

    @staticmethod
    def get_linked_entity_safe(
            id_: int,
            code: str,
            inverse: bool = False,
            types: bool = False) -> Entity:
        entity = Link.get_linked_entity(id_, code, inverse, types)
        if not entity:  # pragma: no cover
            g.logger.log(
                'error',
                'model',
                'missing linked',
                f'id: {id_}, code: {code}')
            abort(418, f'Missing linked {code} for {id_}')
        return entity

    @staticmethod
    def get_links(
            entities: Union[int, list[int]],
            codes: Union[str, list[str], None] = None,
            inverse: bool = False) -> list[Link]:
        from openatlas.models.entity import Entity
        entity_ids = set()
        result = Db.get_links(
            entities,
            codes if isinstance(codes, list) else [str(codes)],
            inverse)
        for row in result:
            entity_ids.add(row['domain_id'])
            entity_ids.add(row['range_id'])
        linked_entities = {
            entity.id: entity for entity
            in Entity.get_by_ids(entity_ids, types=True)}
        links = []
        for row in result:
            links.append(Link(
                row,
                domain=linked_entities[row['domain_id']],
                range_=linked_entities[row['range_id']]))
        return links

    @staticmethod
    def delete_by_codes(
            entity: Entity,
            codes: list[str],
            inverse: bool = False) -> None:
        from openatlas.models.tools import get_carbon_link
        from openatlas.models.type import Type
        if entity.class_.name == 'stratigraphic_unit' \
                and 'P2' in codes \
                and not inverse:
            exclude_ids = Type.get_sub_ids_recursive(
                Type.get_hierarchy('Features for sexing'))
            exclude_ids.append(Type.get_hierarchy('Radiocarbon').id)
            if Tools.get_sex_types(entity.id) or get_carbon_link(entity):
                Db.remove_types(entity.id, exclude_ids)
                codes.remove('P2')
                if not codes:
                    return
        Db.delete_by_codes(entity.id, codes, inverse)

    @staticmethod
    def get_by_id(id_: int) -> Link:
        return Link(Db.get_by_id(id_))

    @staticmethod
    def get_links_by_type(type_: Type) -> list[dict[str, Any]]:
        return Db.get_links_by_type(type_.id)

    @staticmethod
    def get_links_by_type_recursive(
            type_: Type,
            result: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result += Db.get_links_by_type(type_.id)
        for sub_id in type_.subs:
            result = Link.get_links_by_type_recursive(g.types[sub_id], result)
        return result

    @staticmethod
    def get_entity_ids_by_type_ids(types_: list[int]) -> list[int]:
        return Db.get_entity_ids_by_type_ids(types_)

    @staticmethod
    def delete_(id_: int) -> None:
        Db.delete_(id_)

    @staticmethod
    def get_invalid_cidoc_links() -> list[dict[str, str]]:
        from openatlas.models.entity import Entity

        invalid_linking = []
        for row in Db.get_cidoc_links():
            property_ = g.properties[row['property_code']]
            domain_is_valid = property_.find_object(
                'domain_class_code',
                row['domain_code'])
            range_is_valid = property_.find_object(
                'range_class_code',
                row['range_code'])
            if not domain_is_valid or not range_is_valid:
                invalid_linking.append(row)
        invalid_links = []
        for item in invalid_linking:
            for row in Db.get_invalid_links(item):
                domain = Entity.get_by_id(row['domain_id'])
                range_ = Entity.get_by_id(row['range_id'])
                invalid_links.append({
                    'domain': f"{link(domain)} ({domain.cidoc_class.code})",
                    'property': link(g.properties[row['property_code']]),
                    'range': f"{link(range_)} ({range_.cidoc_class.code})"})
        return invalid_links

    @staticmethod
    def invalid_involvement_dates() -> list[Link]:
        return [
            Link.get_by_id(row['id'])
            for row in Date.invalid_involvement_dates()]

    @staticmethod
    def get_invalid_link_dates() -> list[Link]:
        return [
            Link.get_by_id(row['id'])
            for row in Date.get_invalid_link_dates()]

    @staticmethod
    def check_link_duplicates() -> list[dict[str, Any]]:
        return Db.check_link_duplicates()

    @staticmethod
    def delete_link_duplicates() -> int:
        return Db.delete_link_duplicates()

    @staticmethod
    def check_single_type_duplicates() -> list[dict[str, Any]]:
        from openatlas.models.entity import Entity
        data = []
        for type_ in g.types.values():
            if not type_.multiple and type_.category not in ['value', 'tools']:
                if type_ids := type_.get_sub_ids_recursive():
                    for id_ in Db.check_single_type_duplicates(type_ids):
                        offending_types = []
                        entity = Entity.get_by_id(id_, types=True)
                        for entity_type in entity.types:
                            if g.types[entity_type.root[0]].id == type_.id:
                                offending_types.append(entity_type)
                        if offending_types:
                            data.append({
                                'entity': entity,
                                'type': type_,
                                'offending_types': offending_types})
        return data
