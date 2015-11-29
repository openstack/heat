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
from troveclient.openstack.common.apiclient import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints


class TroveClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [DATABASE] = ['database']

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('trove', 'endpoint_type')
        args = {
            'service_type': self.DATABASE,
            'auth_url': con.auth_url or '',
            'proxy_token': con.auth_token,
            'username': None,
            'password': None,
            'cacert': self._get_client_option('trove', 'ca_file'),
            'insecure': self._get_client_option('trove', 'insecure'),
            'endpoint_type': endpoint_type
        }

        client = tc.Client('1.0', **args)
        management_url = self.url_for(service_type=self.DATABASE,
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

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
                if len(allowed_versions) > 1:
                    msg = _("Multiple active datastore versions exist for "
                            "datastore type %(dstype)s. "
                            "Explicit datastore version must be provided. "
                            "Allowed versions are %(allowed)s.") % {
                                'dstype': datastore_type,
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

    def get_flavor_id(self, flavor):
        """Get the ID for the specified flavor name.

        If the specified value is flavor id, just return it.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        :raises: exception.EntityNotFound
        """
        flavor_id = None
        flavor_list = self.client().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id
                break
            if o.id == flavor:
                flavor_id = o.id
                break
        if flavor_id is None:
            raise exception.EntityNotFound(entity='Flavor', name=flavor)
        return flavor_id


class FlavorConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.EntityNotFound,)

    def validate_with_client(self, client, flavor):
        client.client_plugin('trove').get_flavor_id(flavor)
