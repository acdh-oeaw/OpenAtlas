import re
from collections import defaultdict

from openatlas import app
from openatlas.models.entity import Entity, insert


def add_new_hierarchy(name_: str) -> Entity:
    hierarchy = insert({
        'openatlas_class_name': 'type',
        'name': f'{name_} (new)',
        'description': ''})
    Entity.insert_hierarchy(
        hierarchy,
        'custom',
        ['stratigraphic_unit'],
        multiple=True)
    return hierarchy


with app.test_request_context():
    app.preprocess_request()
    elisabethinen_location = Entity.get_by_id(145, with_location=True).location

    ## Patients ##
    cs_patients = Entity.get_by_id(357)
    patientinnen_group = insert({
        'name': f'Patients',
        'openatlas_class_name': 'group'})
    patientinnen_group.link('P2', cs_patients)
    patientinnen_group.link('P74', elisabethinen_location)
    patients = cs_patients.get_linked_entities('P2', ['person'], inverse=True)
    for patient in patients:
        patient.link('P107', patientinnen_group, inverse=True)

    patient_super_event = insert({
        'name': f'Patient visits',
        'openatlas_class_name': 'activity'})
    patient_super_event.link('P7', elisabethinen_location)
    patient_super_event.link('P2', cs_patients)
    visits = cs_patients.get_linked_entities('P2', ['activity'], inverse=True)
    for visit in visits:
        visit.link('P9', patient_super_event, inverse=True)

    ## Recipies ##
    cs_pharmacy = Entity.get_by_id(708)
    all_sources = Entity.get_by_class('source', types=True)
    recipies = []
    for source in all_sources:
        if source.standard_type and source.standard_type.name == 'Recipe book':
            recipies.append(source)
    for recipie in recipies:
        recipie.link('P2', cs_pharmacy)

    ## Graves ##
    cs_graves = Entity.get_by_id(16305)

    ### Files ###
    all_files = Entity.get_by_class('file', types=True)
    files = []
    for file in all_files:
        for type_ in file.types:
            if type_.name in ['Find', 'Excavation', 'Skelettmännchen']:
                files.append(file)
    for file in files:
        file.link('P2', cs_graves)

    ### Position ###
    new_position_hierarchy = add_new_hierarchy('Position')
    position_hierarchy = Entity.get_by_id(16311)
    all_position_types = position_hierarchy.get_linked_entities(
        'P127',
        inverse=True)
    positions = defaultdict(list)
    for position_type in all_position_types:
        position_type_name = re.split(r'[;,|–/]', position_type.name.lower())
        for name in position_type_name:
            positions[name.strip()].append(
                position_type.get_linked_entities('P2', inverse=True))

    for name, entities in positions.items():
        if not name:
            continue
        new_type = insert({
            'name': name.rstrip('.').strip(),
            'openatlas_class_name': 'type'})
        new_type.link('P127', new_position_hierarchy)
        for entity in entities:
            new_type.link('P2', entity, inverse=True)

    ### Dislocation ###
    new_dislocation_hierarchy = add_new_hierarchy('Dislocation')
    dislocation_hierarchy = Entity.get_by_id(16314)
    all_dislocation_types = dislocation_hierarchy.get_linked_entities(
        'P127',
        inverse=True)
    dislocation = defaultdict(list)
    for dislocation_type in all_dislocation_types:
        dislocation_type_name = re.split(
            r'[;,|–/]',
            dislocation_type.name.lower())
        for name in dislocation_type_name:
            dislocation[name.strip()].append(
                dislocation_type.get_linked_entities('P2', inverse=True))

    for name, entities in dislocation.items():
        if not name:
            continue
        new_type = insert({
            'name': name.rstrip('.').strip(),
            'openatlas_class_name': 'type'})
        new_type.link('P127', new_dislocation_hierarchy)
        for entity in entities:
            new_type.link('P2', entity, inverse=True)
