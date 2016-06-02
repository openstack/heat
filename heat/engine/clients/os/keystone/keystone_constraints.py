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
from heat.engine import constraints

CLIENT_NAME = 'keystone'


class KeystoneBaseConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME
    entity = None

    def validate_with_client(self, client, resource_id):
        # when user specify empty value in template, do not get the
        # responding resource from backend, otherwise an error will happen
        if resource_id == '':
            raise exception.EntityNotFound(entity=self.entity,
                                           name=resource_id)

        super(KeystoneBaseConstraint, self).validate_with_client(client,
                                                                 resource_id)


class KeystoneRoleConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_role_id'
    entity = 'KeystoneRole'


class KeystoneDomainConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_domain_id'
    entity = 'KeystoneDomain'


class KeystoneProjectConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_project_id'
    entity = 'KeystoneProject'


class KeystoneGroupConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_group_id'
    entity = 'KeystoneGroup'


class KeystoneServiceConstraint(KeystoneBaseConstraint):

    expected_exceptions = (exception.EntityNotFound,
                           exception.KeystoneServiceNameConflict,)
    resource_getter_name = 'get_service_id'
    entity = 'KeystoneService'


class KeystoneUserConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_user_id'
    entity = 'KeystoneUser'


class KeystoneRegionConstraint(KeystoneBaseConstraint):

    resource_getter_name = 'get_region_id'
    entity = 'KeystoneRegion'
