from typing import Any, Optional

import requests
from flask import g

from openatlas import app
from openatlas.api.import_scripts.util import (
    get_exact_match, get_or_create_type, get_reference_system_by_name,
    request_arche_metadata)
from openatlas.database import reference_system as db
from openatlas.models.entity import Entity
from openatlas.models.reference_system import ReferenceSystem


def fetch_collection_data() -> dict[str, Any]:
    collections = get_collections()
    collection_jpgs = request_arche_metadata(collections['2_JPEGs'])
    return get_metadata(collection_jpgs)


def get_collections() -> dict[str, Any]:
    project_id = app.config['ARCHE']['id']
    collections_dict = {}
    for collection in request_arche_metadata(project_id)['@graph']:
        if collection['@type'] == 'n1:Collection':
            title = collection['n1:hasTitle']['@value']
            collections_dict[title] = collection['@id'].replace('n0:', '')
    return collections_dict


def get_metadata(data: dict[str, Any]) -> dict[str, Any]:
    existing_ids = get_existing_ids()
    metadata = {}
    for collection in data['@graph']:
        if collection['@type'] == "n1:Collection":
            if collection["n1:hasFilename"] == "2_JPEGs":
                continue
            id_ = collection['@id'].replace('n0:', '')
            if int(id_) in existing_ids:
                continue
            collection_url = data['@context']['n0'] + id_
            metadata[collection_url] = {
                'collection_id': id_,
                'filename': collection['n1:hasFilename']}
    return metadata


def get_existing_ids() -> list[int]:
    system = get_arche_reference_system()
    return [int(link_.description) for link_ in system.get_links('P67')]


def fetch_exif(id_: str) -> dict[str, Any]:
    req = requests.get(
        'https://arche-exif.acdh.oeaw.ac.at/',
        params={'id': id_},
        timeout=300)
    return req.json()


def get_single_image_of_collection(id_: int) -> str:
    file_collection = request_arche_metadata(id_)
    for resource in file_collection['@graph']:
        if resource['@type'] == 'n1:Resource':
            return file_collection['@context']['n0'] + \
                resource['@id'].replace('n0:', '')
    return 'string'


def get_orthophoto(filename: str) -> str:
    collections = get_collections()
    collection_ortho = request_arche_metadata(collections['4_Orthophotos'])
    id_ = ''
    for entry in collection_ortho['@graph']:
        if entry['@type'] == 'n1:Collection' and \
                entry['n1:hasTitle']['@value'] == filename:
            folder = request_arche_metadata(entry['@id'].replace('n0:', ''))
            for item in folder['@graph']:
                if item['@type'] == 'n1:Resource':
                    if item['n1:hasFormat'] == 'image/png':
                        id_ = collection_ortho['@context']['n0'] \
                              + item['@id'].replace('n0:', '')
                        break
    return id_


def import_arche_data() -> int:
    count = 0
    person_types = get_or_create_person_types()
    for entries in fetch_collection_data().values():
        name = entries['filename']
        artifact = Entity.insert('artifact', name)
        if ref := get_reference_system_by_name('ARCHE'):
            ref.link(
                'P67',
                artifact,
                entries['collection_id'],
                type_id=get_exact_match().id)
        artifact.link(
            'P53',
            Entity.insert('object_location', f"Location of {name}"))
        exif = get_exif(entries)
        file = Entity.insert('file', name, f"Created by {exif['Creator']}")
        file.link(
            'P2',
            get_or_create_type(
                get_hierarchy_by_name('License'),
                exif['Copyright']))
        filename = f"{file.id}.png"
        ortho_photo: str = get_orthophoto(entries['filename'])
        thumb_req = requests.get(
            'https://arche-thumbnails.acdh.oeaw.ac.at/',
            params={'id': ortho_photo, 'width': 1200},  # type: ignore
            timeout=60).content
        with open(str(app.config['UPLOAD_PATH'] / filename), "wb") as file_:
            file_.write(thumb_req)
        file.link('P67', artifact)
        creator = get_or_create_person(
            exif['Creator'],
            person_types['photographer_type'])
        creation = Entity.insert(
            'creation',
            f'Creation of photograph from {name}')
        creation.update({'attributes': {'begin_from': exif['CreateDate']}})
        creation.link('P94', file)
        creation.link('P14', creator)
        count += 1
    return count


def get_exif(entries: dict[str, Any]) -> dict[str, Any]:
    single_img_id = get_single_image_of_collection(entries['collection_id'])
    return fetch_exif(single_img_id)


def get_hierarchy_by_name(name: str) -> Optional[Entity]:
    type_ = None
    for type_id in g.types:
        if g.types[type_id].name == name and not g.types[type_id].root:
            type_ = g.types[type_id]
    return type_


def get_or_create_person(name: str, relevance: Entity) -> Entity:
    for entity in Entity.get_by_cidoc_class('E21'):
        if entity.name == name:
            return entity
    entity = Entity.insert('person', name, 'Created by ARCHE import')
    entity.link('P2', relevance)
    return entity


def get_or_create_person_types() -> dict[str, Any]:
    hierarchy = get_hierarchy_by_name('Relevance')
    if not hierarchy:
        if hierarchy := Entity.insert('type', 'Relevance'):  # type: ignore
            Entity.insert_hierarchy(hierarchy, 'custom', ['person'], True)
    return {
        'photographer_type': get_or_create_type(hierarchy, 'Photographer'),
        'artist_type': get_or_create_type(hierarchy, 'Graffito artist')}


def get_arche_reference_system() -> ReferenceSystem:
    system = None
    for system_ in g.reference_systems.values():
        if system_.name == 'ARCHE':
            system = system_
    if not system:
        system = ReferenceSystem.insert_system({
            'name': 'ARCHE',
            'description': 'ARCHE by ACDH-CH (autogenerated)',
            'website_url': 'https://arche.acdh.oeaw.ac.at/',
            'resolver_url': f"{app.config['ARCHE']['url']}/browser/detail/"})
    if 'artifact' not in system.classes:
        db.add_classes(system.id, ['artifact'])
    return system
