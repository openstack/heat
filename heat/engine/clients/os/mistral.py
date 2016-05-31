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

from mistralclient.api import base as mistral_base
from mistralclient.api import client as mistral_client

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'mistral'


class MistralClientPlugin(client_plugin.ClientPlugin):

    service_types = [WORKFLOW_V2] = ['workflowv2']

    def _create(self):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.WORKFLOW_V2,
                                endpoint_type=endpoint_type)

        args = {
            'mistral_url': endpoint,
            'auth_token': self.auth_token
        }

        client = mistral_client.client(**args)
        return client

    def is_not_found(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 404)

    def is_over_limit(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 413)

    def is_conflict(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 409)

    def get_workflow_by_identifier(self, workflow_identifier):
        try:
            return self.client().workflows.get(
                workflow_identifier)
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Workflow",
                    name=workflow_identifier)
            raise


class WorkflowConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_workflow_by_identifier'
    expected_exceptions = (exception.EntityNotFound,)
