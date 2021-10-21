from __future__ import annotations  # Needed for Python 4.0 type annotations

from typing import Any, Dict, List, Optional

from flask import g, session
from flask_babel import lazy_gettext as _

from openatlas import app
from openatlas.database.model import Model as Db

view_class_mapping = {
    'actor': ['person', 'group'],
    'event': ['activity', 'acquisition', 'move'],
    'file': ['file'],
    'artifact': ['artifact', 'find'],
    'place': ['feature', 'human_remains', 'place', 'stratigraphic_unit'],
    'reference': ['bibliography', 'edition', 'external_reference'],
    'reference_system': ['reference_system'],
    'source': ['source'],
    'type': ['administrative_unit', 'type'],
    'source_translation': ['source_translation']}


def uc_first(string: str) -> str:
    return str(string)[0].upper() + str(string)[1:] if string else ''


class OpenatlasClass:

    # Needed for translations of class labels
    _('source_translation')
    _('actor_appellation')

    def __init__(
            self,
            name: str,
            cidoc_class: str,
            hierarchies: List[int],
            standard_type_id: Optional[int] = None,
            alias_possible: Optional[bool] = False,
            color: Optional[str] = None,
            write_access: Optional[str] = 'contributor') -> None:
        self.name = name
        self.label = uc_first(_(name.replace('_', ' ')))
        if cidoc_class:
            self.cidoc_class: CidocClass = g.cidoc_classes[cidoc_class]
        self.standard_type = standard_type_id
        self.color = color  # Specifies color of entity in network visualisation
        self.write_access = write_access
        self.view = None
        self.alias_possible = alias_possible
        for item, classes in view_class_mapping.items():
            if name in classes:
                self.view = item

    @staticmethod
    def get_openatlas_classes() -> Dict[str, OpenatlasClass]:
        classes = {}
        for row in Db.get_openatlas_classes():
            classes[row['name']] = OpenatlasClass(
                name=row['name'],
                cidoc_class=row['cidoc_class_code'],
                standard_type_id=row['standard_type_id'],
                alias_possible=row['alias_possible'],
                write_access=row['write_access_group_name'],
                color=row['layout_color'],
                hierarchies=row['hierarchies'])
        return classes

    @staticmethod
    def get_table_headers() -> Dict[str, List[str]]:
        headers = {
            'actor': ['name', 'class', 'begin', 'end', 'description'],
            'artifact': ['name', 'class', 'type', 'begin', 'end',
                         'description'],
            'entities': ['name', 'class', 'info'],
            'event': ['name', 'class', 'type', 'begin', 'end', 'description'],
            'file': ['name', 'license', 'size', 'extension', 'description'],
            'member': ['member', 'function', 'first', 'last', 'description'],
            'member_of': ['member of', 'function', 'first', 'last',
                          'description'],
            'note': ['date', 'visibility', 'user', 'note'],
            'type': ['name', 'description'],
            'place': ['name', 'type', 'begin', 'end', 'description'],
            'relation': ['relation', 'actor', 'first', 'last', 'description'],
            'reference': ['name', 'class', 'type', 'description'],
            'reference_system':
                ['name', 'count', 'website URL', 'resolver URL', 'example ID',
                 'default precision', 'description'],
            'source': ['name', 'type', 'description'],
            'subs': ['name', 'count', 'info'],
            'text': ['text', 'type', 'content']}
        for view in ['actor', 'artifact', 'event', 'place']:
            for class_ in view_class_mapping[view]:
                headers[class_] = headers[view]
        return headers

    @staticmethod
    def get_class_view_mapping() -> Dict['str', 'str']:
        mapping = {}
        for view, classes in view_class_mapping.items():
            for class_ in classes:
                mapping[class_] = view
        return mapping


class CidocClass:

    def __init__(self, data: Dict[str, Any]) -> None:
        self._name = data['name']
        self.code = data['code']
        self.id = data['id']
        self.comment = data['comment']
        self.count = data['count']
        self.i18n: Dict[str, str] = {}
        self.sub: List[CidocClass] = []
        self.super: List[CidocClass] = []

    @property
    def name(self) -> str:
        return self.get_i18n()

    def get_i18n(self) -> str:
        from openatlas import get_locale
        locale_session = get_locale()
        if locale_session in self.i18n:
            return self.i18n[locale_session]
        locale_default = session['settings']['default_language']
        if locale_default in self.i18n:
            return self.i18n[locale_default]
        return getattr(self, '_name')  # pragma: no cover

    @staticmethod
    def get_all() -> Dict[str, CidocClass]:
        classes = {row['code']: CidocClass(row) for row in Db.get_classes()}
        for row in Db.get_class_hierarchy():
            classes[row['super_code']].sub.append(row['sub_code'])
            classes[row['sub_code']].super.append(row['super_code'])
        for row in Db.get_class_translations(app.config['LANGUAGES'].keys()):
            classes[row['class_code']].i18n[row['language_code']] = row['text']
        return classes


class CidocProperty:

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data['id']
        self._name = data['name']
        self._name_inverse = data['name_inverse']
        self.code = data['code']
        self.comment = data['comment']
        self.domain_class_code = data['domain_class_code']
        self.range_class_code = data['range_class_code']
        self.count = data['count']
        self.sub: List[int] = []
        self.super: List[int] = []
        self.i18n: Dict[str, str] = {}
        self.i18n_inverse: Dict[str, str] = {}

    @property
    def name(self) -> str:
        from openatlas import get_locale
        locale_session = get_locale()
        if locale_session in self.i18n:
            return self.i18n[locale_session]
        locale_default = session['settings']['default_language']
        if locale_default in self.i18n:
            return self.i18n[locale_default]
        return getattr(self, '_name')  # pragma: no cover

    @property
    def name_inverse(self) -> str:
        from openatlas import get_locale
        locale_session = get_locale()
        if locale_session in self.i18n_inverse:
            return self.i18n_inverse[locale_session]
        locale_default = session['settings']['default_language']
        if locale_default in self.i18n_inverse:
            return self.i18n_inverse[locale_default]
        return getattr(self, '_name_inverse')  # pragma: no cover

    def find_object(self, attr: str, class_id: int) -> bool:
        valid_domain_id = getattr(self, attr)
        if valid_domain_id == class_id:  # Check if links are CIDOC CRM valid
            return True
        return self.find_subs(
            attr,
            class_id,
            g.cidoc_classes[valid_domain_id].sub)

    def find_subs(
            self, attr:
            str, class_id:
            int, valid_subs: List[int]) -> bool:
        for sub_id in valid_subs:
            if sub_id == class_id or self.find_subs(
                    attr,
                    class_id,
                    g.cidoc_classes[sub_id].sub):
                return True
        return False

    @staticmethod
    def get_all() -> Dict[str, CidocProperty]:
        properties = {
            row['code']: CidocProperty(row) for row in Db.get_properties()}
        for row in Db.get_property_hierarchy():
            properties[row['super_code']].sub.append(row['sub_code'])
            properties[row['sub_code']].super.append(row['super_code'])
        for row in Db.get_property_translations(app.config['LANGUAGES'].keys()):
            properties[row['property_code']].i18n[row['language_code']] = \
                row['text']
            properties[row['property_code']].i18n_inverse[
                row['language_code']] = row['text_inverse']
        return properties
