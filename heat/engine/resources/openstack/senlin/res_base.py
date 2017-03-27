#    Copyright 2015 IBM Corp.
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

from oslo_log import log as logging

from heat.engine import resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class BaseSenlinResource(resource.Resource):
    """A base class for Senlin resources."""

    support_status = support.SupportStatus(version='6.0.0')

    default_client_name = 'senlin'

    def _show_resource(self):
        method_name = 'get_' + self.entity
        try:
            client_method = getattr(self.client(), method_name)
            res_info = client_method(self.resource_id)
            return res_info.to_dict()
        except AttributeError as ex:
            LOG.warning("No method to get the resource: %s", ex)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        res_info = self._show_resource()
        return res_info.get(name)
