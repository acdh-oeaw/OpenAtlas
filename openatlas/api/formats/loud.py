import ast
import hashlib
import mimetypes
from collections import defaultdict
from typing import Any

import validators
from flask import g, url_for

from openatlas import app
from openatlas.api.resources.util import (
    date_to_utc_iso_str,
    get_iiif_manifest_and_path,
    get_license_type, is_float, remove_spaces_dashes)
from openatlas.database.gis import get_wkt_by_id
from openatlas.display.util2 import get_file_path
from openatlas.models.annotation import AnnotationText
from openatlas.models.entity import Entity, Link

LANGUAGES: dict[str, dict[str, Any]] = {
    'en': {
        'id': 'https://vocab.getty.edu/aat/300388277',
        'type': 'Language',
        '_label': 'English'},
    'de': {
        'id': 'https://vocab.getty.edu/aat/300388344',
        'type': 'Language',
        '_label': 'German'},
    'fr': {
        'id': 'https://vocab.getty.edu/aat/300388306',
        'type': 'Language',
        '_label': 'French'},
    'it': {
        'id': 'https://vocab.getty.edu/aat/300388474',
        'type': 'Language',
        '_label': 'Italian'},
    'es': {
        'id': 'https://vocab.getty.edu/aat/300389311',
        'type': 'Language',
        '_label': 'Spanish'},
    'sr': {
        'id': 'https://vocab.getty.edu/aat/300389248',
        'type': 'Language',
        '_label': 'Serbian'},
    'sl': {
        'id': 'https://vocab.getty.edu/aat/300389291',
        'type': 'Language',
        '_label': 'Slovenian'},
    'cs': {
        'id': 'https://vocab.getty.edu/aat/300388191',
        'type': 'Language',
        '_label': 'Czech'},
    'sk': {
        'id': 'https://vocab.getty.edu/aat/300389290',
        'type': 'Language',
        '_label': 'Slovak'}}

UNIT_MAP = {
    'B': 'bytes',
    'KB': 'kilobytes',
    'MB': 'megabytes',
    'GB': 'gigabytes',
    'TB': 'terabytes'}

TYPE_OVERWRITES = {
    'file': 'DigitalObject',
    'human_remains': 'BiologicalObject',
    'place': 'Site',
    'feature': 'HumanMadeFeature',
    'stratigraphic_unit':
        'http://www.cidoc-crm.org/extensions/crmarchaeo/'
        'A8_Stratigraphic_Unit'}


def aat_type(id_: str, label: str) -> dict[str, str]:
    """Build a LOUD ``Type`` stub pointing at a Getty AAT concept.

    Linked Art uses Getty's Art & Architecture Thesaurus (AAT) as its
    canonical controlled vocabulary for classifications. Whenever we want
    to attach a ``classified_as`` to a resource, we emit a minimal stub
    with the AAT URI as ``id`` plus a human-readable ``_label``. The
    label is informational only — consumers should dereference the URI.
    """
    return {
        'id': f'https://vocab.getty.edu/aat/{id_}',
        'type': 'Type',
        '_label': label}


ARCHAEOLOGY_AAT: dict[str, dict[str, str]] = {
    'artifact': aat_type('300117127', 'artifacts'),
    'human_remains': aat_type('300379896', 'human remains')}

MIME_CLASSIFICATIONS: dict[str, list[dict[str, str]]] = {
    'image/': [aat_type('300215302', 'Digital image')],
    'application/pdf': [aat_type('300424602', 'Digital documents')],
    'model/': [
        aat_type('300266011', 'Digital File Format'), {
            'id': 'https://www.wikidata.org/wiki/Q3859833',
            'type': 'Type',
            '_label': '3D Model'}]}

BIBLIOGRAPHY_AAT: dict[str, dict[str, str]] = {
    'bibliography': aat_type('300026497', 'bibliography'),
    'edition': aat_type('300121294', 'edition')}

SKOS_CLOSE_MATCH: dict[str, Any] = {
    'id': 'http://www.w3.org/2004/02/skos/core#closeMatch',
    'type': 'Type',
    '_label': 'Close Match'}


def get_language() -> dict[str, Any]:
    """Return the LOUD ``Language`` stub configured for this instance.

    LinguisticObjects in LOUD must declare their language with an AAT
    Getty URI. The active language is taken from ``ARCHE_METADATA`` in
    the app config, defaulting to English when unset or unknown.
    """
    code = app.config.get('ARCHE_METADATA', {}).get('language', 'en')
    return LANGUAGES.get(code, LANGUAGES['en'])


def category_aat(id_: str, label: str) -> dict[str, Any]:
    """Like :func:`aat_type` but flagged as a category of *documents*.

    Some Linked Art shapes (e.g. on LinguisticObject.classified_as)
    expect the classifier itself to be classified as a 'documents (by
    form)' (AAT 300137954). This helper just bundles that extra layer so
    we don't repeat it at every call site.
    """
    return aat_type(id_, label) \
        | {'classified_as': [aat_type('300137954', 'documents (by form)')]}


def primary_name(
        content: str,
        label: str | None = None,
        id_: str | None = None) -> dict[str, Any]:
    """Build a LOUD ``Name`` stub flagged as a primary appellation.

    Linked Art models human-readable names as nested ``Name`` resources
    under ``identified_by``, classified with AAT 300404670 ('primary
    name'). This helper produces such a stub with the configured
    language attached so the surrounding code only has to pass the text.
    """
    name: dict[str, Any] = {
        'type': 'Name',
        '_label': label or content,
        'content': content,
        'classified_as': [aat_type('300404670', 'primary name')],
        'language': [get_language()]}
    if id_:
        name = {'id': id_} | name
    return name


def entity_uri(entity: Entity) -> str:
    """Return the stable, externally resolvable URI for ``entity``.

    All OpenAtlas entities are addressed by their UUID through the
    ``api.entity_uuid`` endpoint. We use the UUID-based route (not the
    integer id) on purpose: integer ids are local to a database
    instance, UUIDs are globally stable identifiers and therefore the
    only ones safe to publish as Linked Open Data.
    """
    return url_for('api.entity_uuid', uuid=entity.uuid, _external=True)


def reference_url(type_link: Link) -> str:
    """Compute the external URL described by a reference-system Link.

    A 'reference_system' entity (Wikidata, GeoNames, ...) stores a base
    URL on the system itself; the Link's ``description`` carries the
    record id within that system. We concatenate them to obtain the full
    external URI. For non reference-system links we fall back to the
    domain's display name, matching the legacy LOUD contract.
    """
    if type_link.domain.class_.name == 'reference_system':
        system = g.reference_systems[type_link.domain.id]
        return f'{system.resolver_url or ''}{type_link.description}'
    return type_link.domain.name


def is_close_match(link_: Link) -> bool:
    """True if a reference link expresses a skos:closeMatch.

    OpenAtlas users can flag external references as 'close' matches
    instead of strict equivalents. In LOUD this distinction is preserved
    by wrapping the reference in an ``AttributeAssignment`` classified as
    ``skos:closeMatch`` (see :func:`close_match_attribution`) rather than
    listing it under ``equivalent``.
    """
    return bool(
        link_.type
        and g.types.get(link_.type.id)
        and 'close' in g.types[link_.type.id].name)


def close_match_attribution(
        skolem_id: str,
        assigned: dict[str, Any]) -> dict[str, Any]:
    """Wrap an external reference into a skos:closeMatch attribution.

    LOUD doesn't allow ``skos:closeMatch`` to be used as a direct
    predicate; instead the convention is to attach an
    ``AttributeAssignment`` whose ``classified_as`` is the closeMatch
    AAT, and whose ``assigned`` slot carries the reference itself. This
    keeps the graph SHACL-valid while preserving the user's intent.
    """
    return {
        'id': skolem_id,
        'type': 'AttributeAssignment',
        '_label': 'Close Match assignment',
        'classified_as': [SKOS_CLOSE_MATCH],
        'assigned': assigned}


class LoudFormatter:
    """Builds a LOUD/Linked-Art JSON-LD document for a single entity.

    The formatter is instantiated once per top-level entity (see
    :func:`get_loud_entities`) and accumulates output into a
    ``properties_set`` ``defaultdict(list)`` that the caller passes in.

    Why a class instead of a flat module of functions?

    - The CIDOC-CRM property to LOUD key mapping is *not* a simple table:
      several codes (P1, P2, P67, P73, OA7) need bespoke shaping. We use
      a per-instance ``handlers`` dict so ``format_link`` stays a small
      dispatcher.
    - The JSON-LD ``@context`` and the entity-wide ``type_references``
      cache are read in dozens of places. Storing them on ``self`` is
      cheaper and clearer than threading them through every call.
    """

    def __init__(
            self,
            loud_context: dict[str, str],
            type_references: dict[int, list[Link]]) -> None:
        self.loud = loud_context
        self.type_refs = type_references
        self.handlers: dict[str, Any] = {
            'P1': self._handle_p1,
            'P2': self._handle_p2,
            'P67': self._handle_p67,
            'P73': self._handle_p73,
            'OA7': self._handle_oa7}

    def _loud_relation(self, link_: Link, is_inverse: bool) -> str:
        """Map a CRM property code to its canonical LOUD property name.

        The LOUD ``@context`` is keyed by the human-readable, snake-cased
        version of CIDOC-CRM property labels (e.g. ``part_of`` for
        ``crm:P46``). :func:`get_loud_crm_relation` reconstructs that
        label from the link; we just normalize the spaces and look the
        key up. Used as the fallback when no special-case rule applies
        in :meth:`get_property_key`.
        """
        return self.loud[
            get_loud_crm_relation(link_, is_inverse).replace(' ', '_')]

    def get_property_key(self, link_: Link, is_inverse: bool) -> str:
        """Decide under which LOUD key a Link is rendered.

        Most CRM properties map 1:1 to a LOUD predicate via the
        ``@context`` (handled by :meth:`_loud_relation`). A handful of
        them, however, are remodelled by Linked Art:

        - ``OA7`` (relationship) always becomes ``participated_in``
          because the relationship is reified as an Event;
        - inverse ``P67`` on an external_reference flips to ``subject_of``
          (the external page is *about* this entity);
        - ``P67`` on a file flips to ``digitally_carries`` so the file is
          modelled as a DigitalObject;
        - ``P53`` on an artifact narrows to ``current_location``;
        - ``P2`` with a numeric description becomes a ``Dimension``;
        - ``P127`` swaps direction (``part``/``part_of``);
        - ``P46`` on artifact/human_remains uses ``occupies`` to express
          the spatial container relation Linked Art prefers.

        Anything else falls through to the context lookup.
        """
        code = link_.property.code
        if code == 'OA7':
            return 'participated_in'
        if is_inverse and link_.domain.class_.name == 'external_reference':
            return 'subject_of'
        if not is_inverse and code == 'P67':
            if link_.domain.class_.name == 'file':
                return 'digitally_carries'
            return 'refers_to'
        if not is_inverse and code == 'P73':
            return 'referred_to_by'
        if code == 'P53' and link_.domain.class_.name == 'artifact':
            return 'current_location'
        if code == 'P2' and link_.description:
            return 'dimension'
        if code == 'P127':
            return 'part' if is_inverse else 'part_of'
        if code == 'P46':
            classes = {
                link_.domain.class_.name,
                link_.range.class_.name}
            if classes & {'artifact', 'human_remains'}:
                return 'occupies' if is_inverse else 'occupied_by'
        return self._loud_relation(link_, is_inverse)

    def format_link(self, link_: Link, is_domain: bool) -> dict[str, Any]:
        """Render the *target* side of a Link as a LOUD resource stub.

        Produces the minimum stub Linked Art consumers expect: an ``id``,
        a ``type``, a ``_label`` and an ``identified_by`` block carrying
        the inline appellations / system identifiers. On top of that:

        - If the link has dates, attach a ``timespan``.
        - For most properties, attach the link's own type as
          ``classified_as`` (P2 is excluded because there the type is
          used differently, see :meth:`_handle_p2`).
        - If the target is a file linked through ``P67``, wrap the stub
          inside a ``VisualItem`` (``represents`` chain) so the bitstream
          is properly distinguished from the conceptual content.
        - Prepend archaeology-specific AAT classifications when the
          target class is artifact / human_remains.
        - Finally dispatch to a per-code handler (``self.handlers``) for
          the codes that need bespoke shaping (P1, P2, P67, P73, OA7).
        """
        target = link_.domain if is_domain else link_.range
        property_: dict[str, Any] = {
            'id': entity_uri(target),
            'type': self._resolve_type(target),
            '_label': target.name,
            'identified_by': self._inline_identifiers(target)}
        if link_.dates.begin_from or link_.dates.end_from:
            property_ = property_ | self.get_loud_timespan(link_)
        code_ = link_.property.code
        if code_ != 'P2' and link_.type:
            property_['classified_as'] = [
                self._format_type_property(g.types[link_.type.id])]
        if code_ == 'P67' and link_.domain.class_.name == 'file':
            property_ = {
                'id': self.generate_skolem_id(link_.domain.id, 'visual_item'),
                "type": "VisualItem",
                "_label": f"Visual content of {link_.domain.name}",
                "represents": [property_]}
        self._prepend_archaeology_classification(target, property_)
        if handler := self.handlers.get(code_):
            return handler(property_, link_, is_domain)
        return property_

    @staticmethod
    def _prepend_archaeology_classification(
            entity: Entity,
            property_: dict[str, Any]) -> None:
        """Prepend an archaeology AAT type onto an existing stub.

        Artefacts and human remains need an extra ``classified_as`` entry
        pointing at the matching AAT concept (see ``ARCHAEOLOGY_AAT``).
        We *prepend* it on purpose: the more specific archaeology
        classification should appear first so LOUD consumers that pick
        the head of the list still get the right semantics.
        """
        if aat := ARCHAEOLOGY_AAT.get(entity.class_.name):
            property_['classified_as'] = (
                    [aat] + property_.get('classified_as', []))

    @staticmethod
    def base_entity_dict(entity: Entity) -> dict[str, Any]:
        """Return the root LOUD dict (id/type/_label) for a top-level entity.

        Called once per export to seed the output document with the
        canonical identity triple of the entity being serialised. The
        archaeology classification is prepended here too so it always
        ends up at the top of the output, not buried inside a nested
        property.
        """
        result: dict[str, Any] = {
            'id': entity_uri(entity),
            'type': LoudFormatter._resolve_type(entity),
            '_label': entity.name}
        LoudFormatter._prepend_archaeology_classification(entity, result)
        return result

    @staticmethod
    def _resolve_type(entity: Entity) -> str:
        """Pick the LOUD ``type`` string for an entity.

        Linked Art uses its own class vocabulary that does not match
        CIDOC-CRM 1:1 (e.g. CRM's E18 Physical Thing becomes ``Site``
        for places, ``HumanMadeFeature`` for features, ...). The
        ``TYPE_OVERWRITES`` table encodes those substitutions; everything
        else falls back to the CIDOC class label with whitespace removed
        so it becomes a valid JSON-LD term.
        """
        return TYPE_OVERWRITES.get(
            entity.class_.name,
            remove_spaces_dashes(entity.cidoc_class.i18n['en']))

    @staticmethod
    def get_file_dimensions(entity: Entity) -> dict[str, Any]:
        """Build a LOUD ``Dimension`` describing a file's size in bytes/KB/...

        DigitalObjects in Linked Art carry their size as a nested
        ``Dimension`` with the value and an AAT MeasurementUnit. We use
        a skolemised id (deterministic blank-node URI) so the same file
        always produces the same dimension URI across exports.
        """
        file_size = entity.get_file_size()
        value, unit = file_size.split()
        return {'dimension': [{
            'id': LoudFormatter.generate_skolem_id(entity.id, 'file_size'),
            "type": "Dimension",
            "_label": file_size,
            "classified_as": [aat_type('300265863', 'File Size')],
            "value": int(value),
            "unit": {
                "id": "https://vocab.getty.edu/aat/300265870",
                "type": "MeasurementUnit",
                "_label": UNIT_MAP[unit]}}]}

    def get_digital_object_details(
            self,
            entity: Entity,
            mime_type: str | None = None) -> dict[str, Any]:
        """Collect the DigitalObject-level metadata for a file entity.

        Returns a dict combining

        - ``format`` (MIME type),
        - ``classified_as`` driven by ``MIME_CLASSIFICATIONS`` (so a PDF
          gets the 'Digital documents' AAT, an image the 'Digital image'
          AAT, etc.),
        - ``access_point`` (the API URL that resolves to the bitstream),
        - ``right_held_by`` / ``created_by`` from the file's metadata,
        - ``referred_to_by`` carrying the license LinguisticObject when
          a license is attached.

        Used both for files that are themselves the root entity and for
        files linked as media to another entity.
        """
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(g.files[entity.id])
        digital_object: dict[str, Any] = {'format': mime_type}
        for prefix, classification in MIME_CLASSIFICATIONS.items():
            if mime_type and prefix in mime_type:
                digital_object['classified_as'] = classification
        file_ = get_file_path(entity.id)
        if file_ and file_.stem:
            digital_object['access_point'] = [{
                "id": url_for(
                    'api.display', filename=file_.stem, _external=True),
                "type": "DigitalObject",
                "_label": file_.stem}]
        for license_holder in entity.license_holder or []:
            digital_object['right_held_by'] = [{
                'id': self.generate_skolem_id(
                    license_holder.id, 'rights_holder'),
                '_label': license_holder.name,
                'type': (license_holder.class_ or 'Actor').capitalize()}]
        for creator in entity.creator or []:
            digital_object['created_by'] = {
                'id': self.generate_skolem_id(
                    creator.id, f'{entity.id}_creation_{creator.id}'),
                '_label': f'Creation of {entity.name}',
                'type': 'Creation',
                'carried_out_by': [{
                    'id': self.generate_skolem_id(
                        creator.id, 'rights_holder'),
                    '_label': creator.name,
                    'type': (creator.class_ or 'Actor').capitalize()}]}
        if license_ := get_license_type(entity):
            digital_object['referred_to_by'] = [
                self._build_license(license_, entity.name)]
        return digital_object

    def _build_license(
            self, license_: Entity, entity_name: str) -> dict[str, Any]:
        """Render a license entity as a LOUD LinguisticObject stub.

        Licenses in OpenAtlas are themselves Entities (so they can carry
        translations, references, ...) but in LOUD they are exposed as a
        nested LinguisticObject classified as 'copyright/licensing
        statement', with any external reference (e.g. a CC URL) added as
        extra ``classified_as`` entries.
        """
        classified_as: list[dict[str, Any]] = [
            aat_type('300435434', 'copyright/licensing statement')]
        classified_as.extend(
            {
                "id": reference_url(type_link),
                "type": "Type",
                "_label": license_.name}
            for type_link in self.type_refs.get(license_.id, []))
        return {
            'id': self.generate_skolem_id(license_.id, 'license'),
            'type': 'LinguisticObject',
            '_label': f'License of {entity_name}',
            'classified_as': classified_as,
            'language': [get_language()],
            'identified_by': [
                primary_name(license_.name, id_=entity_uri(license_))]}

    @staticmethod
    def handle_radiocarbon(
            link_: Link, properties_set: dict[str, Any]) -> None:
        """Emit a LOUD ``AttributeAssignment`` for a radiocarbon date.

        Radiocarbon datings live on a ``P2`` link whose ``description``
        is a Python-literal dict (year / range / scale / lab id / spec
        id). They are *not* a normal P2 classification, so we model them
        explicitly as an AttributeAssignment carrying a Dimension with
        upper/lower limits, plus Identifier nodes for the lab and the
        specimen, plus a Group for the lab itself. This shape matches
        the Linked Art recipe for scientific datings.
        """
        data = ast.literal_eval(link_.description)
        year = int(data['radiocarbonYear'])
        rng = int(data['range'])
        scale = data['timeScale']
        lab_id = data['labId']
        spec_id = data['specId']
        skolem = LoudFormatter.generate_skolem_id
        dating = aat_type('300054717', 'Radiocarbon Dating')
        properties_set['attributed_by'].append({
            'id': skolem(link_.id, 'radiocarbon'),
            "type": "AttributeAssignment",
            "_label": "Radiocarbon Dating",
            "classified_as": [dating],
            "assigned": [{
                'id': skolem(link_.id, 'radiocarbon_dimension'),
                "type": "Dimension",
                "_label": f'{year} +/- {rng} {scale}',
                "classified_as": [dating],
                "value": year,
                "lower_value_limit": year - rng,
                "upper_value_limit": year + rng,
                "unit": {
                    "id": "https://vocab.getty.edu/aat/300379244",
                    "type": "MeasurementUnit",
                    "_label": f"years {scale}"},
                "referred_to_by": [{
                    'id': skolem(link_.id, 'radiocarbon_error'),
                    "type": "LinguisticObject",
                    "content": str(rng),
                    "_label": "Laboratory Error Range",
                    "language": [get_language()],
                    "classified_as": [category_aat(
                        '300417273',
                        'error (measure of uncertainty)')]}]}],
            "identified_by": [{
                'id': skolem(link_.id, 'laboratory'),
                "type": "Identifier",
                "content": f"{lab_id}-{spec_id}",
                "_label": "Laboratory ID",
                "classified_as": [aat_type(
                    '300460217', 'Laboratory Identifiers')]}, {
                'id': skolem(link_.id, 'specimen'),
                "type": "Identifier",
                "content": str(spec_id),
                "_label": "Specimen ID",
                "classified_as": [aat_type(
                    '300404626', 'Identification Numbers')]}],
            "carried_out_by": [{
                'id': skolem(link_.id, 'radio_group'),
                "type": "Group",
                "_label": lab_id,
                "identified_by": [primary_name(lab_id)]}]})

    @staticmethod
    def _handle_p1(
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        """Customise the stub for a ``P1 is identified by`` link.

        For P1 the *target* is conceptually a Name/Appellation, not a
        full resource, so we replace the auto-generated entity URI with
        a skolemised one specific to this appellation and copy the
        target's display name into ``content`` to match the LOUD Name
        shape.
        """
        target = link_.domain if is_domain else link_.range
        property_['id'] = LoudFormatter.generate_skolem_id(
            link_.id, 'appellation')
        property_['content'] = target.name
        return property_

    @staticmethod
    def _handle_p2(
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        """Customise the stub for a ``P2 has type`` link.

        A plain P2 is just a classification (handled by the default
        path). When the link carries a numeric ``description`` it is
        actually a measurement: the type entity then describes the unit
        and the description holds the value. We rewrite the stub into a
        Linked Art ``Dimension`` with value / unit / classified_as so
        the consumer can read it as a number, not a vocabulary term.
        """
        target = link_.domain if is_domain else link_.range
        if link_.description and is_float(link_.description):
            property_['id'] = LoudFormatter.generate_skolem_id(
                link_.id,
                'dimension')
            property_['type'] = 'Dimension'
            property_['value'] = float(link_.description)
            property_['unit'] = {
                "id": "https://vocab.getty.edu/aat/300226816",
                'type': "MeasurementUnit",
                '_label': target.description}
            property_['classified_as'] = [{
                "id": "https://vocab.getty.edu/aat/300379096",
                'type': "Type",
                '_label': target.description}]
        return property_

    def _handle_p73(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        """Customise the stub for a ``P73 has translation`` link.

        On the inverse side (this entity *is* the translation), we pull
        the translated content out of the range's description and attach
        its standard type as ``classified_as`` so the LinguisticObject
        carries the translated text directly. On the domain side the
        stub is fine as-is.
        """
        if is_domain:
            return property_
        property_['content'] = link_.range.description
        if link_.range.standard_type:
            property_['classified_as'] = [self._format_type_property(
                g.types[link_.range.standard_type.id])]
        return property_

    def _handle_p67(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> dict[str, Any]:
        """Customise the stub for a ``P67 refers to`` link.

        P67 is the most overloaded property in our model: depending on
        the domain class it represents a file (DigitalObject), a source
        (LinguisticObject with historical context), a bibliography
        entry, an external web reference, etc. This handler picks the
        right LOUD shape for each case and, where applicable, attaches
        pagination information from ``link_.description`` as an extra
        primary name.

        For external_reference domains we completely rebuild the stub
        into a LinguisticObject + DigitalObject pair: the entity itself
        is the *description* of the web page, while the actual URL
        lives on the carried DigitalObject.
        """
        if not is_domain:
            if link_.description:
                property_['content'] = link_.description
            return property_
        domain = link_.domain
        property_['classified_as'] = []
        property_['type'] = (
            'DigitalObject' if domain.class_.name == 'file'
            else 'LinguisticObject')
        if standard_type := domain.standard_type:
            property_['classified_as'].append(
                self._format_type_property(standard_type))
        if link_.description:
            pagination = primary_name(
                link_.description,
                id_=self.generate_skolem_id(link_.id, 'pagination'))
            pagination['classified_as'] = (
                    [aat_type('300200294', 'pagination')]
                    + pagination['classified_as'])
            property_['identified_by'] = [pagination]
        if aat := BIBLIOGRAPHY_AAT.get(domain.class_.name):
            property_['classified_as'].append(aat)
            property_['classified_as'].append(category_aat(
                '300311705',
                'citations (bibliographic references)'))
        if property_['type'] == 'LinguisticObject':
            property_['language'] = [get_language()]
        if domain.class_.name == 'source':
            property_['classified_as'].append(category_aat(
                '300435428',
                'historical/cultural context'))
        if domain.class_.name == 'external_reference':
            web_page = category_aat('300264578', 'web page')
            description = category_aat('300435416', 'description')
            property_ = {
                "id": entity_uri(domain),
                "_label": domain.name,
                "classified_as": [web_page, description],
                "type": "LinguisticObject",
                "language": [get_language()],
                "digitally_carried_by": [{
                    "id": self.generate_skolem_id(
                        domain.id, 'web_digital_object'),
                    "type": "DigitalObject",
                    "_label": domain.name,
                    "classified_as": [web_page],
                    "format": "text/html",
                    "access_point": [{
                        "id": domain.name,
                        "_label": domain.name,
                        "type": "DigitalObject"}]}]}
        if domain.description:  # pragma: no cover
            property_['content'] = domain.description
        return property_

    def _handle_oa7(
            self,
            property_: dict[str, Any],
            link_: Link,
            is_domain: bool) -> Any:
        """Reify an ``OA7 has relationship to`` link as a LOUD Event.

        OA7 is OpenAtlas' relationship property. Linked Art has no
        binary 'related to' predicate; it instead expects relationships
        to be reified as Events with both parties as ``had_participant``.
        We always emit such an Event with the link's own type attached
        as ``classified_as``. The domain side gets the event wrapped in
        a list so it can be consumed under ``participated_in``.
        """
        first, second = (link_.range, link_.domain) \
            if is_domain else (link_.domain, link_.range)
        relationship: dict[str, Any] = {
            'id': self.generate_skolem_id(link_.id, 'relationship'),
            'type': 'Event',
            '_label': f'Relationship between {first.name} and {second.name}',
            'had_participant': [property_]}
        if link_.type:
            relationship['classified_as'] = [
                self._format_type_property(g.types[link_.type.id])]
        return [relationship] if is_domain else relationship

    def _format_type_property(self, type_: Entity) -> dict[str, Any]:
        """Render an internal Type entity as a LOUD ``Type`` stub.

        OpenAtlas Types can carry references to external vocabularies
        (Wikidata, AAT, GeoNames, ...). For each such reference we emit
        either:

        - an ``equivalent`` link, when the reference is a strict match,
        - an ``attributed_by`` ``AttributeAssignment`` classified as
          ``skos:closeMatch`` (see :func:`close_match_attribution`),
          when the reference is flagged as a close match.

        This preserves the user's intent and stays SHACL-valid because
        ``skos:closeMatch`` is never used as a direct predicate.
        """
        property_: dict[str, Any] = {
            'id': entity_uri(type_),
            'type': self._resolve_type(type_),
            '_label': type_.name}
        if type_.dates.begin_from or type_.dates.end_from:
            property_ = property_ | self.get_loud_timespan(type_)
        equivalents: list[dict[str, Any]] = []
        attributed_by: list[dict[str, Any]] = []
        for type_link in self.type_refs.get(type_.id, []):
            url = reference_url(type_link)
            if not validators.url(url):  # pragma: no cover
                continue
            ref = {
                "id": url,
                "type": "Type",
                "_label": type_.name}
            if is_close_match(type_link):  # pragma: no cover
                attributed_by.append(close_match_attribution(
                    self.generate_skolem_id(type_link.id, 'close_match'),
                    ref))
            else:
                equivalents.append(ref)
        if equivalents:
            property_['equivalent'] = equivalents
        if attributed_by:  # pragma: no cover
            property_['attributed_by'] = attributed_by
        return property_

    @staticmethod
    def generate_skolem_id(id_: int, type_name: str) -> str:
        """Generate a deterministic skolem URI for a nested resource.

        A *skolem* URI is the standard RDF way to give a stable name to
        something that would otherwise be a blank node (see RDF 1.1
        §3.5). We need this for every nested object that does *not*
        correspond to a first-class OpenAtlas entity — timespans, name
        appellations, dimensions, identifiers, etc. — because Linked Art
        consumers and SHACL validators expect every resource to have an
        ``id``.

        The id is derived from the parent entity/link id plus a
        type-specific suffix, hashed to 16 hex chars and resolved
        through the ``api.skolem_proxy`` endpoint. The hash means the
        URIs are short and opaque; determinism means the same export
        always produces the same URIs, which is required for diffing
        and caching downstream.
        """
        seed = f"{id_}_{type_name}".encode('utf-8')
        identifier_hash = hashlib.sha256(seed).hexdigest()[:16]
        return url_for(
            "api.skolem_proxy",
            subpath=f'{type_name.lower()}/{identifier_hash}',
            _external=True)

    LIFE_EVENT_CONFIG: dict[str, dict[str, Any]] = {
        'person': {
            'begin_key': 'born',
            'begin_type': 'Birth',
            'end_key': 'died_in',
            'end_type': 'Death',
            'inner_ts_id': False},
        'group': {
            'begin_key': 'formed_by',
            'begin_type': 'Formation',
            'end_key': 'dissolved_by',
            'end_type': 'Dissolution',
            'inner_ts_id': True}}

    def get_loud_timespan(
            self,
            entity: Entity | Link,
            links_: list[Link] | None = None) -> dict[str, Any]:
        """Return the LOUD timespan block for an entity or link.

        Three shapes are produced depending on the input:

        - **Persons / groups** — expanded to a full birth/death (or
          formation/dissolution) Event pair via
          :meth:`_get_life_event_timespan` because Linked Art models the
          life span of an actor through such events rather than a flat
          TimeSpan.
        - **Any other entity or Link with dates** — a single ``timespan``
          key whose value is a skolemised ``TimeSpan`` carrying the
          begin/end dates (see :meth:`_get_loud_begin_dates` /
          :meth:`_get_loud_end_dates`).
        - **No dates** — an empty dict, so callers can safely splat it
          into the output without producing empty keys.
        """
        if not isinstance(entity, Link) \
                and entity.class_.name in self.LIFE_EVENT_CONFIG:
            return self._get_life_event_timespan(entity, links_)
        if not entity.dates.dates_available():
            return {}
        name = entity.name if isinstance(entity, Entity) \
            else entity.domain.name
        return {'timespan':
                    {'id': self.generate_skolem_id(entity.id, 'timespan'),
                     'type': 'TimeSpan',
                     '_label': f'Timespan of {name}'}
                    | self._get_loud_begin_dates(entity)
                    | self._get_loud_end_dates(entity)}

    def _make_life_event(
            self,
            entity: Entity,
            event_type: str,
            dates: dict[str, Any],
            has_dates: bool) -> dict[str, Any]:
        """Build a Birth/Death/Formation/Dissolution Event stub.

        Persons and groups don't carry their dates directly in LOUD;
        instead the dates live on a dedicated event resource. This
        helper produces that event stub, optionally embedding a
        TimeSpan when ``has_dates`` is true. The event is always emitted
        even without dates because it may still carry a place
        (``took_place_at``) added later in
        :meth:`_get_life_event_timespan`.
        """
        skolem_key = event_type.lower()
        event: dict[str, Any] = {
            'id': self.generate_skolem_id(entity.id, skolem_key),
            'type': event_type,
            '_label': f'{event_type} of {entity.name}'}
        if has_dates:
            ts_key = 'begin' if event_type in {'Birth', 'Formation'} \
                else 'end'
            timespan: dict[str, Any] = {
                'id': self.generate_skolem_id(entity.id, ts_key),
                'type': 'TimeSpan',
                '_label': f'Timespan of {event_type} of {entity.name}'}
            event['timespan'] = timespan | dates
        return event

    def _get_life_event_timespan(
            self,
            entity: Entity,
            links_: list[Link] | None) -> dict[str, Any]:
        """Build the begin/end life events for a Person or Group.

        Walks the entity's begin/end dates plus any place links
        (``OA8`` = took place at birth/formation, ``OA9`` = took place
        at death/dissolution) and packages them into the LOUD keys
        defined in ``LIFE_EVENT_CONFIG`` (e.g. ``born`` / ``died_in``
        for persons, ``formed_by`` / ``dissolved_by`` for groups). An
        event is included only if it has dates *or* a place — we don't
        emit empty Birth/Death stubs.
        """
        config = self.LIFE_EVENT_CONFIG[entity.class_.name]
        has_begin = bool(entity.dates.begin_from or entity.dates.begin_to)
        has_end = bool(entity.dates.end_from or entity.dates.end_to)
        begin_event = self._make_life_event(
            entity, config['begin_type'],
            self._get_loud_begin_dates(entity),
            has_begin)
        end_event = self._make_life_event(
            entity, config['end_type'],
            self._get_loud_end_dates(entity),
            has_end)
        for link_ in links_ or []:
            place = {
                'id': entity_uri(link_.range),
                'type': 'Place',
                '_label': link_.range.name,
                'identified_by': self._inline_identifiers(link_.range)}
            if link_.property.code == 'OA8':
                begin_event['took_place_at'] = [place]
                has_begin = True
            elif link_.property.code == 'OA9':
                end_event['took_place_at'] = [place]
                has_end = True
        result: dict[str, Any] = {}
        if has_begin:
            result[config['begin_key']] = begin_event
        if has_end:
            result[config['end_key']] = end_event
        return result

    @staticmethod
    def _get_loud_begin_dates(entity: Entity | Link) -> dict[str, Any]:
        """Translate OpenAtlas begin dates to LOUD TimeSpan keys.

        OpenAtlas stores an interval as four dates (begin_from /
        begin_to / end_from / end_to). Linked Art's TimeSpan uses
        ``begin_of_the_begin`` / ``end_of_the_begin`` etc. We map them
        one-to-one and additionally pass through ``begin_comment`` as
        ``beginning_is_qualified_by``. ``None`` values are dropped so
        the resulting dict can be merged without producing nulls.
        """
        data = {
            'begin_of_the_begin':
                date_to_utc_iso_str(entity.dates.begin_from),
            'end_of_the_begin': date_to_utc_iso_str(entity.dates.begin_to),
            'beginning_is_qualified_by': entity.dates.begin_comment}
        return {k: v for k, v in data.items() if v is not None}

    @staticmethod
    def _get_loud_end_dates(entity: Entity | Link) -> dict[str, Any]:
        """Translate OpenAtlas end dates to LOUD TimeSpan keys.

        Counterpart of :meth:`_get_loud_begin_dates` for the closing
        side of an interval. We add one bit of best-effort recovery: if
        the user only provided an *open-ended* interval (no end dates
        at all), we still emit an ``end_of_the_end`` derived from the
        next-best-available date, because SHACL shapes on Linked Art
        TimeSpans require both bounds to be present.
        """
        begin_of_the_end = date_to_utc_iso_str(entity.dates.end_from)
        end_of_the_end = date_to_utc_iso_str(entity.dates.end_to)
        if end_of_the_end is None:
            end_of_the_end = begin_of_the_end \
                             or date_to_utc_iso_str(entity.dates.begin_to) \
                             or date_to_utc_iso_str(entity.dates.begin_from)
        data = {
            'begin_of_the_end': begin_of_the_end,
            'end_of_the_end': end_of_the_end,
            'end_is_qualified_by': entity.dates.end_comment}
        return {k: v for k, v in data.items() if v is not None}

    def get_loud_representations(
            self,
            image_links: list[Link],
            properties_set: dict[str, Any]) -> None:
        """Attach image / PDF media to the entity as LOUD representations.

        Each linked image becomes a ``VisualWorks`` enriched with its
        DigitalObject details and bundled under a single ``VisualItem``
        on the entity's ``representation`` slot. PDFs are handled
        differently: they are not visual works in the Linked Art sense,
        so they are exposed under ``subject_of`` as LinguisticObjects
        digitally carried by the PDF DigitalObject.
        """
        representation = []
        subject_of = []
        for link_ in image_links:
            entity = link_.domain
            mime_type, _ = mimetypes.guess_type(g.files[entity.id])
            image = {
                'id': entity_uri(entity),
                '_label': entity.name,
                'type': 'VisualWorks'}
            image.update(self.get_digital_object_details(entity, mime_type))
            if mime_type == 'application/pdf':  # pragma: no cover
                subject_of.append({
                    'id': self.generate_skolem_id(entity.id, 'pdf_subject'),
                    'type': 'LinguisticObject',
                    '_label': entity.name,
                    "language": [get_language()],
                    "classified_as": [
                        category_aat('300424602', 'Digital documents')],
                    'digitally_carried_by': [image]})
            else:
                representation.append(image)
        properties_set['representation'].append({
            'id': self.generate_skolem_id(0, 'visual_representation'),
            'type': 'VisualItem',
            "_label": "Visual Representations",
            'digitally_shown_by': representation})
        if subject_of:  # pragma: no cover
            properties_set['subject_of'].extend(subject_of)

    @staticmethod
    def get_iiif_subject_of(image_links: list[Link]) -> list[dict[str, Any]]:
        """Build ``subject_of`` stubs pointing at IIIF manifests, if any.

        For files that have an associated IIIF manifest we expose the
        manifest as a LinguisticObject (the descriptive metadata
        document) digitally carried by a DigitalObject whose
        ``access_point`` is the manifest URL and which ``conforms_to``
        the IIIF Presentation API 2.0. Files without a manifest are
        silently skipped so callers can use the result as-is.
        """
        subject_of = []
        skolem = LoudFormatter.generate_skolem_id
        for link_ in image_links:
            manifest_path = get_iiif_manifest_and_path(link_.domain.id)
            if not (manifest_path.get('IIIFManifest')
                    and manifest_path.get('IIIFBasePath')):
                continue  # pragma: no cover
            label = f'IIIF manifest of {link_.domain.name}'
            subject_of.append({
                'id': skolem(link_.id, 'iif_manifest'),
                "type": "LinguisticObject",
                "_label": label,
                "classified_as": [
                    category_aat('300266076', 'metadata (descriptive)')],
                "language": [get_language()],
                "digitally_carried_by": [{
                    'id': skolem(link_.id, 'DigitalObject'),
                    "type": "DigitalObject",
                    "_label": label,
                    "access_point": [{
                        "id": manifest_path['IIIFManifest'],
                        "_label": label,
                        "type": "DigitalObject"}],
                    "conforms_to": [{
                        "id": "https://iiif.io/api/presentation/2.0/",
                        "type": "InformationObject",
                        "_label": "IIIF Presentation API 2.0"}],
                    "format":
                        "application/ld+json;profile='https://iiif.io"
                        "/api/presentation/2/context.json'"}]})
        return subject_of

    @staticmethod
    def handle_authority_reference(
            link_: Link,
            properties_set: dict[str, Any],
            entity: Entity) -> None:
        """Materialise an inverse ``P67`` link from an authority reference.

        When an entity is referenced by an external authority record
        (``E32 Authority Document`` in CIDOC) we want two things in
        LOUD: a same-as link (``equivalent`` or close-match attribution)
        for graph reasoners, *and* a proper ``Identifier`` under
        ``identified_by`` so the reference is also discoverable through
        the entity's identifier list. This helper writes both at once.
        """
        system = g.reference_systems[link_.domain.id]
        skolem = LoudFormatter.generate_skolem_id
        match_reference = {
            "id": f'{system.resolver_url or ''}{link_.description}',
            "type": LoudFormatter._resolve_type(entity),
            "_label": entity.name}
        if is_close_match(link_):
            properties_set['attributed_by'].append(close_match_attribution(
                skolem(link_.id, 'close_match'), match_reference))
        else:
            properties_set['equivalent'].append(match_reference)
        properties_set['identified_by'].append({
            'id': skolem(link_.id, 'identifier'),
            "type": "Identifier",
            "content": link_.description,
            "_label": f"{link_.domain.name} Identifier",
            "classified_as": [
                aat_type('300404626', 'Authority Control Number')],
            "attributed_by": [{
                "id": skolem(link_.id, 'authority'),
                "type": "AttributeAssignment",
                "_label": f"Authority assignment by {link_.domain.name}",
                "carried_out_by": [{
                    "id":
                        system.website_url
                        or skolem(link_.id, 'group'),
                    "type": "Group",
                    "_label": link_.domain.name,
                    "identified_by":
                        LoudFormatter._inline_identifiers(link_.domain)}]}]})

    def handle_membership(
            self,
            link_: Link,
            properties_set: dict[str, Any]) -> None:
        """Render an inverse ``P107 is member of`` link.

        Linked Art expresses membership both *statically* (the entity is
        in ``member_of``) and *dynamically* (an Activity describing the
        role and its dates is added under ``carried_out``). We emit the
        static link always and add the activity only when the
        membership has a role type or dates worth exporting — otherwise
        the activity would carry no information.
        """
        domain = link_.domain
        group_ref = {
            'id': entity_uri(domain),
            'type': self._resolve_type(domain),
            '_label': domain.name,
            'identified_by': self._inline_identifiers(domain)}
        properties_set['member_of'].append(group_ref)
        if not (link_.type or link_.dates.dates_available()):
            return  # pragma: no cover
        carried_out: dict[str, Any] = {
            'id': self.generate_skolem_id(link_.id, 'membership'),
            "type": "Activity",
            '_label': f"Membership in {domain.name}",
            "carried_out_on_behalf_of": [dict(group_ref)]}
        if link_.type:
            if type_ := g.types.get(link_.type.id):
                carried_out['_label'] = (
                    f"Role as {type_.name} at {domain.name}")
                carried_out['classified_as'] = [
                    self._format_type_property(type_)]
        if link_.dates.dates_available():
            carried_out = carried_out | self.get_loud_timespan(link_)
        properties_set['carried_out'].append(carried_out)

    def process_link(
            self,
            link_: Link,
            properties_set: dict[str, Any],
            is_inverse: bool,
            root_entity: Entity) -> None:
        """Top-level dispatcher: route one Link to the right LOUD shape.

        Special cases are handled first because they don't fit the
        generic ``format_link`` -> ``properties_set[key].append`` pipe:

        - ``P53`` (current/has location) for the *domain* side becomes
          a single dict with the WKT geometry inlined as ``defined_by``;
        - inverse ``P67`` from an E32 Authority Document delegates to
          :meth:`handle_authority_reference`;
        - inverse ``P107`` delegates to :meth:`handle_membership`;
        - ``P2`` with a 'Radiocarbon' range delegates to
          :meth:`handle_radiocarbon`.

        Everything else takes the regular path: format the link's
        target as a stub and append it under the resolved property key.
        """
        code = link_.property.code
        is_domain = is_inverse
        if code == 'P53':
            base_property = self.format_link(link_, is_domain=is_domain)
            key = self.get_property_key(link_, is_inverse)
            if not is_inverse:
                if geometry := get_wkt_by_id(link_.range.id):
                    base_property['defined_by'] = geometry
                properties_set[key] = base_property
            else:
                properties_set[key].append(base_property)
            return
        if is_inverse and code == 'P67' \
                and link_.domain.cidoc_class.code == 'E32':
            self.handle_authority_reference(link_, properties_set, root_entity)
            return
        if is_inverse and code == 'P107':
            self.handle_membership(link_, properties_set)
            return
        if code == 'P2' and link_.range.name == 'Radiocarbon':
            self.handle_radiocarbon(link_, properties_set)
            return
        property_name = self.get_property_key(link_, is_inverse)
        formatted = self.format_link(link_, is_domain=is_domain)
        properties_set[property_name].append(formatted)

    def process_media_links(
            self,
            file_links: list[Link],
            properties_set: dict[str, Any],
            entity: Entity) -> None:
        """Attach all media-related blocks for a given entity.

        Three things happen here, in order:

        1. Linked files become ``representation`` / ``subject_of``
           entries via :meth:`get_loud_representations`.
        2. Linked files that expose a IIIF manifest add additional
           ``subject_of`` entries via :meth:`get_iiif_subject_of`.
        3. When the entity itself *is* a file (the root entity is a
           DigitalObject) the file's own size, mime, license and rights
           metadata are merged into ``properties_set``. The license is
           moved into ``referred_to_by`` so it doesn't clobber any
           license entries coming from other sources.
        """
        if file_links:
            self.get_loud_representations(file_links, properties_set)
            if iiif := self.get_iiif_subject_of(file_links):
                properties_set['subject_of'].extend(iiif)
        if entity.class_.name == 'file' and g.files.get(entity.id):
            properties_set.update(self.get_file_dimensions(entity))
            details = self.get_digital_object_details(entity)
            if referred := details.pop('referred_to_by', None):
                properties_set['referred_to_by'].extend(referred)
            properties_set.update(details)

    @staticmethod
    def handle_description(
            entity: Entity,
            properties_set: dict[str, Any]) -> None:
        """Emit the entity's description as a LinguisticObject.

        Plain text descriptions in OpenAtlas become ``referred_to_by``
        LinguisticObjects classified as 'description'. If the
        description carries inline text annotations we also attach them
        as ``part`` LinguisticObjects (see :meth:`_build_annotation`).
        """
        description: dict[str, Any] = {
            'id': LoudFormatter.generate_skolem_id(entity.id, 'description'),
            "type": "LinguisticObject",
            "_label": "Description",
            "content": entity.description,
            "language": [get_language()],
            "classified_as": [category_aat('300435416', 'description')]}
        annotations = AnnotationText.get_by_source_id(entity.id) or []
        part = [
            LoudFormatter._build_annotation(annotation, entity)
            for annotation in annotations]
        if part:  # pragma: no cover
            description['part'] = part
        properties_set['referred_to_by'].append(description)

    @staticmethod
    def _build_annotation(
            annotation: AnnotationText,
            entity: Entity) -> dict[str, Any]:  # pragma: no cover
        """Render an inline text annotation as a LOUD LinguisticObject.

        Annotations carry a slice of the parent description plus an
        optional link to another entity. We mirror that in LOUD with:

        - a LinguisticObject containing the annotated substring,
        - a digitally_carried_by DigitalObject acting as the *selector*
          (offset-based Text Position Selector, per Web Annotations),
        - optionally an ``about`` link to the referenced entity,
        - optionally a separate ``referred_to_by`` carrying the user's
          own note.
        """
        skolem = LoudFormatter.generate_skolem_id
        text = entity.description or ''
        inner_text = text[annotation.link_start:annotation.link_end]
        selector = aat_type('300055590', 'Selectors')
        annotation_dict: dict[str, Any] = {
            'id': skolem(annotation.id, 'annotation'),
            "type": "LinguisticObject",
            "_label": f"Annotation: {inner_text}",
            "content": inner_text,
            "language": [get_language()],
            "classified_as": [category_aat('300026100', 'Annotation')],
            "digitally_carried_by": [{
                'id': skolem(annotation.id, 'annotation_digital_object'),
                "type": "DigitalObject",
                "_label": f"Annotation selector: {inner_text}",
                "classified_as": [selector],
                "referred_to_by": [{
                    "id": skolem(annotation.id, 'annotation_text'),
                    "type": "LinguisticObject",
                    "_label": "Text Position Selector",
                    "content": f'{annotation.text}',
                    "language": [get_language()],
                    "classified_as": [category_aat(
                        '300055590', 'Text Position Selector')],
                    "identified_by": [{
                        "id": skolem(annotation.id, 'link_start'),
                        "type": "Identifier",
                        "_label": "start",
                        "content": f'{annotation.link_start}'}, {
                        "id": skolem(annotation.id, 'link_end'),
                        "type": "Identifier",
                        "_label": "end",
                        "content": f'{annotation.link_end}'}]}]}]}
        if annotation.entity_id:
            linked = Entity.get_by_id(annotation.entity_id)
            annotation_dict['about'] = [{
                'id': entity_uri(linked),
                'type': LoudFormatter._resolve_type(linked),
                '_label': linked.name,
                'identified_by': [
                    primary_name(linked.name), {
                        'id': LoudFormatter.generate_skolem_id(
                            linked.id, 'system_identifier'),
                        "type": "Identifier",
                        "_label": "System Identifier",
                        "content": entity_uri(linked)}]}]
        if annotation.text:
            annotation_dict['referred_to_by'] = [{
                "id": skolem(annotation.id, 'annotation_text'),
                "type": "LinguisticObject",
                "_label": annotation.text,
                "content": annotation.text,
                "language": [get_language()],
                "classified_as": [category_aat('300027200', 'Note')]}]
        return annotation_dict

    @staticmethod
    def _inline_identifiers(entity: Entity) -> list[dict[str, Any]]:
        """Build the canonical ``identified_by`` list for an entity.

        Every entity gets three identifiers, in this fixed order so
        diffing across exports stays stable:

        1. its primary name (the human-readable label, see
           :func:`primary_name`),
        2. its internal database URL (``api.entity`` with ``format=loud``
           — the entry point a developer would hit to retrieve the
           machine-readable LOUD document),
        3. its globally unique URI (``entity_uri``).

        The third one duplicates ``id`` on purpose: SHACL shapes on
        ``Identifier`` require ``content``, so we need an Identifier
        node carrying the URI as content even when the same URI is
        already the resource's ``id``.
        """
        skolem = LoudFormatter.generate_skolem_id
        internal_id = url_for(
            'api.entity',
            id_=entity.id,
            _external=True,
            format='loud')
        return [
            primary_name(
                entity.name, id_=skolem(entity.id, 'appellation')), {
                'id': internal_id,
                "type": "Identifier",
                "_label": "Internal Database ID",
                "content": internal_id,
                "classified_as": [aat_type('300404629', 'local URI')]}, {
                'id': skolem(entity.id, 'unique_identifier'),
                "type": "Identifier",
                "_label": "Unique Identifier",
                "content": entity_uri(entity),
                "classified_as": [
                    aat_type('300404012', 'unique identifier')]}]

    @staticmethod
    def add_core_metadata(
            entity: Entity,
            properties_set: dict[str, Any]) -> None:
        """Inject the entity's identifiers (and geometry, if any) at the root.

        Differs from :meth:`_inline_identifiers` only in that the
        primary name's skolem id is ``primary_name`` instead of
        ``appellation`` — the root-level appellation gets a stable id
        of its own so downstream consumers can link to it. For
        ``object_location`` entities we additionally inline the WKT
        geometry as ``defined_by`` (PFP / GeoSPARQL convention).
        """
        skolem = LoudFormatter.generate_skolem_id
        identifiers = LoudFormatter._inline_identifiers(entity)
        identifiers[0] = primary_name(
            entity.name, id_=skolem(entity.id, 'primary_name'))
        properties_set['identified_by'].extend(identifiers)
        if entity.class_.name == 'object_location':
            if geometry := get_wkt_by_id(entity.id):
                properties_set['defined_by'] = geometry

    def finalize_output(
            self,
            entity: Entity,
            properties_set: dict[str, Any],
            links_data: list[Link]) -> dict[str, Any]:
        """Assemble the final LOUD JSON-LD document for the root entity.

        Order of keys matters for human readability of the JSON output,
        so we merge with ``|`` in this deliberate sequence:

        1. ``@context`` first — conventionally the very first JSON-LD
           key consumers expect to see;
        2. the root entity's id/type/_label/archaeology classification;
        3. the timespan / life-events block;
        4. all the accumulated property triples (``identified_by``,
           ``classified_as``, ``referred_to_by``, ...).

        Returns a plain dict ready to be serialised as JSON-LD.
        """
        self.add_core_metadata(entity, properties_set)
        if entity.description:
            self.handle_description(entity, properties_set)
        return ({'@context': app.config['API_CONTEXT']['LOUD']} |
                self.base_entity_dict(entity) |
                self.get_loud_timespan(entity, links_data) |
                properties_set)


def get_loud_entities(
        data: dict[str, Any],
        loud: dict[str, str],
        type_references: dict[int, list[Link]]) -> Any:
    """Build the full LOUD JSON-LD document for one OpenAtlas entity.

    This is the public entry point used by the API. ``data`` is the
    bundle prepared upstream and contains:

    - ``entity`` — the root :class:`Entity`,
    - ``links`` — outgoing Links (``entity`` is the domain),
    - ``links_inverse`` — incoming Links (``entity`` is the range).

    Processing happens in three passes:

    1. Outgoing links are dispatched to :meth:`LoudFormatter.process_link`,
       except for ``OA8`` / ``OA9`` (birth/death/formation/dissolution
       places) which are consumed later by the timespan logic instead.
    2. Incoming links go through the same dispatcher, with one
       optimisation: file links are collected separately so they can be
       batched into :meth:`process_media_links`. Doing them one-by-one
       would produce N independent ``representation`` containers
       instead of one.
    3. ``finalize_output`` assembles everything into a single JSON-LD
       dict, including the ``@context``.
    """
    entity = data['entity']
    formatter = LoudFormatter(loud, type_references)
    properties_set: dict[str, Any] = defaultdict(list)
    skipped = {'OA8', 'OA9'}
    for link_ in data['links']:
        if link_.property.code not in skipped:
            formatter.process_link(
                link_, properties_set, is_inverse=False, root_entity=entity)
    file_links = []
    for link_ in data['links_inverse']:
        if link_.property.code in skipped:
            continue
        domain = link_.domain
        if domain.class_.name == 'file' and g.files.get(domain.id):
            file_links.append(link_)
            continue
        formatter.process_link(
            link_, properties_set, is_inverse=True, root_entity=entity)
    formatter.process_media_links(file_links, properties_set, entity)
    return formatter.finalize_output(entity, properties_set, data['links'])


def get_loud_crm_relation(link_: Link, inverse: bool = False) -> str:
    """Build the CIDOC-CRM property label used as a LOUD context key.

    The LOUD ``@context`` (see ``loud.json``) is keyed by the
    concatenation ``crm:<code> <english label>`` (or, for inverse
    properties, ``crm:<code>i <inverse english label>``). This helper
    reconstructs that string from a Link so :meth:`LoudFormatter._loud_relation`
    can look the corresponding LOUD property name up in the context.
    """
    property_ = f' {link_.property.i18n['en']}'
    if inverse and link_.property.i18n_inverse['en']:
        property_ = f'i {link_.property.i18n_inverse['en']}'
    return f'crm:{link_.property.code}{property_}'
