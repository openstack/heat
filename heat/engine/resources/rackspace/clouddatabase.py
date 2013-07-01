# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from heat.common import exception
from heat.engine.resources.rackspace import rackspace_resource
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class CloudDBInstance(rackspace_resource.RackspaceResource):
    '''
    Rackspace cloud database resource.
    '''
    database_schema = {
        "Character_set": {
            "Type": "String",
            "Default": "utf8",
            "Required": False
        },
        "Collate": {
            "Type": "String",
            "Default": "utf8_general_ci",
            "Required": False
        },
        "Name": {
            "Type": "String",
            "Required": True,
            "MaxLength": "64",
            "AllowedPattern": "[a-zA-Z0-9_]+[a-zA-Z0-9_@?#\s]*[a-zA-Z0-9_]+"
        }
    }

    user_schema = {
        "Name": {
            "Type": "String",
            "Required": True,
            "MaxLength": "16",
            "AllowedPattern": "[a-zA-Z0-9_]+[a-zA-Z0-9_@?#\s]*[a-zA-Z0-9_]+"
        },
        "Password": {
            "Type": "String",
            "Required": True,
            "AllowedPattern": "[a-zA-Z0-9_]+[a-zA-Z0-9_@?#\s]*[a-zA-Z0-9_]+"
        },
        "Host": {
            "Type": "String",
            "Default": "%"
        },
        "Databases": {
            "Type": "List",
            "Required": True
        }
    }

    properties_schema = {
        "InstanceName": {
            "Type": "String",
            "Required": True,
            "MaxLength": "255"
        },

        "FlavorRef": {
            "Type": "String",
            "Required": True
        },

        "VolumeSize": {
            "Type": "Number",
            "MinValue": 1,
            "MaxValue": 150,
            "Required": True
        },

        "Databases": {
            'Type': 'List',
            'Required': False,
            'Schema': {
                'Type': 'Map',
                'Schema': database_schema
            }
        },

        "Users": {
            'Type': 'List',
            'Required': False,
            'Schema': {
                'Type': 'Map',
                'Schema': user_schema
            }
        },
    }

    attributes_schema = {
        "hostname": "Hostname of the instance",
        "href": "Api endpoint reference of the instance"
    }

    def __init__(self, name, json_snippet, stack):
        super(CloudDBInstance, self).__init__(name, json_snippet, stack)
        self.hostname = None
        self.href = None

    def handle_create(self):
        '''
        Create Rackspace Cloud DB Instance.
        '''
        logger.debug("Cloud DB instance handle_create called")
        self.sqlinstancename = self.properties['InstanceName']
        self.flavor = self.properties['FlavorRef']
        self.volume = self.properties['VolumeSize']
        self.databases = self.properties.get('Databases', None)
        self.users = self.properties.get('Users', None)

        # create db instance
        logger.info("Creating Cloud DB instance %s" % self.sqlinstancename)
        instance = self.cloud_db().create(self.sqlinstancename,
                                          flavor=self.flavor,
                                          volume=self.volume)
        if instance is not None:
            self.resource_id_set(instance.id)

        self.hostname = instance.hostname
        self.href = instance.links[0]['href']
        return instance

    def check_create_complete(self, instance):
        '''
        Check if cloud DB instance creation is complete.
        '''
        instance.get()  # get updated attributes
        if instance.status == 'ERROR':
            instance.delete()
            raise exception.Error("Cloud DB instance creation failed.")

        if instance.status != 'ACTIVE':
            return False

        logger.info("Cloud DB instance %s created (flavor:%s, volume:%s)" %
                    (self.sqlinstancename, self.flavor, self.volume))
        # create databases
        for database in self.databases:
            instance.create_database(
                database['Name'],
                character_set=database['Character_set'],
                collate=database['Collate'])
            logger.info("Database %s created on cloud DB instance %s" %
                        (database['Name'], self.sqlinstancename))

        # add users
        dbs = []
        for user in self.users:
            if user['Databases']:
                dbs = user['Databases']
            instance.create_user(user['Name'], user['Password'], dbs)
            logger.info("Cloud database user %s created successfully" %
                        (user['Name']))
        return True

    def handle_delete(self):
        '''
        Delete a Rackspace Cloud DB Instance.
        '''
        logger.debug("CloudDBInstance handle_delete called.")
        sqlinstancename = self.properties['InstanceName']
        if self.resource_id is None:
            logger.debug("resource_id is null and returning without delete.")
            raise exception.ResourceNotFound(resource_name=sqlinstancename,
                                             stack_name=self.stack.name)
        instances = self.cloud_db().delete(self.resource_id)
        self.resource_id = None

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(CloudDBInstance, self).validate()
        if res:
            return res

        # check validity of user and databases
        users = self.properties.get('Users', None)
        if not users:
            return

        databases = self.properties.get('Databases', None)
        if not databases:
            return {'Error':
                    'Databases property is required if Users property'
                    ' is provided'}

        for user in users:
            if not user['Databases']:
                return {'Error':
                        'Must provide access to at least one database for '
                        'user %s' % user['Name']}

            missing_db = [db_name for db_name in user['Databases']
                          if db_name not in [db['Name'] for db in databases]]
            if missing_db:
                return {'Error':
                        'Database %s specified for user does not exist in '
                        'databases.' % missing_db}
        return

    def _resolve_attribute(self, name):
        if name == 'hostname':
            return self.hostname
        elif name == 'href':
            return self.href


# pyrax module is required to work with Rackspace cloud database provider.
# If it is not installed, don't register clouddatabase provider
def resource_mapping():
    if rackspace_resource.PYRAX_INSTALLED:
        return {
            'Rackspace::Cloud::DBInstance': CloudDBInstance,
        }
    else:
        return {}
