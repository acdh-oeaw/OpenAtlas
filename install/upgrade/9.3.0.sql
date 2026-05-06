BEGIN;

UPDATE web.settings SET value = '9.3.0' WHERE name = 'database_version';

ALTER TABLE model.entity ADD COLUMN IF NOT EXISTS uuid UUID;

UPDATE model.entity SET uuid = gen_random_uuid() WHERE uuid IS NULL;

ALTER TABLE model.entity ALTER COLUMN uuid SET NOT NULL;
ALTER TABLE model.entity ADD CONSTRAINT entity_uuid_unique UNIQUE (uuid);
ALTER TABLE model.entity ALTER COLUMN uuid SET DEFAULT gen_random_uuid();

COMMIT;
