from pathlib import Path
from typing import Any

from flask import g, url_for

from openatlas import app
from openatlas.models.entity import Entity
from openatlas.models.overlay import Overlay
from tests.base import TestBaseCase, get_hierarchy, insert


class PlaceTest(TestBaseCase):

    def test_place(self) -> None:
        c = self.client
        with app.test_request_context():
            app.preprocess_request()
            reference = insert('external_reference', 'https://d-nb.info')
            source = insert('source', 'Necronomicon')

        unit_type = get_hierarchy('Administrative unit')
        data: dict[Any, Any] = {
            'name': 'Asgard',
            'alias-0': 'Valhöll',
            unit_type.id: str([unit_type.subs[0], unit_type.subs[1]]),
            f'reference_system_id_{g.geonames.id}':
                ['123456', self.precision_type.subs[0]]}
        rv = c.post(
            url_for('insert', class_='place', origin_id=reference.id),
            data=data,
            follow_redirects=True)
        assert b'Asgard' in rv.data and b'An entry has been' in rv.data

        place_type = get_hierarchy('Place')
        data[place_type.id] = place_type.subs
        data['gis_points'] = """[{
            "type": "Feature",
            "geometry": {"type":"Point","coordinates":[9,17]},
            "properties": {
                "name": "Valhalla",
                "description": "",
                "shapeType": "centerpoint"}}]"""
        data['gis_lines'] = """[{
            "type": "Feature",
            "geometry":{
                "type": "LineString",
                "coordinates": [
                    [9.75307425847859,17.8111792731339],
                    [9.75315472474904,17.8110005175436],
                    [9.75333711496205,17.8110873417098]]},
            "properties": {
                "name": "",
                "description": "",
                "shapeType": "line"}}]"""
        data['gis_polygons'] = """[{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [9.75307425847859,17.8111792731339],
                    [9.75315472474904,17.8110005175436],
                    [9.75333711496205,17.8110873417098],
                    [9.75307425847859,17.8111792731339]]]},
            "properties":{
                "name": "",
                "description": "",
                "shapeType": "shape"}}]"""
        rv = c.post(
            url_for('insert', class_='place', origin_id=source.id),
            data=data,
            follow_redirects=True)
        assert b'Necronomicon' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            places = Entity.get_by_class('place')
            place = places[0]
            place2 = places[1]
            location = place2.get_linked_entity_safe('P53')
            actor = insert('person', 'Milla Jovovich')
            actor.link('P74', location)

        data['continue_'] = ''
        data['alias-1'] = 'Val-hall'
        data['geonames_id'] = '321'
        rv = c.post(
            url_for('update', id_=place.id),
            data=data,
            follow_redirects=True)
        assert b'Val-hall' in rv.data

        rv = c.get(url_for('view', id_=place.id+1))
        assert b"can't be viewed directly" in rv.data

        data['geonames_id'] = ''
        rv = c.post(
            url_for('update', id_=place.id),
            data=data,
            follow_redirects=True)
        assert b'Val-hall' in rv.data

        data['gis_polygons'] = """[{
            "type": "Feature", 
            "geometry": {
                "type": "Polygon", 
                "coordinates": [[
                    [298.9893436362036, -5.888919049309554], 
                    [299.00444983737543, -5.9138487869408545],
                    [299.00650977389887, -5.893358673645309], 
                    [298.9848804404028, -5.9070188333813585],
                    [298.9893436362036, -5.888919049309554]]]},
            "properties": {
            "name": "", 
            "description": "", 
            "shapeType": "shape"}}]"""
        rv = c.post(
            url_for('update', id_=place.id),
            data=data,
            follow_redirects=True)
        assert b'An invalid geometry was entered' in rv.data

        with open(Path(app.root_path) / 'static' / 'images' / 'layout'
                  / 'logo.png', 'rb') as img:
            rv = c.post(
                url_for('insert', class_='file', origin_id=place.id),
                data={'name': 'X-Files', 'file': img},
                follow_redirects=True)
        assert b'An entry has been created' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            file = Entity.get_by_class('file')[0]
            link_id = file.link('P67', place)[0]

        rv = c.get(
            url_for(
                'overlay_insert',
                image_id=file.id,
                place_id=place.id,
                link_id=link_id))
        assert b'X-Files' in rv.data

        data = {
            'top_left_easting': 42,
            'top_left_northing': 12,
            'top_right_easting': 43,
            'top_right_northing': 13,
            'bottom_left_easting': 10,
            'bottom_left_northing': 20}
        rv = c.post(
            url_for(
                'overlay_insert',
                image_id=file.id,
                place_id=place.id,
                link_id=link_id),
            data=data,
            follow_redirects=True)
        assert b'Edit' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            overlay = Overlay.get_by_object(place)
            overlay_id = overlay[list(overlay.keys())[0]].id

        rv = c.get(
            url_for(
                'overlay_update',
                overlay_id=overlay_id,
                place_id=place.id))
        assert b'42' in rv.data

        rv = c.post(
            url_for(
                'overlay_update',
                overlay_id=overlay_id,
                place_id=place.id),
            data=data,
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(
            url_for('overlay_remove', id_=overlay_id, place_id=place.id),
            follow_redirects=True)
        assert b'42' in rv.data

        rv = c.post(
            url_for('entity_add_file', id_=place.id),
            data={'checkbox_values': str([file.id])},
            follow_redirects=True)
        assert b'X-Files' in rv.data

        rv = c.get(url_for('reference_add', id_=reference.id, view='place'))
        assert b'Val-hall' in rv.data

        rv = c.get(url_for('entity_add_reference', id_=place.id))
        assert b'link reference' in rv.data

        rv = c.post(
            url_for('type_move_entities', id_=unit_type.subs[0]),
            data={
                unit_type.id: unit_type.subs[1],
                'selection': location.id,
                'checkbox_values': str([location.id])},
            follow_redirects=True)
        assert b'Entities were updated' in rv.data

        rv = c.post(
            url_for('type_move_entities', id_=unit_type.subs[1]),
            data={
                unit_type.id: unit_type.subs[0],
                'selection': location.id,
                'checkbox_values': str([location.id])},
            follow_redirects=True)
        assert b'Entities were updated' in rv.data

        data = {'name': 'Try', 'continue_': 'sub', 'super': place.id}
        rv = c.post(
            url_for('insert', class_='place'),
            data=data,
            follow_redirects=True)
        assert b'insert and add strati' in rv.data

        data['name'] = "It's not a bug, it's a feature!"
        rv = c.post(
            url_for('insert', class_='feature', origin_id=place.id),
            data=data)
        feat_id = rv.location.split('/')[-1]

        rv = c.get(url_for('update', id_=feat_id))
        assert b'Val-hall' in rv.data

        rv = c.get(
            url_for('insert', class_='stratigraphic_unit', origin_id=feat_id),
            data=data)
        assert b'insert and add human remains' in rv.data

        data['name'] = "I'm a stratigraphic unit"
        data['super'] = feat_id
        rv = c.post(
            url_for('insert', class_='stratigraphic_unit', origin_id=feat_id),
            data=data)
        strati_id = rv.location.split('/')[-1]

        rv = c.get(url_for('update', id_=strati_id))
        assert b'a stratigraphic unit' in rv.data

        data = {
            'name': 'You never find me',
            'super': strati_id,
            get_hierarchy('Dimensions').subs[0]: 50}
        rv = c.post(
            url_for('insert', class_='artifact', origin_id=strati_id),
            data=data)
        find_id = rv.location.split('/')[-1]

        # Create a second artifact to test siblings pager
        rv = c.post(
            url_for('insert', class_='artifact', origin_id=strati_id),
            data=data,
            follow_redirects=True)
        assert b'An entry has been created' in rv.data

        rv = c.get(url_for('update', id_=find_id))
        assert b'You never find me' in rv.data

        remains_type = get_hierarchy('Human remains')
        rv = c.post(
            url_for('insert', class_='human_remains', origin_id=strati_id),
            data={
                'name': 'My human remains',
                'actor': actor.id,
                'super': strati_id,
                remains_type.id: str([remains_type.subs[0]])})
        human_remains_id = rv.location.split('/')[-1]

        rv = c.get(
            url_for('insert', class_='human_remains', origin_id=strati_id))
        assert b'exists' in rv.data

        rv = c.get(url_for('update', id_=human_remains_id))
        assert b'My human remains' in rv.data

        rv = c.get('/')
        assert b'My human remains' in rv.data

        rv = c.get(url_for('view', id_=remains_type.subs[0]))
        assert b'My human remains' in rv.data

        rv = c.get(
            url_for('delete', id_=human_remains_id),
            follow_redirects=True)
        assert b'The entry has been deleted' in rv.data

        rv = c.post(
            url_for('sex_update', id_=strati_id),
            data={'Glabella': 'Female'},
            follow_redirects=True)
        assert b'Female' in rv.data

        rv = c.post(
            url_for('sex_update', id_=strati_id),
            data={'Glabella': 'Female?'},
            follow_redirects=True)
        assert b'Female?' in rv.data

        rv = c.get(url_for('sex_update', id_=strati_id))
        assert b'Glabella' in rv.data

        data = {
            'lab_id': 'VERA',
            'spec_id': 'S',
            'radiocarbon_year': 1,
            'range': 1}
        rv = c.post(
            url_for('carbon_update', id_=strati_id),
            data=data,
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.post(
            url_for('carbon_update', id_=strati_id),
            data=data,
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(url_for('view', id_=strati_id))
        assert b'radiocarbon dating' in rv.data
        assert b'sex estimation' in rv.data

        rv = c.get(url_for('carbon_update', id_=strati_id))
        assert b'VERA' in rv.data

        rv = c.get(url_for('carbon', id_=strati_id))
        assert b'VERA' in rv.data

        rv = c.get(url_for('sex_delete', id_=strati_id), follow_redirects=True)
        assert b'tools' in rv.data

        rv = c.post(
            url_for('update', id_=strati_id),
            data={'name': 'New name', 'super': feat_id},
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(url_for('view', id_=feat_id))
        assert b'not a bug' in rv.data

        rv = c.get(url_for('view', id_=find_id))
        assert b'You never' in rv.data

        rv = c.get(url_for('delete', id_=place.id), follow_redirects=True)
        assert b'not possible if subunits' in rv.data
