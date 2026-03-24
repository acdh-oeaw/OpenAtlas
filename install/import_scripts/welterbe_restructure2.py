"""
This script is for restructuring type hierarchies for the Welterbe project.
Basically some building levels types will be merged, see issue #2764

# Todo
* Remove duplicates
* Own hierarchy for Nutzungsart (Nutzungsart aktuell)
* Descriptions of sub types available?
* Make categories unselectable?
"""

import time
from pprint import pprint
from typing import Any

import psycopg2
from flask import g
from psycopg2 import extras

from openatlas import app
from openatlas.models.entity import Entity, insert
from openatlas.database import entity as db
from openatlas.database.checks import delete_link_duplicates


def connect() -> Any:
    return psycopg2.connect(
        database='openatlas_welterbe',
        user=app.config['DATABASE_USER'],
        password=app.config['DATABASE_PASS'],
        port=app.config['DATABASE_PORT'],
        host=app.config['DATABASE_HOST'])


start = time.time()
connection = connect()
cursor = connection.cursor(cursor_factory=extras.DictCursor)


def get_mapping() -> None:
    for name in [
            '10 Gebäude - 05 Erdgeschoß',
            '10 Gebäude - 06 1.Obergeschoß',
            '10 Gebäude - 06 2.Obergeschoß',
            '10 Gebäude - 06 3.Obergeschoß',
            '10 Gebäude - 06 4.Obergeschoß',
            '10 Gebäude - 06 5.Obergeschoß']:
        old_hierarchy = Entity.get_hierarchy(name)
        for id_ in old_hierarchy.subs:
            type_ = g.types[id_]
            if type_.name == 'vorhanden':
                continue
            if type_.name not in mapping:
                mapping[type_.name] = {'org_ids': [], 'subs': {}}
            mapping[type_.name]['org_ids'].append(id_)
            for id_ in type_.subs:
                sub = g.types[id_]
                if sub.name not in mapping[type_.name]['subs']:
                    mapping[type_.name]['subs'][sub.name] = {'org_ids': []}
                mapping[type_.name]['subs'][sub.name]['org_ids'].append(id_)
                if sub.subs:
                    print(f'Warning: there are subs in {sub.id}')


def insert_new_types() -> None:
    for name in mapping:
        new_type = insert({
            'name': name,
            'description': '',
            'openatlas_class_name': 'type'})
        new_type.link('P127', hierarchy)
        mapping[name]['new_id'] = new_type.id
        for sub_name in mapping[name]['subs']:
            new_sub = insert({
                'name': sub_name,
                'description': '',
                'openatlas_class_name': 'type'})
            new_sub.link('P127', new_type)
            mapping[name]['subs'][sub_name]['new_id'] = new_sub.id


def insert_new_type_links() -> None:
    for name in mapping:
        g.cursor.execute(
            """
            UPDATE model.link
            SET range_id = %(new_id)s
            WHERE property_code = 'P2' AND range_id IN %(org_ids)s;
            """, {
                'new_id': mapping[name]['new_id'],
                'org_ids': tuple(mapping[name]['org_ids'])})
        for sub_name in mapping[name]['subs']:
            g.cursor.execute(
                """
                UPDATE model.link
                SET range_id = %(new_id)s
                WHERE property_code = 'P2' AND range_id IN %(org_ids)s;
                """, {
                    'new_id': mapping[name]['subs'][sub_name]['new_id'],
                    'org_ids':
                        tuple(mapping[name]['subs'][sub_name]['org_ids'])})

def clean_up():
    for sub_id in hierarchy.get_sub_ids_recursive():
        g.types[sub_id].delete()


with app.test_request_context():
    app.preprocess_request()
    hierarchy = g.types[27145]
    clean_up()
    mapping = {}
    get_mapping()
    insert_new_types()
    insert_new_type_links()
# pprint(mapping)
print(f'Execution time: {int(time.time() - start)} seconds')
