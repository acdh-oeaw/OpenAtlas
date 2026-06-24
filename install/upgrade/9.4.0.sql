BEGIN;

-- Raise database version
UPDATE web.settings SET value = '9.4.0' WHERE name = 'database_version';

-- Standard API field for DOI with Crossref (#2601, #2617)
INSERT INTO model.entity (name, cidoc_class_code, description, openatlas_class_name)
SELECT
    'DOI',
    'E32',
    'A DOI (Digital Object Identifier) is a persistent identifier for digital resources. OpenAtlas uses Crossref for autocomplete, but any DOI can be stored and resolved, even if it is not found there. Please enter only the DOI identifier itself, not the full URL or domain.',
    'reference_system'
WHERE NOT EXISTS (
    SELECT 1 FROM model.entity WHERE name='DOI' AND openatlas_class_name = 'reference_system'
);

INSERT INTO web.reference_system (system, name, api, entity_id, resolver_url, website_url, identifier_example)
VALUES (
    true,
    'DOI',
    'DOI',
    (SELECT id FROM model.entity WHERE name = 'DOI' AND openatlas_class_name = 'reference_system'),
    'https://doi.org/',
    'https://www.crossref.org/',
    '10.5281/zenodo.20451000')
ON CONFLICT (name) DO UPDATE SET resolver_url = 'https://doi.org/', system=true, api='DOI';

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='DOI'), 'edition'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='DOI')
        AND openatlas_class_name = 'edition'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='DOI'), 'bibliography'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='DOI')
        AND openatlas_class_name = 'bibliography'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='DOI'), 'external_reference'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='DOI')
        AND openatlas_class_name = 'external_reference'
);

INSERT INTO model.link (property_code, range_id, domain_id) VALUES (
    'P2',
    (SELECT id FROM model.entity WHERE name='exact match'),
    (SELECT id FROM model.entity WHERE name='DOI' AND openatlas_class_name = 'reference_system')
);

-- Public flag for files as type (#2780)
-- add new type
INSERT INTO model.entity (cidoc_class_code, openatlas_class_name, name, description)
VALUES
    ('E55', 'type', 'Public sharing allowed', 'Mark files for public sharing, e.g. on presentation sites'),
    ('E55', 'type', 'yes_temp', ''),
    ('E55', 'type', 'no_temp', '');

INSERT INTO model.link (property_code, range_id, domain_id) VALUES
  ('P127', (SELECT id FROM model.entity WHERE name='Public sharing allowed'), (SELECT id FROM model.entity WHERE name='yes_temp')),
  ('P127', (SELECT id FROM model.entity WHERE name='Public sharing allowed'), (SELECT id FROM model.entity WHERE name='no_temp'));

INSERT INTO web.hierarchy (id, name, category, multiple, directional, required) VALUES
  ((SELECT id FROM model.entity WHERE name='Public sharing allowed'), 'Public sharing allowed', 'system', False, False, True);

INSERT INTO web.hierarchy_openatlas_class (hierarchy_id, openatlas_class_name) VALUES
  ((SELECT id FROM web.hierarchy WHERE name='Public sharing allowed'), 'file');

-- map former data
INSERT INTO model.link (property_code, domain_id, range_id)
SELECT 'P2', entity_id, (SELECT id FROM model.entity WHERE name = 'yes_temp')
FROM model.file_info WHERE public = true;

INSERT INTO model.link (property_code, domain_id, range_id)
SELECT 'P2', entity_id, (SELECT id FROM model.entity WHERE name = 'no_temp')
FROM model.file_info WHERE public = false;

DROP TABLE model.file_info;

-- rename temp names
UPDATE model.entity SET name = 'Yes' WHERE name = 'yes_temp';
UPDATE model.entity SET name = 'No' WHERE name = 'no_temp';

END;
