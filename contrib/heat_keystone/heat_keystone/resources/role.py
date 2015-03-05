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

from heat.common.i18n import _
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class KeystoneRole(resource.Resource):
    '''
    Heat Template Resource for Keystone Role.

    heat_template_version: 2013-05-23

    parameters:
      role_name:
        type: string
        description: Keystone role name

    resources:
      sample_role:
        type: OS::Keystone::Role
        properties:
          name: {get_param: role_name}
    '''

    support_status = support.SupportStatus(
        version='2015.1',
        message=_('Supported versions: keystone v3'))

    PROPERTIES = (
        NAME
    ) = (
        'name'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of keystone role.'),
            update_allowed=True
        )
    }

    def _create_role(self, role_name):
        return self.keystone().client.roles.create(name=role_name)

    def _delete_role(self, role_id):
        return self.keystone().client.roles.delete(role_id)

    def _update_role(self, role_id, new_name):
        return self.keystone().client.roles.update(
            role=role_id,
            name=new_name
        )

    def handle_create(self):
        role_name = (self.properties.get(self.NAME) or
                     self.physical_resource_name())

        role = self._create_role(role_name=role_name)

        self.resource_id_set(role.id)

    def handle_update(self, json_snippet=None, tmpl_diff=None, prop_diff=None):
        if prop_diff is None:
            return

        name = prop_diff.get(self.NAME) or self.physical_resource_name()
        self._update_role(
            role_id=self.resource_id,
            new_name=name
        )

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self._delete_role(role_id=self.resource_id)
            except Exception as ex:
                self.client_plugin('keystone').ignore_not_found(ex)


def resource_mapping():
    return {
        'OS::Keystone::Role': KeystoneRole
    }
