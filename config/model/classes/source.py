from flask_babel import lazy_gettext as _

from config.model.class_groups import class_groups, standard_relations

source = {
    'attributes': {
        'name': {
            'required': True},
        'description': {
            'label': _('content'),
            'annotated': True}},
    'relations': {
        'text': {
            'label': _('text'),
            'classes': 'source_translation',
            'properties': 'P73',
            'multiple': True,
            'tab':{
                'buttons': ['insert']}},
        'actor': {
            'classes': class_groups['actor']['classes'],
            'properties': 'P67',
            'multiple': True,
            'tab': {
                'buttons': ['link', 'insert'],
                'tooltip': _('mentioned in the source')}},
        'artifact': {
            'classes': class_groups['artifact']['classes'],
            'properties': 'P67',
            'multiple': True,
            'tab': {
                'buttons': ['link', 'insert'],
                'tooltip': _('mentioned in the source')}},
        'information_carrier': {
            'label': _('information carrier'),
            'classes': 'artifact',
            'properties': 'P128',
            'inverse': True,
            'multiple': True,
            'mode': 'direct',
            'tooltip': _(
                'Link artifacts as the information carrier of the source')},
        'event': {
            'classes': class_groups['event']['classes'],
            'properties': 'P67',
            'multiple': True,
            'tab': {
                'buttons': ['link', 'insert'],
                'tooltip': _('mentioned in the source')}},
        'place': {
            'classes': class_groups['place']['classes'],
            'properties': 'P67',
            'multiple': True,
            'tab': {
                'buttons': ['link', 'insert'],
                'tooltip': _('mentioned in the source')}},
        'file': standard_relations['file'],
        'reference': standard_relations['reference']},
    'display': {
        'buttons': ['copy'],
        'form': {
            'insert_and_continue': True},
        'additional_tabs': {
            'note': {}}}}

source_translation = {
    'attributes': {
        'name': {
            'required': True},
        'description': {
            'label': _('content'),
            'annotated': True}},
    'relations': {
        'source': {
            'classes': 'source',
            'properties': 'P73',
            'inverse': True,
            'required': True,
            'mode': 'direct'}},
    'display': {
        'form': {
            'insert_and_continue': True},
        'additional_tabs': {
            'note': {}}}}
