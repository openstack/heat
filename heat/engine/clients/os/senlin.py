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
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints

from senlinclient import client
from senlinclient.common import exc

CLIENT_NAME = 'senlin'


class SenlinClientPlugin(client_plugin.ClientPlugin):

    service_types = [CLUSTERING] = ['clustering']
    VERSION = '1'

    def _create(self):
        con = self.context
        args = {
            'auth_url': con.auth_url,
            'project_id': con.tenant_id,
            'token': self.auth_token,
            'user_id': con.user_id,
            'auth_plugin': 'token',
        }
        return client.Client(self.VERSION, **args)

    def generate_spec(self, spec_type, spec_props):
        spec = {'properties': spec_props}
        spec['type'], spec['version'] = spec_type.split('-')
        return spec

    def is_not_found(self, ex):
        return isinstance(ex, exc.sdkexc.ResourceNotFound)

    def is_bad_request(self, ex):
        return (isinstance(ex, exc.sdkexc.HttpException) and
                ex.http_status == 400)


class ProfileConstraint(constraints.BaseCustomConstraint):
    # If name is not unique, will raise exc.sdkexc.HttpException
    expected_exceptions = (exc.sdkexc.HttpException,)

    def validate_with_client(self, client, profile):
        client.client(CLIENT_NAME).get_profile(profile)


class ClusterConstraint(constraints.BaseCustomConstraint):
    #  If name is not unique, will raise exc.sdkexc.HttpException
    expected_exceptions = (exc.sdkexc.HttpException,)

    def validate_with_client(self, client, value):
        client.client(CLIENT_NAME).get_cluster(value)


class ProfileTypeConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.StackValidationFailed,)

    def validate_with_client(self, client, value):
        senlin_client = client.client(CLIENT_NAME)
        type_list = senlin_client.profile_types()
        names = [pt['name'] for pt in type_list]
        if value not in names:
            not_found_message = (
                _("Unable to find senlin profile type '%(pt)s', "
                  "available profile types are %(pts)s.") %
                {'pt': value, 'pts': names}
            )
            raise exception.StackValidationFailed(message=not_found_message)


class PolicyTypeConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.StackValidationFailed,)

    def validate_with_client(self, client, value):
        senlin_client = client.client(CLIENT_NAME)
        type_list = senlin_client.policy_types()
        names = [pt['name'] for pt in type_list]
        if value not in names:
            not_found_message = (
                _("Unable to find senlin policy type '%(pt)s', "
                  "available policy types are %(pts)s.") %
                {'pt': value, 'pts': names}
            )
            raise exception.StackValidationFailed(message=not_found_message)
