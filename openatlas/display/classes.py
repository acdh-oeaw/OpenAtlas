from __future__ import annotations

from flask import g, url_for
from flask_babel import lazy_gettext as _

from openatlas.display.classes_base import (
    ActorDisplay, BaseDisplay, EventsDisplay, PlaceBaseDisplay,
    ReferenceBaseDisplay, TypeBaseDisplay)
from openatlas.display.tab import Tab
from openatlas.display.table import Table
from openatlas.display.util import (
    button, description, display_annotation_text_links, edit_link,
    format_entity_date, get_base_table_data, get_file_path, link, remove_link)
from openatlas.display.util2 import is_authorized, uc_first
from openatlas.models.entity import Entity
from openatlas.models.reference_system import ReferenceSystem
from openatlas.views.tools import carbon_result, sex_result


class AcquisitionDisplay(EventsDisplay):

    def add_data(self) -> None:
        super().add_data()
        self.data[_('recipient')] = [
            link(actor) for actor in
            self.entity.get_linked_entities('P22', sort=True)]
        self.data[_('donor')] = [
            link(donor) for donor in
            self.entity.get_linked_entities('P23', sort=True)]
        self.data[_('given object')] = [
            link(item) for item in
            self.entity.get_linked_entities('P24', sort=True)]


class ActivityDisplay(EventsDisplay):
    pass


class AdministrativeUnitDisplay(TypeBaseDisplay):
    pass


class ArtifactDisplay(PlaceBaseDisplay):

    def add_data(self) -> None:
        self.data[_('source')] = [
            link(source) for source
            in self.entity.get_linked_entities('P128', sort=True)]
        self.data[_('owned by')] = link(self.entity.get_linked_entity('P52'))


class BibliographyDisplay(ReferenceBaseDisplay):
    pass


class CreationDisplay(EventsDisplay):

    def add_data(self) -> None:
        super().add_data()
        self.data[_('document')] = [
            link(file_) for file_
            in self.entity.get_linked_entities('P94', sort=True)]


class FileDisplay(BaseDisplay):

    def add_data(self) -> None:
        self.data[_('public sharing allowed')] = str(_('no'))
        if self.entity.public:
            self.data[_('public sharing allowed')] = str(_('yes'))
            if not self.entity.standard_type:
                self.data[_('public sharing allowed')] = str(_('yes')) + (
                    ' <span class="error">' + _('but license is missing ') +
                    '</span>')
        self.data[_('creator')] = self.entity.creator
        self.data[_('license holder')] = self.entity.license_holder
        self.data[_('size')] = self.entity.get_file_size()
        self.data[_('extension')] = self.entity.get_file_ext()

    def add_button_others(self) -> None:
        if path := get_file_path(self.entity.id):
            self.buttons.append(
                button(_('download'), url_for('download', filename=path.name)))
            return
        self.buttons.append(
            '<span class="error">' + uc_first(_("missing file")) + '</span>')

    def add_button_copy(self) -> None:
        pass

    def add_tabs(self) -> None:
        entity = self.entity
        for name in [
                'source', 'event', 'actor', 'place', 'artifact', 'reference',
                'type']:
            self.tabs[name] = Tab(name, entity=entity)
        entity.image_id = entity.id if get_file_path(entity.id) else None
        for link_ in entity.get_links('P67'):
            range_ = link_.range
            data = get_base_table_data(range_)
            data.append(
                remove_link(range_.name, link_, entity, range_.class_.view))
            self.tabs[range_.class_.view].table.rows.append(data)
        for link_ in entity.get_links(['P67', 'P94'], inverse=True):
            data = get_base_table_data(link_.domain)
            data.append(link_.description)
            data.append(edit_link(
                url_for('link_update', id_=link_.id, origin_id=entity.id)))
            data.append(remove_link(
                link_.domain.name,
                link_,
                entity,
                link_.domain.class_.view))
            self.tabs[link_.domain.class_.view].table.rows.append(data)


class EditionDisplay(ReferenceBaseDisplay):
    pass


class EventDisplay(EventsDisplay):
    pass


class ExternalReferenceDisplay(ReferenceBaseDisplay):
    pass


class FeatureDisplay(PlaceBaseDisplay):
    pass


class GroupDisplay(ActorDisplay):

    def add_tabs(self) -> None:
        super().add_tabs()
        for link_ in self.entity.get_links('P107'):
            self.tabs['member'].table.rows.append([
                link(link_.range),
                link(link_.type),
                link_.first,
                link_.last,
                link_.description,
                edit_link(url_for(
                    'link_update',
                    id_=link_.id,
                    origin_id=self.entity.id)),
                remove_link(link_.range.name, link_, self.entity, 'member')])


class HumanRemainsDisplay(ArtifactDisplay):
    pass


class ModificationDisplay(EventsDisplay):

    def add_data(self) -> None:
        super().add_data()
        self.data[_('object')] = [
            link(entity) for entity
            in self.entity.get_linked_entities('P31', sort=True)]


class MoveDisplay(EventsDisplay):

    def add_data(self) -> None:
        super().add_data()
        if from_ := self.entity.get_linked_entity('P27'):
            self.data[_('begin')] = format_entity_date(
                self.entity,
                'begin',
                from_.get_linked_entity_safe('P53', True))
        if to := self.entity.get_linked_entity('P26'):
            self.data[_('end')] = format_entity_date(
                self.entity,
                'end',
                to.get_linked_entity_safe('P53', True))
        moved: dict[str, list[str]] = {'actor': [], 'artifact': []}
        for entity in self.entity.get_linked_entities('P25', sort=True):
            moved[entity.class_.view].append(link(entity))
        self.data[_('person')] = moved['actor']
        self.data[_('artifact')] = moved['artifact']


class PersonDisplay(ActorDisplay):
    pass


class PlaceDisplay(PlaceBaseDisplay):

    def add_tabs(self) -> None:
        super().add_tabs()
        if self.entity.location:
            for link_ in self.entity.location.get_links(
                    ['P74', 'OA8', 'OA9'],
                    inverse=True):
                actor = Entity.get_by_id(link_.domain.id)
                self.tabs['actor'].table.rows.append([
                    link(actor),
                    g.properties[link_.property.code].name,
                    actor.class_.name,
                    actor.first,
                    actor.last,
                    actor.description])
        actor_ids = []
        for event in self.events:
            for actor in \
                    event.get_linked_entities(
                        ['P11', 'P14', 'P22', 'P23'],
                        sort=True):
                if actor.id not in actor_ids:
                    actor_ids.append(actor.id)
                    self.tabs['actor'].table.rows.append([
                        link(actor),
                        f"{_('participated at an event')}",
                        event.class_.name, '', '', ''])


class ProductionDisplay(EventsDisplay):

    def add_data(self) -> None:
        super().add_data()
        self.data[_('produced')] = [
            link(item) for item
            in self.entity.get_linked_entities('P108', sort=True)]


class ReferenceSystemDisplay(BaseDisplay):
    entity: ReferenceSystem

    def add_button_copy(self) -> None:
        pass

    # def add_button_delete(self) -> None:
    #    if not self.entity.classes and not self.entity.system:
    #        super().add_button_delete()

    def add_data(self) -> None:
        self.data[_('website URL')] = link(
            self.entity.website_url,
            self.entity.website_url,
            external=True)
        self.data[_('resolver URL')] = link(
            self.entity.resolver_url,
            self.entity.resolver_url,
            external=True)
        self.data[_('example ID')] = self.entity.placeholder

    def add_tabs(self) -> None:
        for name in self.entity.classes:
            self.tabs[name] = Tab(
                name,
                entity=self.entity,
                table=Table([_('entity'), 'id', _('precision')]))
        for link_ in self.entity.get_links('P67'):
            self.tabs[link_.range.class_.name].table.rows.append([
                link(link_.range),
                link(
                    link_.description,
                    f'{self.entity.resolver_url}{link_.description}',
                    external=True)
                if self.entity.resolver_url else link_.description,
                link_.type.name])
        for name in self.entity.classes:
            self.tabs[name].buttons = []
            if not self.tabs[name].table.rows and is_authorized('manager'):
                self.tabs[name].buttons = [button(
                    _('remove'),
                    url_for(
                        'reference_system_remove_class',
                        system_id=self.entity.id,
                        class_name=name))]


class SourceDisplay(BaseDisplay):

    def add_data(self) -> None:
        self.data[_('artifact')] = [
            link(artifact) for artifact in
            self.entity.get_linked_entities('P128', inverse=True)]

    def add_tabs(self) -> None:
        entity = self.entity
        for name, tooltip in {
                'reference': '',
                'file': ''}.items():
            self.tabs[name] = Tab(name, entity=entity, tooltip=tooltip)


class SourceTranslationDisplay(BaseDisplay):

    def add_button_copy(self) -> None:
        pass

    def add_crumbs(self) -> None:
        self.crumbs = [
            [_('source'), url_for('index', view='source')],
            self.entity.get_linked_entity_safe('P73', True),
            self.entity.name]

    def description_html(self) -> str:
        return description(
            display_annotation_text_links(self.entity),
            _('content'))


class StratigraphicUnitDisplay(PlaceBaseDisplay):

    def add_button_others(self) -> None:
        self.buttons.append(
            button(_('tools'), url_for('tools_index', id_=self.entity.id)))

    def description_html(self) -> str:
        html = ''
        if self.entity.class_.name == 'stratigraphic_unit':
            if radiocarbon := carbon_result(self.entity):
                html += f"<p>{radiocarbon}</p>"
            if sex_estimation := sex_result(self.entity):
                html += f"<p>{sex_estimation}</p>"
        return html + description(self.entity.description)


class TypeDisplay(TypeBaseDisplay):
    pass
