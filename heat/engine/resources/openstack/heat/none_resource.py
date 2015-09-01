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

import six
import uuid

from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class NoneResource(resource.Resource):
    '''
    A resource which enables easily disabling certain resources via the
    resource_registry.  It does nothing, but can effectively stub out
    any other resource because it will accept any properties and return
    any attribute (as None).  Note this resource always does nothing
    on update (e.g it is not replaced even if a change to the stubbed
    resource properties would cause replacement).
    '''

    support_status = support.SupportStatus(version='5.0.0')
    properties_schema = {}
    attributes_schema = {}

    def _needs_update(self, after, before, after_props, before_props,
                      prev_resource, check_init_complete=True):
        return False

    def reparse(self):
        self.properties = properties.Properties(schema={}, data={})

    def handle_create(self):
        self.resource_id_set(six.text_type(uuid.uuid4()))

    def validate(self):
        pass

    def FnGetAtt(self, key, *path):
        return None


def resource_mapping():
    return {
        'OS::Heat::None': NoneResource,
    }
