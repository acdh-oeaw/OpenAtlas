import mimetypes
from collections import defaultdict
from typing import Any, Optional

import validators
from flask import g, url_for

from openatlas import app
from openatlas.api.resources.util import (
    date_to_utc_iso_str, get_crm_code, get_crm_relation,
    get_iiif_manifest_and_path,
    get_license_type, remove_spaces_dashes)
from openatlas.display.util2 import get_file_path
from openatlas.models.entity import Entity, Link
from openatlas.models.gis import get_wkt_by_id

unit_map = {
    'B': 'bytes',
    'KB': 'kilobytes',
    'MB': 'megabytes',
    'GB': 'gigabytes',
    'TB': 'terabytes'}


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
        entity: Entity,
        type_references: dict[int, list[Link]]) -> dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(g.files[entity.id])
    file_ = get_file_path(entity.id)
    digital_object: dict[str, Any] = {
        'format': mime_type,
        "classified_as": [{
            "id": "https://vocab.getty.edu/aat/300215302",
            "type": "Type",
            "_label": "Digital Image"}]}
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
                    '_label': license_holder.name,
                    'type': 'Actor'}]})
    if entity.creator:
        for creator in entity.creator:
            digital_object.update({'created_by': [{
                '_label': f'Creation of {entity.name}',
                'type': 'Creation',
                'carried_out_by': [{
                    '_label': creator.name,
                    'type': 'Actor'}]}]})
    if license_ := get_license_type(entity):
        subject_to: dict[str, Any] = {
            'type': "Right",
            '_label': f'License of {entity.name}',
            "identified_by": [{
                'id': url_for(
                    'api.entity',
                    id_=license_.id,
                    _external=True),
                "type": "Name",
                "content": license_.name}]}
        classified_as = []
        for type_link in type_references.get(license_.id, []):
            url = type_link.domain.name
            if type_link.domain.class_.name == 'reference_system':
                system = g.reference_systems[type_link.domain.id]
                url = f'{system.resolver_url or ''}{type_link.description}'
            classified_as.append({
                "id": url,
                "type": "Type",
                "_label": license_.name})
        if classified_as:
            subject_to['classified_as'] = classified_as
        digital_object.update({'subject_to': [subject_to]})
    return digital_object


def get_loud_entities(
        data: dict[str, Any],
        loud: dict[str, str],
        type_references: dict[int, list[Link]]) -> Any:
    entity = data['entity']

    def get_range_links() -> dict[str, Any]:
        property_: Any = {
            'id': url_for(
                'api.entity',
                id_=link_.range.id,
                _external=True),
            'type': loud[get_crm_code(link_).replace(' ', '_')],
            '_label': link_.range.name}
        if link_.dates.begin_from or link_.dates.end_from:
            property_ = property_ | get_loud_timespan(link_)
        code_ = link_.property.code
        if code_ == 'P2':
            if link_.description:
                property_['value'] = link_.description
                property_['unit'] = {
                    'type': "MeasurementUnit",
                    '_label': link_.range.description}
            super_type = g.types[g.types[link_.range.id].root[-1]]
            property_['part_of'] = [
                get_type_property(super_type, type_references)]
        elif link_.type:
            property_['classified_as'] = [
                get_type_property(g.types[link_.type.id], type_references)]
        if code_ == 'P67' and link_.description:
            property_['content'] = link_.description
        if code_ == 'OA7':
            relationship = {
                'type': 'Event',
                '_label':
                    f'Relationship between '
                    f'{link_.domain.name} and {link_.range.name}',
                'had_participant': [property_]}
            if link_.type:
                relationship['classified_as'] = [
                    get_type_property(g.types[link_.type.id], type_references)]
            property_ = relationship
        if code_ == 'P1':
            del property_['_label']
            del property_['id']
            property_['content'] = link_.range.name

        return property_

    def get_domain_links() -> dict[str, Any]:
        property_: Any = {
            'id': url_for(
                'api.entity',
                id_=link_.domain.id,
                _external=True),
            'type': loud[get_crm_code(link_, True).replace(' ', '_')],
            '_label': link_.domain.name}
        if link_.dates.begin_from or link_.dates.end_from:
            property_ = property_ | get_loud_timespan(link_)
        code_ = link_.property.code
        if code_ == 'P2':
            if link_.description:
                property_['value'] = link_.description
                property_['unit'] = {
                    'type': "MeasurementUnit",
                    '_label': link_.domain.description}
            super_type = g.types[g.types[link_.range.id].root[-1]]
            property_['part_of'] = [
                get_type_property(super_type, type_references)]
        elif link_.type:
            property_['classified_as'] = [
                get_type_property(g.types[link_.type.id], type_references)]
        if code_ == 'P67':
            property_['classified_as'] = []
            if link_.domain.class_.name == 'file':
                property_['type'] = 'DigitalObject'
            if standard_type := get_standard_type_loud(link_.domain.types):
                property_['classified_as'].append(
                    get_type_property(standard_type, type_references))

            if link_.description:
                property_['content'] = link_.description
            if link_.description and link_.domain.cidoc_class.code == 'E32':
                pass
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
                    "type": "LinguisticObject",
                    "digitally_carried_by": [{
                        "type": "DigitalObject",
                        "classified_as": [{
                            "id": "https://vocab.getty.edu/aat/300264578",
                            "type": "Type",
                            "_label": "Web Page"}],
                        "format": "text/html",
                        "_label": link_.description,
                        "access_point": [{
                            "id": link_.domain.name,
                            "type": "DigitalObject"}]}]}
        if code_ == 'OA7':
            relationship = {
                'type': 'Event',
                '_label':
                    f'Relationship between '
                    f'{link_.range.name} and {link_.domain.name}',
                'had_participant': [property_]}
            if link_.type:
                relationship['classified_as'] = [
                    get_type_property(g.types[link_.type.id], type_references)]
            property_ = [relationship]
        return property_

    properties_set = defaultdict(list)
    for link_ in data['links']:
        if link_.property.code in ['OA8', 'OA9']:
            continue
        elif link_.property.code == 'OA7':
            property_name = 'participated_in'
        elif link_.property.code == 'P67':
            property_name = 'refers_to'
            if link_.domain.class_.name == 'file':
                property_name = 'digitally_carries'
        else:
            property_name = get_loud_property_name(loud, link_)

        if link_.property.code == 'P53':
            for geom in get_wkt_by_id(link_.range.id):
                base_property = get_range_links() | geom
                properties_set[property_name].append(base_property)
        else:
            base_property = get_range_links()
            properties_set[property_name].append(base_property)

    file_links = []
    for link_ in data['links_inverse']:
        if link_.property.code in ['OA8', 'OA9']:
            continue
        elif link_.property.code == 'OA7':
            property_name = 'participated_in'
        elif link_.domain.class_.name == 'external_reference':
            property_name = 'subject_of'
        elif link_.domain.class_.name == 'file' and g.files.get(
                link_.domain.id):
            file_links.append(link_)
            continue
        else:
            property_name = get_loud_property_name(loud, link_, inverse=True)

        if link_.property.code == 'P53':
            for geom in get_wkt_by_id(link_.range.id):
                base_property = get_domain_links() | geom
                properties_set[property_name].append(base_property)
        elif link_.property.code == 'P67' and \
                link_.domain.cidoc_class.code == 'E32':
            match_property = 'equivalent'
            if g.types.get(link_.type.id) and \
                    'close' in g.types[link_.type.id].name:
                match_property = 'related'
            system = g.reference_systems[link_.domain.id]
            properties_set[match_property].append({
                "id": f'{system.resolver_url or ''}{link_.description}',
                "type": entity.cidoc_class.name})
            properties_set['identified_by'].append({
                "type": "Identifier",
                "content": link_.description,
                "_label": f"{link_.domain.name} Identifier",
                "classified_as": [{
                    "id": "https://vocab.getty.edu/aat/300404620",
                    "type": "Type",
                    "_label": "Authority Control Number"}],
                "part_of": [{
                    "id": system.website_url,
                    "type": "Set",
                    "_label": link_.domain.name}]})
        elif link_.property.code == 'P107':
            properties_set['member_of'].append({
                'id': url_for(
                    'api.entity',
                    id_=link_.domain.id,
                    _external=True),
                'type': loud[get_crm_code(link_, True).replace(' ', '_')],
                '_label': link_.domain.name})
            if link_.type or link_.dates.dates_available():
                carried_out = {
                    "type": "Activity",
                    "carried_out_on_behalf_of": [{
                        'id': url_for(
                            'api.entity',
                            id_=link_.domain.id,
                            _external=True),
                        'type': loud[get_crm_code(
                            link_, True).replace(' ', '_')],
                        '_label': link_.domain.name}]}
                label = f"Membership in {link_.domain.name}"
                if link_.type:
                    if type_ := g.types.get(link_.type.id):
                        label = f"Role as {type_.name} at {link_.domain.name}"
                    if type_ := get_type_property(
                            g.types[link_.type.id],
                            type_references):
                        carried_out['classified_as'] = [type_]

                carried_out['_label'] = label
                if link_.dates.dates_available():
                    carried_out = carried_out | get_loud_timespan(link_)
                properties_set['carried_out'].append(carried_out)
        else:
            base_property = get_domain_links()
            properties_set[property_name].append(base_property)

    if file_links:
        properties_set['representation'].extend(
            get_loud_representations(file_links, type_references))
        properties_set['subject_of'].extend(
            get_loud_iiif_subject_of(file_links))

    if entity.class_.name == 'file' and g.files.get(entity.id):
        properties_set.update(get_file_dimensions(entity))
        properties_set.update(get_digital_object_details(
            entity,
            type_references))

    properties_set['identified_by'].append({
        "type": "Name",
        "content": entity.name})
    # This needs to be replaced by UUID
    properties_set['identified_by'].append({
        "type": "Identifier",
        "content": url_for(
            'api.entity',
            id_=entity.id,
            _external=True)})
    properties_set['referred_to_by'].append({
        "type": "LinguisticObject",
        "content": entity.description,
        "classified_as": [{
            "id": "https://vocab.getty.edu/aat/300435416",
            "type": "Type",
            "_label": "Description"}]})

    return ({'@context': app.config['API_CONTEXT']['LOUD']} |
            base_entity_dict(entity) |
            get_loud_timespan(entity, data['links']) |
            properties_set)


def base_entity_dict(entity: Entity) -> dict[str, Any]:
    type_ = remove_spaces_dashes(entity.cidoc_class.i18n['en'])
    if entity.class_.name == 'file':
        type_ = 'DigitalObject'
    return {
        'id': url_for(
            'api.entity',
            id_=entity.id,
            _external=True),
        'type': type_,
        '_label': entity.name}


def get_loud_property_name(
        loud: dict[str, str],
        link_: Link,
        inverse: bool = False) -> str:
    name = 'part' if inverse else 'part_of'
    if not link_.property.code == 'P127':
        name = loud[get_crm_relation(link_, inverse).replace(' ', '_')]
    return name


def get_loud_representations(
        image_links: list[Link],
        type_references: dict[int, list[Link]]) -> list[dict[str, Any]]:
    representation = []
    for link_ in image_links:
        entity = link_.domain
        image = {
            'id': url_for(
                'api.entity',
                id_=entity.id,
                _external=True),
            '_label': entity.name,
            'type': 'DigitalObject'}
        image.update(get_digital_object_details(entity, type_references))
        representation.append({
            'type': 'VisualItem',
            'digitally_shown_by': [image]})

    return representation


def get_loud_iiif_subject_of(image_links: list[Link]) -> list[dict[str, Any]]:
    subject_of = []
    for link_ in image_links:
        entity = link_.domain
        manifest_path = get_iiif_manifest_and_path(entity.id)
        if (manifest_path.get('IIIFManifest')
                and manifest_path.get('IIIFBasePath')):
            subject_of.append({
                "type": "LinguisticObject",
                "digitally_carried_by": [{
                    "type": "DigitalObject",
                    "access_point": [{
                        "id": manifest_path['IIIFManifest'],
                        "type": "DigitalObject"}],
                    "conforms_to": [{
                        "id": "https://iiif.io/api/presentation/2.0/",
                        "type": "InformationObject"}],
                    "format":
                        "application/ld+json;profile='https://iiif.io/api"
                        "/presentation/2/context.json'"}]})
    return subject_of


def get_loud_person_timespan(
        entity: Entity,
        links_: list[Link] | None) -> dict[str, Any]:
    result = {}
    birth_event: dict[str, Any] = {
        'type': 'Birth',
        '_label': f'Birth of {entity.name}'}
    has_birth_data = False
    if entity.dates.begin_from or entity.dates.begin_to:
        birth_event['timespan'] = (
                {'type': 'TimeSpan'} | get_loud_begin_dates(entity))
        has_birth_data = True

    death_event: dict[str, Any] = {
        'type': 'Death',
        '_label': f'Death of {entity.name}'}
    has_death_data = False
    if entity.dates.end_from or entity.dates.end_to:
        death_event['timespan'] = (
                {'type': 'TimeSpan'} | get_loud_end_dates(entity))
        has_death_data = True

    if links_:
        for link_ in links_:
            place = {
                'id': url_for(
                    'api.entity',
                    id_=link_.range.id,
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


def get_loud_group_timespan(
        entity: Entity,
        links_: list[Link] | None) -> dict[str, Any]:
    res = {}
    form: dict[str, Any] = {
        'type': 'Formation',
        '_label': f'Formation of {entity.name}'}
    has_formation = False
    if entity.dates.begin_from or entity.dates.begin_to:
        form['timespan'] = (
                {'type': 'TimeSpan'} | get_loud_begin_dates(entity))
        has_formation = True

    diss: dict[str, Any] = {
        'type': 'Dissolution',
        '_label': f'Dissolution of {entity.name}'}
    has_dissolution = False
    if entity.dates.end_from or entity.dates.end_to:
        diss['timespan'] = (
                {'type': 'TimeSpan'} | get_loud_end_dates(entity))
        has_dissolution = True
    if links_:
        for lnk in links_:
            place = {
                'id': url_for('api.entity', id_=lnk.range.id, _external=True),
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


def get_loud_timespan(
        entity: Entity,
        links_: list[Link] | None = None) -> dict[str, Any]:
    if not isinstance(entity, Link):
        if entity.class_.name == 'person':
            return get_loud_person_timespan(entity, links_)
        elif entity.class_.name == 'group':
            return get_loud_group_timespan(entity, links_)
    if not entity.dates.dates_available():
        return {}
    return {'timespan': (
            {'type': 'TimeSpan'} |
            get_loud_begin_dates(entity) |
            get_loud_end_dates(entity))}


def get_loud_begin_dates(entity: Entity | Link) -> dict[str, Any]:
    data = {
        'begin_of_the_begin': date_to_utc_iso_str(entity.dates.begin_from),
        'end_of_the_begin': date_to_utc_iso_str(entity.dates.begin_to),
        'beginning_is_qualified_by': entity.dates.begin_comment}
    return {k: v for k, v in data.items() if v is not None}


def get_loud_end_dates(entity: Entity | Link) -> dict[str, Any]:
    data = {
        'begin_of_the_end': date_to_utc_iso_str(entity.dates.end_from),
        'end_of_the_end': date_to_utc_iso_str(entity.dates.end_to),
        'end_is_qualified_by': entity.dates.end_comment}
    return {k: v for k, v in data.items() if v is not None}


def get_type_property(
        type_: Entity,
        type_references: dict[int, list[Link]]) -> dict[str, Any]:
    property_: dict[str, Any] = {
        'id': url_for(
            'api.entity',
            id_=type_.id,
            _external=True),
        'type': remove_spaces_dashes(type_.cidoc_class.i18n['en']),
        '_label': type_.name}
    if type_.dates.begin_from or type_.dates.end_from:
        property_ = property_ | get_loud_timespan(type_)
    for super_type in [g.types[root] for root in type_.root]:
        property_['part_of'] = [get_type_property(super_type, type_references)]

    external_references = {}
    for type_link in type_references.get(type_.id, []):
        url = type_link.domain.name
        if type_link.domain.class_.name == 'reference_system':
            system = g.reference_systems[type_link.domain.id]
            url = f'{system.resolver_url or ''}{type_link.description}'
        if not validators.url(url):
            continue
        match_property = 'equivalent'
        if g.types.get(type_link.type.id) and \
                'close' in g.types[type_link.type.id].name:
            match_property = 'related'
        if match_property not in external_references:
            external_references[match_property] = []
        external_references[match_property].append({
            "id": url,
            "type": "Type",
            "_label": type_.name})
    return property_ | external_references


def get_standard_type_loud(types: dict[Entity, Any]) -> Optional[Entity]:
    standard = None
    for type_ in types:
        if type_.category == 'standard':
            standard = type_
    return standard
