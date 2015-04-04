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

import eventlet

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class TestResource(resource.Resource):
    '''
    A resource which stores the string value that was provided.

    This resource is to be used only for testing.
    It has control knobs such as 'update_replace', 'fail', 'wait_secs'

    '''

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        VALUE, UPDATE_REPLACE, FAIL, WAIT_SECS
    ) = (
        'value', 'update_replace', 'fail', 'wait_secs'
    )

    ATTRIBUTES = (
        OUTPUT,
    ) = (
        'output',
    )

    properties_schema = {
        VALUE: properties.Schema(
            properties.Schema.STRING,
            _('The input string to be stored.'),
            default='test_string',
            update_allowed=True
        ),
        FAIL: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Value which can be set to fail the resource operation '
              'to test failure scenarios.'),
            update_allowed=True,
            default=False
        ),
        UPDATE_REPLACE: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Value which can be set to trigger update replace for '
              'the particular resource'),
            update_allowed=True,
            default=False
        ),
        WAIT_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Value which can be set for resource to wait after an action '
              'is performed.'),
            update_allowed=True,
            default=0,
        ),
    }

    attributes_schema = {
        OUTPUT: attributes.Schema(
            _('The string that was stored. This value is '
              'also available by referencing the resource.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    def handle_create(self):
        value = self.properties.get(self.VALUE)
        fail_prop = self.properties.get(self.FAIL)
        sleep_secs = self.properties.get(self.WAIT_SECS)

        self.data_set('value', value, redact=False)
        self.resource_id_set(self.physical_resource_name())

        # sleep for specified time
        if sleep_secs:
            LOG.debug("Resource %s sleeping for %s seconds",
                      self.name, sleep_secs)
            eventlet.sleep(sleep_secs)

        # emulate failure
        if fail_prop:
            raise Exception("Test Resource failed %s", self.name)

    def handle_update(self, json_snippet=None, tmpl_diff=None, prop_diff=None):
        value = prop_diff.get(self.VALUE)
        new_prop = json_snippet._properties
        if value:
            update_replace = new_prop.get(self.UPDATE_REPLACE, False)
            if update_replace:
                raise resource.UpdateReplace(self.name)
            else:
                fail_prop = new_prop.get(self.FAIL, False)
                sleep_secs = new_prop.get(self.WAIT_SECS, 0)
                # emulate failure
                if fail_prop:
                    raise Exception("Test Resource failed %s", self.name)
                # update in place
                self.data_set('value', value, redact=False)

                if sleep_secs:
                    LOG.debug("Update of Resource %s sleeping for %s seconds",
                              self.name, sleep_secs)
                    eventlet.sleep(sleep_secs)

    def _resolve_attribute(self, name):
        if name == self.OUTPUT:
            return self.data().get('value')


def resource_mapping():
    return {
        'OS::Heat::TestResource': TestResource,
    }
