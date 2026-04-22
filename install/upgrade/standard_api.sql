
-- Standard API field for external reference systems (#2737)
ALTER TABLE web.reference_system ADD COLUMN "api" text;
UPDATE web.reference_system SET api = 'wikidata' WHERE name = 'Wikidata';
UPDATE web.reference_system SET api = 'geonames' WHERE name = 'GeoNames';
UPDATE web.reference_system SET api = 'cadaster' WHERE name = 'Cadaster';
