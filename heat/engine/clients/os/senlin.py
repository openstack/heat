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

from openstack import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients.os import openstacksdk as sdk_plugin
from heat.engine import constraints

CLIENT_NAME = 'senlin'


class SenlinClientPlugin(sdk_plugin.OpenStackSDKPlugin):

    exceptions_module = exceptions

    def _create(self, version=None):
        client = super(SenlinClientPlugin, self)._create(version=version)
        return client.clustering

    def _get_additional_create_args(self, version):
        return {
            'clustering_api_version': version or '1'
        }

    def generate_spec(self, spec_type, spec_props):
        spec = {'properties': spec_props}
        spec['type'], spec['version'] = spec_type.split('-')
        return spec

    def check_action_status(self, action_id):
        action = self.client().get_action(action_id)
        if action.status == 'SUCCEEDED':
            return True
        elif action.status == 'FAILED':
            raise exception.ResourceInError(
                status_reason=action.status_reason,
                resource_status=action.status,
            )
        return False

    def get_profile_id(self, profile_name):
        profile = self.client().get_profile(profile_name)
        return profile.id

    def get_cluster_id(self, cluster_name):
        cluster = self.client().get_cluster(cluster_name)
        return cluster.id

    def get_policy_id(self, policy_name):
        policy = self.client().get_policy(policy_name)
        return policy.id

    def is_bad_request(self, ex):
        return (isinstance(ex, exceptions.HttpException) and
                ex.status_code == 400)

    def execute_actions(self, actions):
        all_executed = True
        for action in actions:
            if action['done']:
                continue
            all_executed = False
            if action['action_id'] is None:
                func = getattr(self.client(), action['func'])
                ret = func(**action['params'])
                if isinstance(ret, dict):
                    action['action_id'] = ret['action']
                else:
                    action['action_id'] = ret.location.split('/')[-1]
            else:
                ret = self.check_action_status(action['action_id'])
                action['done'] = ret
            # Execute these actions one by one.
            break
        return all_executed


class ProfileConstraint(constraints.BaseCustomConstraint):
    # If name is not unique, will raise exceptions.HttpException
    expected_exceptions = (exceptions.HttpException,)

    def validate_with_client(self, client, profile):
        client.client(CLIENT_NAME).get_profile(profile)


class ClusterConstraint(constraints.BaseCustomConstraint):
    #  If name is not unique, will raise exceptions.HttpException
    expected_exceptions = (exceptions.HttpException,)

    def validate_with_client(self, client, value):
        client.client(CLIENT_NAME).get_cluster(value)


class PolicyConstraint(constraints.BaseCustomConstraint):
    #  If name is not unique, will raise exceptions.HttpException
    expected_exceptions = (exceptions.HttpException,)

    def validate_with_client(self, client, value):
        client.client(CLIENT_NAME).get_policy(value)


class ProfileTypeConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.StackValidationFailed,)

    def validate_with_client(self, client, value):
        conn = client.client(CLIENT_NAME)
        type_list = conn.profile_types()
        names = [pt.name for pt in type_list]
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
        conn = client.client(CLIENT_NAME)
        type_list = conn.policy_types()
        names = [pt.name for pt in type_list]
        if value not in names:
            not_found_message = (
                _("Unable to find senlin policy type '%(pt)s', "
                  "available policy types are %(pts)s.") %
                {'pt': value, 'pts': names}
            )
            raise exception.StackValidationFailed(message=not_found_message)
