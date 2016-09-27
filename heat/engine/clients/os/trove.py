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

from troveclient import client as tc
from troveclient import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'trove'


class TroveClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [DATABASE] = ['database']

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'endpoint_type': endpoint_type,
            'service_type': self.DATABASE,
            'session': con.keystone_session,
            'region_name': self._get_region_name()
        }

        client = tc.Client('1.0', **args)
        return client

    def validate_datastore(self, datastore_type, datastore_version,
                           ds_type_key, ds_version_key):
        if datastore_type:
            # get current active versions
            allowed_versions = self.client().datastore_versions.list(
                datastore_type)
            allowed_version_names = [v.name for v in allowed_versions]
            if datastore_version:
                if datastore_version not in allowed_version_names:
                    msg = _("Datastore version %(dsversion)s "
                            "for datastore type %(dstype)s is not valid. "
                            "Allowed versions are %(allowed)s.") % {
                                'dstype': datastore_type,
                                'dsversion': datastore_version,
                                'allowed': ', '.join(allowed_version_names)}
                    raise exception.StackValidationFailed(message=msg)
        else:
            if datastore_version:
                msg = _("Not allowed - %(dsver)s without %(dstype)s.") % {
                    'dsver': ds_version_key,
                    'dstype': ds_type_key}
                raise exception.StackValidationFailed(message=msg)

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def find_flavor_by_name_or_id(self, flavor):
        """Find the specified flavor by name or id.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        """
        try:
            return self.client().flavors.get(flavor).id
        except exceptions.NotFound:
            return self.client().flavors.find(name=flavor).id


class FlavorConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NotFound,)

    resource_client_name = CLIENT_NAME
    resource_getter_name = 'find_flavor_by_name_or_id'
