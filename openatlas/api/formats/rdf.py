from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Iterator
from urllib.parse import quote

from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

from openatlas import app
from openatlas.api.resources.resolve_endpoints import get_loud_context


# rdflib logs a warning every time it cannot cast a lexical date to a
# Python value. This fires for valid BC dates (e.g. '-4712-12-31') because
# date.fromisoformat does not accept negative years. The literal stays
# correctly typed as xsd:date in the graph, so the warning is just noise.
# Per rdflib issue #2210, the recommended way is to filter on the actual
# isoformat ValueError carried in record.exc_info, so unrelated lexical
# cast warnings (different datatypes, different root causes) still pass
# through and remain visible.
class _SuppressYearBeforeCommonEraWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
        message = record.getMessage()
        if record.exc_info is None:
            return True
        _error_type, error_payload, _error_traceback = record.exc_info
        should_suppress = (
            message.startswith(
                'Failed to convert Literal lexical form to value')
            and "Invalid isoformat string: '-" in str(error_payload))
        return not should_suppress


logging.getLogger('rdflib.term').addFilter(
    _SuppressYearBeforeCommonEraWarning())

# Cache the JSON-LD @context once: it is reused for every triple, every
# entity, every export. All resolvers below close over this dict.
_CONTEXT: dict[str, Any] = get_loud_context().get('@context', {})

_DEFAULT_NAMESPACES: dict[str, str] = {
    'crm': 'http://www.cidoc-crm.org/cidoc-crm/',
    'la': 'https://linked.art/ns/terms/',
    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'geo': 'http://www.opengis.net/ont/geosparql#'}

_GEO = Namespace('http://www.opengis.net/ont/geosparql#')

_RESERVED_KEYS: frozenset[str] = frozenset({'id', 'type', '@context'})

# Markers found in every URI we mint ourselves (see entity_uri,
# generate_skolem_id, internal_database_id in loud.py). Anything else
# (Wikidata, Getty AAT, CIDOC CRM, ...) is treated as an external URI:
# we link to it but we do NOT assert rdf:type for it and we do NOT
# expand its inline LOUD stub. Asserting types on external URIs both
# is semantically wrong (open-world: we don't own those resources) and
# triggers SHACL violations because we cannot supply the identifiers /
# appellations the shapes require.
_OWN_URI_MARKERS: tuple[str, ...] = (
    '/api/uuid/',
    '/api/entity/',
    '/api/generated/')


def _is_own_uri(uri: str) -> bool:
    return any(marker in uri for marker in _OWN_URI_MARKERS)

# Patterns used to infer an XSD datatype from a literal's string form.
# SHACL date/time shapes only accept properly typed literals, so any
# date-like string we emit must carry the matching xsd:* datatype.
_DATE_RE = re.compile(r'^-?\d{4}-\d{2}-\d{2}$')
_DATETIME_RE = re.compile(
    r'^-?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
    r'(\.\d+)?(Z|[+-]\d{2}:\d{2})?$')
_GYEARMONTH_RE = re.compile(r'^-?\d{4}-\d{2}$')
_GYEAR_RE = re.compile(r'^-?\d{4}$')

# WKT geometry literals must be typed as geo:wktLiteral so the PFP SHACL
# shape on crm:P168_place_is_defined_by recognizes them. Linked.Places /
# GeoSPARQL convention; OpenAtlas only emits 2D WKT today, but the regex
# also accepts Z/M variants for forward compatibility.
_WKT_RE = re.compile(
    r'^\s*(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|'
    r'MULTIPOLYGON|GEOMETRYCOLLECTION)\s*[ZM]?\s*\(',
    re.IGNORECASE)


def _typed_literal(value: Any) -> Literal:
    if isinstance(value, str):
        if _DATE_RE.match(value):
            return Literal(value, datatype=XSD.date)
        if _DATETIME_RE.match(value):   # pragma: no cover
            return Literal(value, datatype=XSD.dateTime)
        if _GYEARMONTH_RE.match(value):  # pragma: no cover
            return Literal(value, datatype=XSD.gYearMonth)
        if _GYEAR_RE.match(value):  # pragma: no cover
            return Literal(value, datatype=XSD.gYear)
        if _WKT_RE.match(value):
            return Literal(value, datatype=_GEO.wktLiteral)
    return Literal(value)


def _set_proxies() -> None:  # pragma: no cover
    """Propagate the application's HTTP/HTTPS proxy settings to env vars.

    rdflib (and the libraries it uses for namespace lookups) reads the
    ``http_proxy`` / ``https_proxy`` environment variables directly. When
    OpenAtlas is deployed behind a corporate proxy, those values live in
    ``app.config['PROXIES']``. This helper copies whatever is configured
    there into ``os.environ`` so that any outbound request rdflib might
    make (e.g. resolving an unknown vocabulary URI) goes through the
    correct proxy.

    It is called once per public entry point (``rdf_output`` and
    ``rdf_export_to_file``) and is a no-op if no proxy is configured.
    """
    for scheme in ('http', 'https'):
        if scheme in app.config['PROXIES']:
            os.environ[f'{scheme}_proxy'] = app.config['PROXIES'][scheme]


def _bind_namespaces(graph: Graph) -> None:
    """Register all known prefix -> namespace mappings on an rdflib Graph.

    A serialized RDF document is much more readable when full IRIs are
    rendered as short ``prefix:localname`` CURIEs (e.g. ``crm:E21`` instead
    of ``http://www.cidoc-crm.org/cidoc-crm/E21``). rdflib only does that
    abbreviation for prefixes that have been explicitly bound on the graph.

    Two sources are merged:

    1. **The LOUD JSON-LD ``@context``** (``_CONTEXT``): every top-level
       entry whose value is a plain string ending in ``/`` or ``#`` is
       treated as a namespace declaration (the ``/`` / ``#`` heuristic
       filters out entries that are property definitions, not namespaces).
    2. **A hardcoded fallback set** (``_DEFAULT_NAMESPACES``) covering the
       four prefixes we always want present (``crm``, ``la``, ``rdfs``,
       ``rdf``), even if the JSON-LD context happens to omit them.

    The defaults are bound last so they win on conflict.
    """
    for prefix, uri in _CONTEXT.items():
        if isinstance(uri, str) and uri.endswith(('/', '#')):
            graph.bind(prefix, Namespace(uri))
    for prefix, uri in _DEFAULT_NAMESPACES.items():
        graph.bind(prefix, Namespace(uri))


@lru_cache(maxsize=None)
def _expand_curie(curie: str) -> str:
    """Expand a compact IRI (CURIE) such as ``crm:E21`` to its full URI.

    A CURIE is a shorthand of the form ``prefix:localname``. The prefix is
    looked up in the JSON-LD ``@context`` (``_CONTEXT``); if it maps to a
    namespace string, ``localname`` is appended. Examples:

    - ``"crm:P2"`` -> ``"http://www.cidoc-crm.org/cidoc-crm/P2"``
    - ``"la:equivalent"`` -> ``"https://linked.art/ns/terms/equivalent"``

    If the input does not contain a colon, or the prefix is unknown, the
    original string is returned unchanged so the caller can still build a
    URIRef from it (rdflib will simply treat it as an absolute IRI).

    The result is memoized with ``lru_cache`` because the same handful of
    CURIEs (a few dozen predicates and types) appear in tens of thousands
    of triples across a single export. Caching turns a repeated
    dict-lookup + string-split + string-concat into an O(1) hit.
    """
    if ':' not in curie:
        return curie  # pragma: no cover
    prefix, local = curie.split(':', 1)
    base = _CONTEXT.get(prefix)
    if isinstance(base, str):
        return base + local
    return curie  # pragma: no cover


def _entry_uri(entry: Any) -> str | None:
    """Extract the full URI out of a single JSON-LD context entry.

    Inside a JSON-LD ``@context`` a term can be defined in two shapes::

        "identified_by": "crm:P1_is_identified_by"           # string form
        "identified_by": {"@id": "crm:P1_is_identified_by",  # object form
                          "@type": "@id"}

    This helper normalizes both shapes to the fully expanded URI by
    delegating CURIE expansion to ``_expand_curie``. Anything else
    (``None``, a list, a number, ...) yields ``None`` so the caller can
    decide how to handle an unresolvable term.
    """
    if isinstance(entry, dict) and '@id' in entry:
        return _expand_curie(entry['@id'])
    if isinstance(entry, str):  # pragma: no cover
        return _expand_curie(entry)
    return None


@lru_cache(maxsize=None)
def _resolve_predicate(
        key: str,
        data_type: str | None) -> URIRef | None:
    """Translate a JSON property name into the matching RDF predicate.

    LOUD JSON-LD is *scoped*: the same JSON key can map to different RDF
    predicates depending on the surrounding ``type``. For example, the key
    ``content`` means ``crm:P190`` inside a ``LinguisticObject`` but maps
    to something else inside an ``Identifier``. The JSON-LD context
    encodes this with nested ``@context`` blocks on each type.

    Resolution therefore happens in two ordered steps:

    1. **Type-scoped lookup.** If ``data_type`` is given and the context
       has a nested ``@context`` for that type, prefer the predicate
       defined there.
    2. **Top-level fallback.** Otherwise look the key up directly in the
       root ``@context``.

    Returns ``None`` when the key cannot be resolved at all; the caller
    silently drops such triples (this is intentional: unknown / private
    JSON keys must not pollute the RDF output).

    Cached with ``lru_cache`` because the (key, type) cardinality is
    small (a few hundred combinations) but the call count is huge.
    """
    if data_type:
        type_entry = _CONTEXT.get(data_type)
        if isinstance(type_entry, dict):
            sub_ctx = type_entry.get('@context')
            if isinstance(sub_ctx, dict) and key in sub_ctx:
                if uri := _entry_uri(sub_ctx[key]):
                    return URIRef(uri)
    if uri := _entry_uri(_CONTEXT.get(key)):
        return URIRef(uri)
    return None  # pragma: no cover


@lru_cache(maxsize=None)
def _resolve_type_uri(data_type: str) -> str | None:
    """Resolve a JSON ``"type": ...`` value to a full class URI.

    The JSON-LD ``type`` field can appear in three different forms; this
    helper handles all of them in priority order:

    1. **Already a CURIE** (contains ``:``, e.g. ``"crm:E21"``) -- expand
       it via ``_expand_curie``.
    2. **A bare term defined in the context** (e.g. ``"Person"``) -- look
       it up in ``_CONTEXT`` and return the ``@id`` of that entry.
    3. **An unknown bare term** -- as a last-resort fallback, assume it
       lives in the Linked Art namespace (``la:``) and prepend that base.
       This keeps the RDF output well-formed even for terms that have not
       (yet) been added to the local JSON-LD context.

    The returned string is later wrapped in ``URIRef(...)`` by the caller
    to produce an ``rdf:type`` triple. Cached for the same reason as the
    other resolvers: bounded cardinality, huge call volume.
    """
    if ':' in data_type:
        return _expand_curie(data_type)  # pragma: no cover
    entry = _CONTEXT.get(data_type)
    if isinstance(entry, dict) and '@id' in entry:
        return _expand_curie(entry['@id'])
    # pragma: no cover
    la_base = _CONTEXT.get('la') or 'https://linked.art/ns/terms/'
    return la_base + data_type


def _uri_ref(uri: str) -> URIRef:
    """Build a safely percent-encoded ``URIRef`` from a raw URI string.

    OpenAtlas IDs can contain characters that are technically illegal in
    an IRI (spaces, parentheses, unicode in some legacy data, ...). Most
    RDF serializers would either crash or produce invalid output on such
    input. ``urllib.parse.quote`` percent-encodes everything except the
    structural characters we *want* to keep readable:

    - ``:`` so the scheme separator (``https:``) survives
    - ``/`` so path segments stay intact
    - ``#`` so fragment identifiers stay intact

    The result is a valid ``URIRef`` that all rdflib serializers accept.
    """
    return URIRef(quote(uri, safe=':/#'))


def _emit_value(
        graph: Graph,
        subject: URIRef | BNode,
        predicate: URIRef,
        value: Any,
        entity_id: str | None = None) -> None:
    """Add one or more triples for a single (subject, predicate, value).

    The JSON value attached to a property can have several shapes; this
    function dispatches on that shape and writes the appropriate triples
    into ``graph``:

    - **List** -- emit one triple per item. Each item is itself either:
        * a dict with an ``id``: emit ``(subject, predicate, <id>)`` as a
          link to the referenced resource;
        * a dict without an ``id``: create a fresh blank node, link it,
          and recurse via ``_expand_into`` so its inner properties become
          triples about that blank node (this is how nested anonymous
          structures like ``identified_by`` chains are flattened to RDF);
        * a scalar: emit it as an ``rdflib.Literal``.
    - **Dict** (not inside a list) -- only emitted when it has an ``id``;
      a dict without ``id`` at this level is intentionally skipped. This
      preserves the original behaviour of the previous two-pass
      implementation, where anonymous nesting was only recognised inside
      lists.
    - **Scalar** (string, int, bool, ...) -- emitted as an
      ``rdflib.Literal``.

    Note: the function is mutually recursive with ``_expand_into``.
    """
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                if object_id := item.get('id'):
                    target = _uri_ref(str(object_id))
                    graph.add((subject, predicate, target))
                    if _is_own_uri(str(object_id)):
                        _expand_into(graph, target, item, entity_id)
                else:
                    bnode = BNode()
                    graph.add((subject, predicate, bnode))
                    _expand_into(graph, bnode, item, entity_id)
            else:  # pragma: no cover
                graph.add((subject, predicate, _typed_literal(item)))
        return
    if isinstance(value, dict):
        if object_id := value.get('id'):
            target = _uri_ref(str(object_id))
            graph.add((subject, predicate, target))
            if _is_own_uri(str(object_id)):
                _expand_into(graph, target, value, entity_id)
        return
    graph.add((subject, predicate, _typed_literal(value)))


def _expand_into(
        graph: Graph,
        subject: URIRef | BNode,
        data: dict[str, Any],
        entity_id: str | None = None) -> None:
    """Convert all properties of a JSON object into triples about ``subject``.

    Steps performed:

    1. **Type triple.** If ``data`` has a ``"type"`` field that resolves to
       a known class URI (via ``_resolve_type_uri``), emit
       ``(subject, rdf:type, <class>)``.
    2. **Property triples.** Iterate over every remaining key/value pair,
       skipping JSON-LD reserved keys (``id``, ``type``, ``@context``),
       and delegate to ``_emit_value`` for the actual triple creation.
       Keys that cannot be resolved to a predicate are silently skipped.

    The ``data_type`` value is forwarded into ``_resolve_predicate`` so
    that type-scoped predicate definitions in the JSON-LD context are
    honoured (see ``_resolve_predicate`` for details).

    Recurses indirectly through ``_emit_value`` for nested anonymous
    structures.
    """
    data_type = data.get('type')
    if data_type and (type_uri := _resolve_type_uri(str(data_type))):
        graph.add((subject, RDF.type, URIRef(type_uri)))
    for key, value in data.items():
        if key in _RESERVED_KEYS:
            continue
        if predicate := _resolve_predicate(key, data_type):
            _emit_value(graph, subject, predicate, value, entity_id)


def _add_entity(graph: Graph, data: dict[str, Any]) -> None:
    """Insert the triples for one top-level LOUD entity into ``graph``.

    This is the per-entity entry point used by both ``rdf_output`` (one
    shared graph for the whole response) and ``rdf_export_to_file`` (a
    fresh graph per entity, to stream N-Triples line by line).

    The subject of the entity's triples is chosen as follows:

    - if the entity has an ``id``, use that as a URI (percent-encoded);
    - otherwise fall back to a blank node, so the entity's properties
      are still emitted -- just anonymously.

    Non-dict input is defensively ignored (the upstream LOUD formatter is
    expected to yield dicts, but we don't want a stray ``None`` or list
    item to break a multi-entity export).
    """
    if not isinstance(data, dict):
        return  # pragma: no cover
    subject_id = data.get('id')
    if subject_id:
        subject: URIRef | BNode = _uri_ref(str(subject_id))
    else:  # pragma: no cover
        subject = BNode()
    _expand_into(graph, subject, data, subject_id)


def rdf_output(data: Iterator[dict[str, Any]], format_: str) -> Any:
    """Serialize a stream of LOUD entities into an in-memory RDF document.

    Public entry point used by the API endpoints (see
    ``openatlas/api/endpoints/endpoint.py``) whenever a client requests an
    RDF representation (Turtle, RDF/XML, N-Triples, JSON-LD, ...).

    Pipeline:

    1. Mirror proxy configuration into the environment (``_set_proxies``)
       so rdflib's outbound requests, if any, go through the right proxy.
    2. Build a single ``rdflib.Graph`` and pre-bind all known prefixes on
       it (``_bind_namespaces``) so the serialized output uses readable
       CURIEs.
    3. For each LOUD entity yielded by ``data``, add its triples to that
       graph (``_add_entity``).
    4. Serialize the whole graph in ``format_`` (one of rdflib's format
       names) and return the resulting UTF-8 ``bytes``.

    The shared-graph design lets the serializer deduplicate prefixes and
    produce a compact document; the trade-off is peak memory, which is
    acceptable here because API responses already need to fit in memory.
    """
    _set_proxies()
    graph = Graph()
    _bind_namespaces(graph)
    for item in data:
        _add_entity(graph, item)
    return graph.serialize(format=format_, encoding='utf-8')


def rdf_export_to_file(
        data: Iterator[dict[str, Any]],
        rdf_export_path: str) -> str:
    """Stream a stream of LOUD entities into an N-Triples file on disk.

    Used for bulk exports (potentially millions of triples) where holding
    the whole graph in memory like ``rdf_output`` does would be wasteful.

    Strategy:

    - Open the target file once in binary append-via-write mode.
    - For each entity, build a **fresh** small ``Graph``, add only that
      entity's triples, serialize it directly to UTF-8 bytes in N-Triples
      format, and write those bytes to the file.
    - N-Triples is chosen on purpose: each triple is a self-contained
      line, so concatenating per-entity serializations produces a valid
      N-Triples document without any post-processing.

    This keeps peak memory bounded by the largest single entity rather
    than by the whole dataset, and avoids the previous implementation's
    overhead of splitting the serialized output into lines and
    re-encoding each line.

    Returns the path that was written, for the caller's convenience.
    """
    _set_proxies()
    with open(rdf_export_path, 'wb') as output_file:
        for item in data:
            graph = Graph()
            _add_entity(graph, item)
            output_file.write(graph.serialize(format='nt', encoding='utf-8'))
    return rdf_export_path
