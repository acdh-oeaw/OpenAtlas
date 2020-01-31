-- Upgrade 4.x.x to 4.2.0
-- Be sure to backup the database and read the update notes before executing this!

BEGIN;

-- #1089 Body Parts User Interface
INSERT INTO model.entity (class_code, name, description) VALUES ('E55', 'Human Remains', 'Human remains, that for example were discovered during archaeological excavations. They are associated with a stratigraphic unit (in most cases a skeleton) that is composed of (P46) one or multiple parts (in most cases bones) that are classified as biological objects (E20). From a hierarchical point of view the human remains are one level below the stratigraphic unit respectively the entity whose sum of parts resembles the individual/skeleton. This way individual bones or body parts can be treated individually and be connected with separate classifications (e.g. Injuries of the right upper arm or caries on a certain tooth).');
INSERT INTO model.entity (class_code, name, description) VALUES ('E55', 'Upper Body', '');
INSERT INTO model.entity (class_code, name, description) VALUES ('E55', 'Lower Body', '');
INSERT INTO model.link (property_code, range_id, domain_id) VALUES ('P127', (SELECT id FROM model.entity WHERE name='Human Remains' AND class_code = 'E55'), (SELECT id FROM model.entity WHERE name='Arm'));
INSERT INTO model.link (property_code, range_id, domain_id) VALUES ('P127', (SELECT id FROM model.entity WHERE name='Human Remains' AND class_code = 'E55'), (SELECT id FROM model.entity WHERE name='Leg'));
INSERT INTO web.hierarchy (id, name, multiple, system, directional, value_type) VALUES ((SELECT id FROM model.entity WHERE name='Human Remains' AND class_code = 'E55'), 'Human Remains', False, True, False, False);
INSERT INTO web.form (name, extendable) VALUES ('Human Remains', True);
INSERT INTO web.hierarchy_form (hierarchy_id, form_id) VALUES ((SELECT id FROM web.hierarchy WHERE name='Human Remains'),(SELECT id FROM web.form WHERE name='Human Remains'));

COMMIT;
