from flask import g, url_for

from tests.base import TestBaseCase, get_hierarchy


class HierarchyTest(TestBaseCase):

    def test_hierarchy(self) -> None:
        c = self.client
        data = {
            'name': 'Geronimo',
            'classes': ['file', 'group', 'move', 'person', 'place', 'source'],
            'multiple': True,
            'description': 'Very important!'}
        rv = c.post(
            url_for('hierarchy_insert', category='custom'),
            data=data,
            follow_redirects=True)
        assert b'An entry has been created' in rv.data

        rv = c.post(
            url_for('hierarchy_insert', category='custom'),
            data=data,
            follow_redirects=True)
        assert b'The name is already in use' in rv.data

        hierarchy = get_hierarchy('Geronimo')
        data[f'reference_system_id_{g.wikidata.id}'] \
            = ['Q123', self.precision_type.subs[0]]
        data['classes'] = ['acquisition']
        data['entity_id'] = hierarchy.id
        rv = c.post(
            url_for('hierarchy_update', id_=hierarchy.id),
            data=data,
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(url_for('hierarchy_update', id_=hierarchy.id))
        assert b'checked class="" id="multiple"' in rv.data

        rv = c.get(url_for('hierarchy_insert', category='custom'))
        assert b'+ Custom' in rv.data

        sex = get_hierarchy('Sex')
        rv = c.get(url_for('required_risk', id_=sex.id))
        assert b'Be careful with making types required' in rv.data

        rv = c.get(url_for('required_add', id_=sex.id), follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(url_for('insert', class_='person'))
        assert b'Sex *' in rv.data

        rv = c.get(
            url_for('required_remove', id_=sex.id),
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.post(
            url_for('insert', class_='type', origin_id=hierarchy.id),
            data={'name': 'Secret type', 'description': 'Very important!'})
        type_id = rv.location.split('/')[-1]

        rv = c.get(
            url_for('remove_class', id_=hierarchy.id, name='person'),
            follow_redirects=True)
        assert b'Changes have been saved' in rv.data

        rv = c.get(url_for('type_delete', id_=type_id), follow_redirects=True)
        assert b'deleted' in rv.data

        rv = c.post(
            url_for('hierarchy_update', id_=hierarchy.id),
            data={'name': 'Actor relation', 'entity_id': hierarchy.id},
            follow_redirects=True)
        assert b'The name is already in use' in rv.data

        rv = c.post(
            url_for('hierarchy_delete', id_=hierarchy.id),
            follow_redirects=True)
        assert b'deleted' in rv.data

        rv = c.get(url_for('hierarchy_insert', category='value'))
        assert b'+ Value' in rv.data

        rv = c.post(
            url_for('hierarchy_insert', category='value'),
            data={'name': 'Valued', 'classes': ['file']},
            follow_redirects=True,)
        assert b'An entry has been created' in rv.data

        rv = c.get(url_for('hierarchy_update', id_=get_hierarchy('Valued').id))
        assert b'Valued' in rv.data

        type_ = get_hierarchy('Actor relation')
        rv = c.get(url_for('hierarchy_update', id_=type_.id))
        assert b'Forbidden' in rv.data

        rv = c.get(url_for('hierarchy_delete', id_=type_.id))
        assert b'Forbidden' in rv.data
