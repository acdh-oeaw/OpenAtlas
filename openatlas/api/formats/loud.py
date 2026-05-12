import ast
import hashlib
import mimetypes
from collections import defaultdict
from typing import Any

import validators
from flask import g, url_for

from openatlas import app
from openatlas.api.resources.util import (
    date_to_utc_iso_str, generate_feature_without_null_values, get_crm_code,
    get_crm_relation,
    get_iiif_manifest_and_path,
    get_license_type, remove_spaces_dashes)
from openatlas.display.util2 import get_file_path
from openatlas.models.annotation import AnnotationText
from openatlas.models.entity import Entity, Link
from openatlas.models.gis import get_gis_by_id

unit_map = {
    'B': 'bytes',
    'KB': 'kilobytes',
    'MB': 'megabytes',
    'GB': 'gigabytes',
    'TB': 'terabytes'}

ARCHAEOLOGY_AAT: dict[str, dict[str, str]] = {
    'artifact': {
        'id': 'https://vocab.getty.edu/aat/300117127',
        'type': 'Type',
        '_label': 'artifacts'},
    'human_remains': {
        'id': 'https://vocab.getty.edu/aat/300379896',
        'type': 'Type',
        '_label': 'human remains'}}


class LoudFormatter:

    def __init__(
            self,
            loud_context: dict[str, str],
            type_references: dict[int, list[Link]]) -> None:
        self.loud = loud_context
        self.type_refs = type_references
        self.handlers: dict[str, Any] = {
            'P1': self._handle_p1,
            'P2': self._handle_p2,
            'P67': self._handle_p67,
            'P73': self._handle_p73,
            'OA7': self._handle_oa7}

    def get_property_key(self, link_: Link, is_inverse: bool) -> str:
        code = link_.property.code
        if code == 'OA7':
            return 'participated_in'
        if is_inverse \
                and link_.domain.class_.name == 'external_reference':
            return 'subject_of'
        if not is_inverse:
            if code == 'P67':
                if link_.domain.class_.name == 'file':
                    return 'digitally_carries'
                return 'refers_to'
            if code == 'P73':
                return 'referred_to_by'
        if code == 'P53' and link_.domain.class_.name == 'artifact':
            return 'current_location'
        if code == 'P2' and link_.description:
            return 'dimension'
        name = 'part' if is_inverse else 'part_of'
        if link_.property.code != 'P127':
            name = self.loud[
                get_crm_relation(link_, is_inverse).replace(' ', '_')]
        return name

    def format_link(self, link_: Link, is_domain: bool) -> Any:
        target = link_.domain if is_domain else link_.range
        type_ = self.loud[
            get_crm_code(link_, is_domain).replace(' ', '_')]
        if target.class_.name == 'human_remains':
            type_ = 'BiologicalObject'
        property_: Any = {
            'id': url_for('api.entity_uuid', uuid=target.uuid, _external=True),
            'type': type_,
            '_label': target.name}
        if link_.dates.begin_from or link_.dates.end_from:
            property_ = property_ | self.get_loud_timespan(link_)
        code_ = link_.property.code
        if code_ != 'P2' and link_.type:
            property_['classified_as'] = [
                self._format_type_property(g.types[link_.type.id])]
        if code_ == 'P67' and link_.domain.class_.name == 'file':
            property_ = {
                "type": "VisualItem",
                "_label": f"Visual content of {link_.domain.name}",
                "represents": [property_]}

        handler = self.handlers.get(code_)
        self._prepend_archaeology_classification(target, property_)
        if handler:
            return handler(property_, link_, is_domain)
        return property_

    @staticmethod
    def _prepend_archaeology_classification(
            entity: Entity,
            property_: dict[str, Any]) -> None:
        if aat := ARCHAEOLOGY_AAT.get(entity.class_.name):
            property_['classified_as'] = (
                    [aat] + property_.get('classified_as', []))

    @staticmethod
    def base_entity_dict(entity: Entity) -> dict[str, Any]:
        type_ = remove_spaces_dashes(entity.cidoc_class.i18n['en'])
        if entity.class_.name == 'file':
            type_ = 'DigitalObject'
        if entity.class_.name == 'human_remains':
            type_ = 'BiologicalObject'
        result: dict[str, Any] = {
            'id': url_for(
                'api.entity_uuid',
                uuid=entity.uuid,
                _external=True),
            'type': type_,
            '_label': entity.name}
        LoudFormatter._prepend_archaeology_classification(entity, result)
        return result

    @staticmethod
    def get_file_dimensions(entity: Entity) -> dict[str, Any]:
        file_size = entity.get_file_size()
        return {'dimension': [{
            "type": "Dimension",
            "_label": file_size,
            "classified_as": [{
                "id": "https://vocab.getty.edu/aat/300265863",
                "type": "Type",
                "_label": "File Size"}],
            "value": int(file_size.split()[0]),
            "unit": {
                "id": "https://vocab.getty.edu/aat/300265870",
                "type": "MeasurementUnit",
                "_label": unit_map[file_size.split()[1]]}}]}

    def get_digital_object_details(
            self,
            entity: Entity,
            mime_type: str | None = None) -> dict[str, Any]:
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(g.files[entity.id])
        file_ = get_file_path(entity.id)
        digital_object: dict[str, Any] = {'format': mime_type}
        if mime_type:
            if 'image/' in mime_type:
                digital_object["classified_as"] = [{
                    "id": "https://vocab.getty.edu/aat/300215302",
                    "type": "Type",
                    "_label": "Digital image"}]
            if 'application/pdf' in mime_type:  # pragma: no cover
                digital_object["classified_as"] = [{
                    "id": "https://vocab.getty.edu/aat/300424602",
                    "type": "Type",
                    "_label": "Digital documents"}]
            if 'model/' in mime_type:  # pragma: no cover
                digital_object["classified_as"] = [{
                    "id": "https://vocab.getty.edu/aat/300247398",
                    "type": "Type",
                    "_label": "Digital File Format"}, {
                    "id": "https://www.wikidata.org/wiki/Q3859833",
                    "type": "Type",
                    "_label": "3D Model"}]
        if file_ and file_.stem:
            digital_object.update({"access_point": [{
                "id": url_for(
                    'api.display',
                    filename=file_.stem if file_ else '',
                    _external=True),
                "type": "DigitalObject"}]})
        if entity.license_holder:
            for license_holder in entity.license_holder:
                digital_object.update({
                    'right_held_by': [{
                        'id': self.generate_skolem_id(
                            license_holder.id,
                            'rights_holder'),
                        '_label': license_holder.name,
                        'type': 'Actor'}]})
        if entity.creator:
            for creator in entity.creator:
                digital_object.update({'created_by': [{
                    'id': self.generate_skolem_id(
                        creator.id,
                        f'{entity.id}_creation_{creator.id}'),
                    '_label': f'Creation of {entity.name}',
                    'type': 'Creation',
                    'carried_out_by': [{
                        'id': self.generate_skolem_id(
                            creator.id,
                            'rights_holder'),
                        '_label': creator.name,
                        'type': 'Actor'}]}]})
        if license_ := get_license_type(entity):
            subject_to: dict[str, Any] = {
                'id': self.generate_skolem_id(license_.id, 'license'),
                'type': "Right",
                '_label': f'License of {entity.name}',
                "identified_by": [{
                    'id': url_for(
                        'api.entity_uuid',
                        uuid=license_.uuid,
                        _external=True),
                    "type": "Name",
                    "content": license_.name}]}
            classified_as = []
            for type_link in self.type_refs.get(license_.id, []):
                url = type_link.domain.name
                if type_link.domain.class_.name == 'reference_system':
                    system = g.reference_systems[type_link.domain.id]
                    url = (
                        f'{system.resolver_url or ''}'
                        f'{type_link.description}')
                classified_as.append({
                    "id": url,
                    "type": "Type",
                    "_label": license_.name})
            if classified_as:
                subject_to['classified_as'] = classified_as
            digital_object.update({'subject_to': [subject_to]})
        return digital_object

    @staticmethod
    def handle_radiocarbon(
            link_: Link, properties_set: dict[str, Any]) -> None:
        radio_data = ast.literal_eval(link_.description)
        properties_set['attributed_by'].append({
            'id': LoudFormatter.generate_skolem_id(link_.id, 'radiocarbon'),
            "type": "AttributeAssignment",
            "_label": "Radiocarbon Dating",
            "classified_as": [{
                "id": "https://vocab.getty.edu/aat/300054656",
                "type": "Type",
                "_label": "Radiocarbon Dating"}],
            "assigned": [{
                "type": "Dimension",
                "_label": f'{radio_data['radiocarbonYear']} +/- '
                          f'{radio_data['range']} {radio_data['timeScale']}',
                "classified_as": [{
                    "id": "https://vocab.getty.edu/aat/300054656",
                    "type": "Type",
                    "_label": "Radiocarbon Date"}],
                "value": int(radio_data['radiocarbonYear']),
                "lower_value": int(radio_data['radiocarbonYear']) - int(
                    radio_data['range']),
                "upper_value": int(radio_data['radiocarbonYear']) + int(
                    radio_data['range']),
                "unit": {
                    "id": "https://vocab.getty.edu/aat/300379244",
                    "type": "MeasurementUnit",
                    "_label": f"years {radio_data['timeScale']}"},
                "referred_to_by": [{
                    "type": "LinguisticObject",
                    "content": str(radio_data['range']),
                    "_label": "Laboratory Error Range",
                    "classified_as": [{
                        "id": "https://vocab.getty.edu/aat/300435427",
                        "type": "Type",
                        "_label": "error (measure of uncertainty)"}]}]}],
            "identified_by": [{
                'id': LoudFormatter.generate_skolem_id(link_.id, 'laboratory'),
                "type": "Identifier",
                "content": f"{radio_data['labId']}-{radio_data['specId']}",
                "_label": "Laboratory ID",
                "classified_as": [{
                    "id": "https://vocab.getty.edu/aat/300404621",
                    "type": "Type",
                    "_label": "Laboratory Identifiers"}]}, {
                'id': LoudFormatter.generate_skolem_id(link_.id, 'specimen'),
                "type": "Identifier",
                "content": str(radio_data['specId']),
                "_label": "Specimen ID",
                "classified_as": [{
                    "id": "https://vocab.getty.edu/aat/300404626",
                    "type": "Type",
                    "_label": "Identification Numbers"}]}],
            "carried_out_by": [{
                'id': LoudFormatter.generate_skolem_id(
                    link_.id,
                    'radio_group'),
                "type": "Group",
                "_label": radio_data['labId'],
                "identified_by": [{
                    "type": "Name",
                    "content": radio_data['labId']}]}]})

    @staticmethod
    def _handle_p1(
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        target = link_.domain if is_domain else link_.range
        del property_['id']
        property_['content'] = target.name
        return property_

    def _handle_p2(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        target = link_.domain if is_domain else link_.range
        if link_.description:
            property_['value'] = float(link_.description)
            property_['unit'] = {
                "id": "http://vocab.getty.edu/aat/300226816",
                'type': "MeasurementUnit",
                '_label': target.description}
        # super_type = g.types[g.types[link_.range.id].root[-1]]
        # property_['part_of'] = [self._format_type_property(super_type)]
        return property_

    def _handle_p73(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        if is_domain:
            return property_
        property_['content'] = link_.range.description
        if link_.range.standard_type:
            property_['classified_as'] = [self._format_type_property(
                g.types[link_.range.standard_type.id])]
        return property_

    def _handle_p67(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        if not is_domain:
            if link_.description:
                property_['content'] = link_.description
            return property_
        property_['classified_as'] = []
        if link_.domain.class_.name == 'file':
            property_['type'] = 'DigitalObject'
        else:
            property_['type'] = 'LinguisticObject'
        if standard_type := link_.domain.standard_type:
            property_['classified_as'].append(
                self._format_type_property(standard_type))
        if link_.description:
            property_ = property_ | {
                "identified_by": [{
                    "type": "Name",
                    "content": f"{link_.description}",
                    "classified_as": [{
                        "id": "http://vocab.getty.edu/aat/300200294",
                        "type": "Type",
                        "_label": "pagination"}]}]}
        if link_.domain.class_.name == 'bibliography':
            property_['classified_as'].append({
                "id": "https://vocab.getty.edu/aat/300026652",
                "type": "Type",
                "_label": "Bibliography"})
        if link_.domain.class_.name == 'edition':
            property_['classified_as'].append({
                "id": "https://vocab.getty.edu/aat/300404319",
                "type": "Type",
                "_label": "Edition"})
        if link_.domain.class_.name == 'external_reference':
            property_ = {
                "id": url_for(
                    'api.entity_uuid',
                    uuid=link_.domain.uuid,
                    _external=True),
                "classified_as": [{
                    "id": "https://vocab.getty.edu/aat/300264578",
                    "type": "Type",
                    "_label": "Web Page"}],
                "type": "LinguisticObject",
                "digitally_carried_by": [{
                    "type": "DigitalObject",
                    "classified_as": [{
                        "id": "https://vocab.getty.edu/aat/300264578",
                        "type": "Type",
                        "_label": "Web Page"}],
                    "format": "text/html",
                    "_label": link_.domain.name,
                    "access_point": [{
                        "id": link_.domain.name,
                        "type": "DigitalObject"}]}]}
        property_['content'] = link_.domain.description
        return property_

    def _handle_oa7(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> Any:
        if is_domain:
            label = (
                f'Relationship between '
                f'{link_.range.name} and {link_.domain.name}')
        else:
            label = (
                f'Relationship between '
                f'{link_.domain.name} and {link_.range.name}')
        relationship: dict[str, Any] = {
            'id': self.generate_skolem_id(link_.id, 'relationship'),
            'type': 'Event',
            '_label': label,
            'had_participant': [property_]}
        if link_.type:
            relationship['classified_as'] = [
                self._format_type_property(g.types[link_.type.id])]
        return [relationship] if is_domain else relationship

    def _format_type_property(self, type_: Entity) -> dict[str, Any]:
        property_: dict[str, Any] = {
            'id': url_for('api.entity_uuid', uuid=type_.uuid, _external=True),
            'type': remove_spaces_dashes(type_.cidoc_class.i18n['en']),
            '_label': type_.name}
        if type_.dates.begin_from or type_.dates.end_from:
            property_ = property_ | self.get_loud_timespan(type_)
        # for super_type in [g.types[root] for root in type_.root]:
        #    property_['part_of'] = [
        #        self._format_type_property(super_type)]
        external_references: dict[str, Any] = {}
        for type_link in self.type_refs.get(type_.id, []):
            url = type_link.domain.name
            if type_link.domain.class_.name == 'reference_system':
                system = g.reference_systems[type_link.domain.id]
                url = f'{system.resolver_url or ''}{type_link.description}'
            if not validators.url(url):  # pragma: no cover
                continue
            match_property = 'equivalent'
            if type_link.type \
                    and g.types.get(type_link.type.id) \
                    and 'close' in g.types[type_link.type.id].name:
                match_property = 'related'  # pragma: no cover
            if match_property not in external_references:
                external_references[match_property] = []
            external_references[match_property].append({
                "id": url,
                "type": "Type",
                "_label": type_.name})
        return property_ | external_references

    @staticmethod
    def generate_skolem_id(id_: int, type_name: str) -> str:
        seed = f"{id_}_{type_name}".encode('utf-8')
        identifier_hash = hashlib.sha256(seed).hexdigest()[:16]
        return url_for(
            "api.skolem_proxy",
            subpath= f'{type_name.lower()}/{identifier_hash}',
            _external=True)

    def get_loud_timespan(
            self,
            entity: Entity | Link,
            links_: list[Link] | None = None) -> dict[str, Any]:
        if not isinstance(entity, Link):
            if entity.class_.name == 'person':
                return self._get_loud_person_timespan(entity, links_)
            if entity.class_.name == 'group':
                return self._get_loud_group_timespan(entity, links_)
        if not entity.dates.dates_available():
            return {}
        return {'timespan': (
                {'id': self.generate_skolem_id(entity.id, 'timespan'),
                 'type': 'TimeSpan'} |
                self._get_loud_begin_dates(entity) |
                self._get_loud_end_dates(entity))}

    def _get_loud_person_timespan(
            self,
            entity: Entity,
            links_: list[Link] | None) -> dict[str, Any]:
        result = {}
        birth_event: dict[str, Any] = {
            'id': self.generate_skolem_id(entity.id, 'birth'),
            'type': 'Birth',
            '_label': f'Birth of {entity.name}'}
        has_birth_data = False
        if entity.dates.begin_from or entity.dates.begin_to:
            birth_event['timespan'] = (
                    {'type': 'TimeSpan'}
                    | self._get_loud_begin_dates(entity))
            has_birth_data = True

        death_event: dict[str, Any] = {
            'id': self.generate_skolem_id(entity.id, 'death'),
            'type': 'Death',
            '_label': f'Death of {entity.name}'}
        has_death_data = False
        if entity.dates.end_from or entity.dates.end_to:
            death_event['timespan'] = (
                    {'type': 'TimeSpan'}
                    | self._get_loud_end_dates(entity))
            has_death_data = True

        if links_:
            for link_ in links_:
                place = {
                    'id': url_for(
                        'api.entity_uuid',
                        uuid=link_.range.uuid,
                        _external=True),
                    'type': 'Place',
                    '_label': link_.range.name}
                if link_.property.code == 'OA8':
                    birth_event['took_place_at'] = [place]
                    has_birth_data = True
                elif link_.property.code == 'OA9':
                    death_event['took_place_at'] = [place]
                    has_death_data = True
        if has_birth_data:
            result['born'] = birth_event
        if has_death_data:
            result['died_in'] = death_event
        return result

    def _get_loud_group_timespan(
            self,
            entity: Entity,
            links_: list[Link] | None) -> dict[str, Any]:
        res = {}
        form: dict[str, Any] = {
            'id': self.generate_skolem_id(entity.id, 'formation'),
            'type': 'Formation',
            '_label': f'Formation of {entity.name}'}
        has_formation = False
        if entity.dates.begin_from or entity.dates.begin_to:
            form['timespan'] = (
                    {'id': self.generate_skolem_id(entity.id, 'begin'),
                     'type': 'TimeSpan'}
                    | self._get_loud_begin_dates(entity))
            has_formation = True

        diss: dict[str, Any] = {
            'id': self.generate_skolem_id(entity.id, 'dissolution'),
            'type': 'Dissolution',
            '_label': f'Dissolution of {entity.name}'}
        has_dissolution = False
        if entity.dates.end_from or entity.dates.end_to:
            diss['timespan'] = (
                    {'id': self.generate_skolem_id(entity.id, 'end'),
                     'type': 'TimeSpan', }
                    | self._get_loud_end_dates(entity))
            has_dissolution = True
        if links_:
            for lnk in links_:
                place = {
                    'id': url_for(
                        'api.entity_uuid',
                        uuid=lnk.range.uuid,
                        _external=True),
                    'type': 'Place',
                    '_label': lnk.range.name}
                if lnk.property.code == 'OA8':
                    form['took_place_at'] = [place]
                    has_formation = True
                elif lnk.property.code == 'OA9':
                    diss['took_place_at'] = [place]
                    has_dissolution = True

        if has_formation:
            res['formed_by'] = form
        if has_dissolution:
            res['dissolved_by'] = diss
        return res

    @staticmethod
    def _get_loud_begin_dates(entity: Entity | Link) -> dict[str, Any]:
        data = {
            'begin_of_the_begin':
                date_to_utc_iso_str(entity.dates.begin_from),
            'end_of_the_begin': date_to_utc_iso_str(entity.dates.begin_to),
            'beginning_is_qualified_by': entity.dates.begin_comment}
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def _get_loud_end_dates(entity: Entity | Link) -> dict[str, Any]:
        data = {
            'begin_of_the_end': date_to_utc_iso_str(entity.dates.end_from),
            'end_of_the_end': date_to_utc_iso_str(entity.dates.end_to),
            'end_is_qualified_by': entity.dates.end_comment}
        return {k: v for k, v in data.items() if v is not None}

    def get_loud_representations(
            self,
            image_links: list[Link],
            properties_set: dict[str, Any]) -> None:
        representation = []
        subject_of = []
        for link_ in image_links:
            entity = link_.domain
            mime_type, _ = mimetypes.guess_type(g.files[entity.id])
            image = {
                'id': url_for(
                    'api.entity_uuid',
                    uuid=entity.uuid,
                    _external=True),
                '_label': entity.name,
                'type': 'DigitalObject'}
            image.update(self.get_digital_object_details(entity, mime_type))
            if mime_type == 'application/pdf':  # pragma: no cover
                subject_of.append({
                    'type': 'LinguisticObject',
                    '_label': entity.name,
                    "classified_as": [{
                        "id": "https://vocab.getty.edu/aat/300424602",
                        "type": "Type",
                        "_label": "Digital documents"}],
                    'digitally_carried_by': [image]})
            else:
                representation.append(image)
        properties_set['representation'].append({
            'id': self.generate_skolem_id(0, 'visual_representation'),
            'type': 'VisualItem',
            "_label": "Visual Representations",
            'digitally_shown_by': representation})
        properties_set['subject_of'].extend(subject_of)

    @staticmethod
    def get_iiif_subject_of(image_links: list[Link]) -> list[dict[str, Any]]:
        subject_of = []
        for link_ in image_links:
            entity = link_.domain
            manifest_path = get_iiif_manifest_and_path(entity.id)
            if (manifest_path.get('IIIFManifest')
                    and manifest_path.get('IIIFBasePath')):
                subject_of.append({
                    'id': LoudFormatter.generate_skolem_id(
                        link_.id,
                        'iif_manifest'),
                    "type": "LinguisticObject",
                    "digitally_carried_by": [{
                        'id': LoudFormatter.generate_skolem_id(
                            link_.id,
                            'DigitalObject'),
                        "type": "DigitalObject",
                        "access_point": [{
                            "id": manifest_path['IIIFManifest'],
                            "type": "DigitalObject"}],
                        "conforms_to": [{
                            "id":
                                "https://iiif.io/api/presentation/2.0/",
                            "type": "InformationObject"}],
                        "format":
                            "application/ld+json;profile='https://iiif.io"
                            "/api/presentation/2/context.json'"}]})
        return subject_of

    @staticmethod
    def handle_authority_reference(
            link_: Link,
            properties_set: dict[str, Any],
            entity: Entity) -> None:
        match_property = 'equivalent'
        if link_.type and \
                g.types.get(link_.type.id) and \
                'close' in g.types[link_.type.id].name:
            match_property = 'related'
        system = g.reference_systems[link_.domain.id]
        properties_set[match_property].append({
            "id": f'{system.resolver_url or ''}{link_.description}',
            "type": entity.cidoc_class.name.replace(' ', '')})
        properties_set['identified_by'].append({
            'id': LoudFormatter.generate_skolem_id(link_.id, 'identifier'),
            "type": "Identifier",
            "content": link_.description,
            "_label": f"{link_.domain.name} Identifier",
            "classified_as": [{
                "id": "https://vocab.getty.edu/aat/300404620",
                "type": "Type",
                "_label": "Authority Control Number"}],
            "attributed_by": [{
                "id": LoudFormatter.generate_skolem_id(link_.id, 'authority'),
                "type": "AttributeAssignment",
                "carried_out_by": [{
                    "id": system.website_url,
                    "type": "Group",
                    "_label": link_.domain.name}]}]})

    def handle_membership(
            self,
            link_: Link,
            properties_set: dict[str, Any]) -> None:
        properties_set['member_of'].append({
            'id': url_for(
                'api.entity_uuid',
                uuid=link_.domain.uuid,
                _external=True),
            'type': self.loud[get_crm_code(link_, True).replace(' ', '_')],
            '_label': link_.domain.name})
        if link_.type or link_.dates.dates_available():
            carried_out: dict[str, Any] = {
                "type": "Activity",
                "carried_out_on_behalf_of": [{
                    'id': url_for(
                        'api.entity_uuid',
                        uuid=link_.domain.uuid,
                        _external=True),
                    'type': self.loud[
                        get_crm_code(link_, True).replace(' ', '_')],
                    '_label': link_.domain.name}]}
            label = f"Membership in {link_.domain.name}"
            if link_.type:
                if type_ := g.types.get(link_.type.id):
                    label = (
                        f"Role as {type_.name} at {link_.domain.name}")
                if type_ := self._format_type_property(
                        g.types[link_.type.id]):
                    carried_out['classified_as'] = [type_]
            carried_out['_label'] = label
            if link_.dates.dates_available():
                carried_out = (
                        carried_out | self.get_loud_timespan(link_))
            properties_set['carried_out'].append(carried_out)

    @staticmethod
    def handle_geometries(link_: Link) -> dict[str, list[Any]]:
        defined_by = []
        for geom in get_gis_by_id(link_.range.id):
            defined_by.append(generate_feature_without_null_values(geom))
        return {'defined_by': defined_by}

    def process_link(
            self,
            link_: Link,
            properties_set: dict[str, Any],
            is_inverse: bool,
            root_entity: Entity) -> None:
        is_domain = is_inverse
        if link_.property.code == 'P53':
            property_name = self.get_property_key(link_, is_inverse)
            base_property = self.format_link(link_, is_domain=is_domain)
            properties_set[property_name].append(
                base_property |
                self.handle_geometries(link_)
                # | self.handle_administrative_units(link_)
            )
            return
        if is_inverse \
                and link_.property.code == 'P67' \
                and link_.domain.cidoc_class.code == 'E32':
            self.handle_authority_reference(
                link_,
                properties_set,
                root_entity)
            return
        if is_inverse and link_.property.code == 'P107':
            self.handle_membership(link_, properties_set)
            return
        if link_.property.code == 'P2' and link_.range.name == 'Radiocarbon':
            self.handle_radiocarbon(link_, properties_set)
            return
        property_name = self.get_property_key(link_, is_inverse)
        if link_.property.code == 'P46':
            properties_set[property_name] = self.format_link(
                link_,
                is_domain=is_domain)
            return
        properties_set[property_name].append(
            self.format_link(link_, is_domain=is_domain))

    def process_media_links(
            self,
            file_links: list[Link],
            properties_set: dict[str, Any],
            entity: Entity) -> None:
        if file_links:
            self.get_loud_representations(file_links, properties_set)
            properties_set['subject_of'].extend(
                self.get_iiif_subject_of(file_links))
        if entity.class_.name == 'file' and g.files.get(entity.id):
            properties_set.update(self.get_file_dimensions(entity))
            properties_set.update(self.get_digital_object_details(entity))

    @staticmethod
    def handle_description(
            entity: Entity,
            properties_set: dict[str, Any]) -> None:
        description: dict[str, Any] = {
            'id': LoudFormatter.generate_skolem_id(entity.id, 'description'),
            "type": "LinguisticObject",
            "_label": "Description",
            "content": entity.description,
            "classified_as": [{
                "id": "https://vocab.getty.edu/aat/300435416",
                "type": "Type",
                "_label": "Description"}]}
        part = []
        if annotations := AnnotationText.get_by_source_id(entity.id):
            for annotation in annotations:  # pragma: no cover
                offset = 0
                text = entity.description or ''
                inner_text = text[
                    annotation.link_start + offset:
                    annotation.link_end + offset]
                annotation_dict = {
                    'id': LoudFormatter.generate_skolem_id(
                        annotation.id,
                        'annotation'),
                    "type": "LinguisticObject",
                    "_label": f"Annotation: {inner_text}",
                    "content": inner_text,
                    "classified_as": [{
                        "id": "https://vocab.getty.edu/aat/300435420",
                        "type": "Type",
                        "_label": "Annotation"}]}
                annotation_dict = annotation_dict | {
                    "digitally_carried_by": [{
                        'id': LoudFormatter.generate_skolem_id(
                            annotation.id,
                            'annotation_digital_object'),
                        "type": "DigitalObject",
                        "classified_as": [{
                            # todo: get aat right
                            "id": "https://vocab.getty.edu/aat/300435443",
                            "type": "Type",
                            "_label": "Selectors"}],
                        "referred_to_by": [{
                            "type": "LinguisticObject",
                            "content": f'{annotation.text}',
                            "classified_as": [{
                                # todo: get aat right
                                "id": "https://vocab.getty.edu/aat/300430390",
                                "type": "Type",
                                "_label": "Text Position Selector"}],
                            "identified_by": [{
                                "type": "Identifier",
                                "_label": "start",
                                "content": f'{annotation.link_start + offset}'
                            }, {
                                "type": "Identifier",
                                "_label": "end",
                                "content": f'{annotation.link_end + offset}'}]
                        }]}]}
                if annotation.entity_id:
                    linked_entity = Entity.get_by_id(annotation.entity_id)
                    annotation_dict = annotation_dict | {
                        "about": [{
                            'id': url_for(
                                'api.entity_uuid',
                                uuid=linked_entity.uuid,
                                _external=True),
                            'type': remove_spaces_dashes(
                                linked_entity.cidoc_class.i18n['en']),
                            '_label': linked_entity.name,
                            'identified_by': [{
                                "type": "Name",
                                "_label": linked_entity.name,
                                "content": linked_entity.name
                            }, {
                                "type": "Identifier",
                                "_label": "System Identifier",
                                "content": url_for(
                                    'api.entity_uuid',
                                    uuid=linked_entity.uuid,
                                    _external=True)}]}]}
                if annotation.text:
                    annotation_dict = annotation_dict | {
                        'referred_to_by': [{
                            "type": "LinguisticObject",
                            "_label": annotation.text,
                            "content": annotation.text,
                            "classified_as": [{
                                "id": "https://vocab.getty.edu/aat/300027200",
                                "type": "Type",
                                "_label": "Note"}]}]}
                part.append(annotation_dict)
        if part:  # pragma: no cover
            description = description | {'part': part}
        properties_set['referred_to_by'].append(description)

    @staticmethod
    def add_core_metadata(
            entity: Entity,
            properties_set: dict[str, Any]) -> None:
        properties_set['identified_by'].append({
            "type": "Name",
            "_label": entity.name,
            "content": entity.name})
        properties_set['identified_by'].append({
            "type": "Identifier",
            "_label": "System Identifier",
            "content": url_for(
                'api.entity_uuid',
                uuid=entity.uuid,
                _external=True)})

    def finalize_output(
            self,
            entity: Entity,
            properties_set: dict[str, Any],
            links_data: list[Link]) -> dict[str, Any]:
        self.add_core_metadata(entity, properties_set)
        if entity.description:
            self.handle_description(entity, properties_set)
        return ({'@context': app.config['API_CONTEXT']['LOUD']} |
                self.base_entity_dict(entity) |
                self.get_loud_timespan(entity, links_data) |
                properties_set)


def get_loud_entities(
        data: dict[str, Any],
        loud: dict[str, str],
        type_references: dict[int, list[Link]]) -> Any:
    entity = data['entity']
    formatter = LoudFormatter(loud, type_references)
    properties_set: dict[str, Any] = defaultdict(list)
    for link_ in data['links']:
        if link_.property.code in ['OA8', 'OA9']:
            continue

        formatter.process_link(
            link_, properties_set, is_inverse=False, root_entity=entity)
    file_links = []
    for link_ in data['links_inverse']:
        if link_.property.code in ['OA8', 'OA9']:
            continue
        if link_.domain.class_.name == 'file' and g.files.get(link_.domain.id):
            file_links.append(link_)
            continue
        formatter.process_link(
            link_, properties_set, is_inverse=True, root_entity=entity)
    formatter.process_media_links(file_links, properties_set, entity)
    return formatter.finalize_output(
        entity,
        properties_set,
        data['links'])
