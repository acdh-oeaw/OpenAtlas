BEGIN;

-- Raise database version
UPDATE web.settings SET value = '9.4.0' WHERE name = 'database_version';

-- Standard API field for Crossref (#2601, #2617)
UPDATE web.reference_system SET api = 'Crossref', name = 'Crossref (DOI)' WHERE name = 'DOI' OR name = 'Crossref';

INSERT INTO model.entity (name, cidoc_class_code, description, openatlas_class_name)
SELECT
    'Crossref (DOI)',
    'E32',
    'A Digital Object Identifier (DOI) is a unique, permanent alphanumeric string assigned to a digital document to provide a persistent link to its location on the internet.',
    'reference_system'
WHERE NOT EXISTS (
    SELECT 1 FROM model.entity WHERE name='Crossref (DOI)' AND openatlas_class_name = 'reference_system'
);

INSERT INTO web.reference_system (system, name, api, entity_id, resolver_url, website_url, identifier_example)
VALUES (
    true,
    'Crossref (DOI)',
    'Crossref',
    (SELECT id FROM model.entity WHERE name = 'Crossref (DOI)' AND openatlas_class_name = 'reference_system'),
    'https://doi.org/',
    'https://www.crossref.org/',
    '10.5281/zenodo.20451000')
ON CONFLICT (name) DO UPDATE SET resolver_url = 'https://doi.org/', system=true, api='Crossref';

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)'), 'source'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)')
        AND openatlas_class_name = 'source'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)'), 'text'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)')
        AND openatlas_class_name = 'text'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)'), 'edition'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)')
        AND openatlas_class_name = 'edition'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)'), 'bibliography'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)')
        AND openatlas_class_name = 'bibliography'
);

INSERT INTO web.reference_system_openatlas_class (reference_system_id, openatlas_class_name)
SELECT (SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)'), 'external_reference'
WHERE NOT EXISTS (
    SELECT 1 FROM web.reference_system_openatlas_class
    WHERE
        reference_system_id=(SELECT entity_id FROM web.reference_system WHERE name='Crossref (DOI)')
        AND openatlas_class_name = 'external_reference'
);

END;
