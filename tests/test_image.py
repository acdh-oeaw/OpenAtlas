from pathlib import Path
from shutil import copyfile

from flask import g, url_for

from openatlas import app
from openatlas.display.image_processing import safe_resize_image
from openatlas.display.util import profile_image
from openatlas.models.entity import Entity
from tests.base import TestBaseCase, get_hierarchy, insert


class ImageTest(TestBaseCase):

    def test_image(self) -> None:
        c = self.client
        app.config['IMAGE_SIZE']['tmp'] = '1'
        with app.test_request_context():
            app.preprocess_request()
            place = insert('place', 'Nostromos')

        # Resizing through UI insert
        with open(Path(app.root_path) / 'static'
                  / 'images' / 'layout' / 'logo.png', 'rb') as img:
            rv = c.post(
                url_for('insert', class_='file', origin_id=place.id),
                data={'name': 'OpenAtlas logo', 'file': img},
                follow_redirects=True)
        assert b'An entry has been created' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            files = Entity.get_by_class('file')
            file_id = files[0].id

        rv = c.get(
            url_for('set_profile_image', id_=file_id, origin_id=place.id),
            follow_redirects=True)
        assert b'Remove' in rv.data

        rv = c.get(url_for('delete', id_=file_id), follow_redirects=True)
        assert b'The entry has been deleted' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            file_pathless = insert('file', 'Pathless_File')
            file = insert('file', 'Test_File')
            file.link('P2', g.types[get_hierarchy('License').subs[0]])
            file_name = f'{file.id}.jpeg'
            copyfile(
                Path(app.root_path)
                / 'static' / 'images' / 'layout' / 'logo.png',
                Path(app.config['UPLOAD_PATH'] / file_name))
            file2 = insert('file', 'Test_File2')
            file2.link('P2', g.types[get_hierarchy('License').subs[0]])
            copyfile(
                Path(app.root_path)
                / 'static' / 'images' / 'layout' / 'logo.png',
                Path(app.config['UPLOAD_PATH'] / f'{file2.id}.jpeg'))
            file_json = insert('file', 'Test')
            copyfile(
                Path(app.root_path) / 'static' / 'manifest.json',
                Path(app.config['UPLOAD_PATH'] / f'{file_json.id}.json'))
            safe_resize_image(file2.id, '.png', size="???")
            profile_image(file_pathless)

        rv = c.get(url_for('view', id_=file_json.id))
        assert b'no preview available' in rv.data

        rv = c.get(url_for('view', id_=file_pathless.id))
        assert b'Missing file' in rv.data

        rv = c.get(url_for('index', view='file'))
        assert b'Test_File' in rv.data

        rv = c.get(url_for('display_file', filename=file_name))
        assert b'\xff' in rv.data

        c.get(
            url_for(
                'display_file',
                filename=file_name,
                size=app.config['IMAGE_SIZE']['thumbnail']))
        # assert b'\xff' in rv.data  # GitHub struggles with this test

        c.get(
            url_for('api.display', filename=file_name, image_size='thumbnail'))
        # assert b'\xff' in rv.data  # GitHub struggles with this test

        app.config['IMAGE_SIZE']['tmp'] = '<'
        rv = c.get(url_for('view', id_=file.id))
        assert b'Test_File' in rv.data

        app.config['IMAGE_SIZE']['tmp'] = '1'
        rv = c.get(url_for('resize_images'), follow_redirects=True)
        assert b'Images were created' in rv.data

        rv = c.get(
            url_for('admin_delete_orphaned_resized_images'),
            follow_redirects=True)
        assert b'Resized orphaned images were deleted' in rv.data

        with app.test_request_context():
            app.preprocess_request()
            files = Entity.get_by_class('file')

        for file in files:
            rv = c.get(url_for('delete', id_=file.id), follow_redirects=True)
            assert b'The entry has been deleted' in rv.data
