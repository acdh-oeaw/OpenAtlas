import os
import sys

sys.path.insert(0, '/usr/local/openatlas')
os.environ['INSTANCE_PATH'] = f'{os.path.dirname(os.path.abspath(__file__))}/'

from install.upgrade import database_upgrade
database_upgrade.database_upgrade()
