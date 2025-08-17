from flask import url_for

from openatlas import app
from tests.base import TestBaseCase, insert


class SourceTest(TestBaseCase):

    def test_source(self) -> None:
        c = self.client
        with app.test_request_context():
            app.preprocess_request()
            gillian = insert('person', 'Gillian Anderson Gillian Anderson')
            artifact = insert('artifact', 'Artifact with inscription')
            reference = insert('external_reference', 'https://d-nb.info')

        rv = c.post(
            url_for('insert', class_='source'),
            data={
                'name': 'Necronomicon',
                'description': (
                    'The <mark meta="{"annotationId":"c27",'
                    f'"entityId":{artifact.id},'
                    '"comment":"asdf"}">Necronomicon</mark>,'
                    ' also referred to as the Book of the Dead')})
        source_id = rv.location.split('/')[-1]

        rv = c.get(url_for('insert', class_='source', origin_id=artifact.id))
        assert b'Artifact with inscription' in rv.data

        rv = c.get(url_for('link_insert', id_=source_id, view='actor'))
        assert b'Gillian' in rv.data

        rv = c.post(
            url_for('link_insert', id_=source_id, view='actor'),
            data={'checkbox_values': [gillian.id]},
            follow_redirects=True)
        assert b'Gillian' in rv.data

        rv = c.get(url_for('update', id_=source_id))
        assert b'Necronomicon' in rv.data

        rv = c.post(
            url_for('update', id_=source_id),
            data={
                'name': 'Source updated',
                'description': (
                    'The <mark meta="{"annotationId":"c27",'
                    '"comment":"asdf"}">Necronomicon</mark>,'
                    ' also referred to as the Book of the Dead'),
                'artifact': [artifact.id]},
            follow_redirects=True)
        assert b'Source updated' in rv.data

        rv = c.get(url_for('entity_add_reference', id_=source_id))
        assert b'link reference' in rv.data

        rv = c.post(
            url_for('entity_add_reference', id_=source_id),
            data={'reference': reference.id, 'page': '777'},
            follow_redirects=True)
        assert b'777' in rv.data

        rv = c.get(
            url_for(
                'insert',
                class_='source_translation',
                origin_id=source_id))
        assert b'+ Source translation' in rv.data

        rv = c.post(
            url_for(
                'insert',
                class_='source_translation',
                origin_id=source_id),
            data={'name': 'Translation continued', 'continue_': 'yes'},
            follow_redirects=True)
        assert b'+' in rv.data

        rv = c.post(
            url_for(
                'insert',
                class_='source_translation',
                origin_id=source_id),
            data={'name': 'Test translation'})
        translation_id = rv.location.split('/')[-1]

        rv = c.get(url_for('update', id_=translation_id))
        assert b'Test translation' in rv.data

        rv = c.post(
            url_for('update', id_=translation_id),
            data={'name': 'Translation updated', 'opened': '9999999999'},
            follow_redirects=True)
        assert b'Translation updated' in rv.data

        rv = c.post(
            url_for('update', id_=translation_id),
            data={'name': 'Translation updated', 'opened': '1000000000'},
            follow_redirects=True)
        assert b'because it has been modified' in rv.data

        rv = c.get(
            url_for('delete', id_=translation_id),
            follow_redirects=True)
        assert b'The entry has been deleted' in rv.data
