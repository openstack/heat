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

import datetime
import eventlet
from oslo_utils import timeutils
import six

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class TestResource(resource.Resource):
    """A resource which stores the string value that was provided.

    This resource is to be used only for testing.
    It has control knobs such as 'update_replace', 'fail', 'wait_secs'.
    """

    support_status = support.SupportStatus(version='5.0.0')

    ACTION_TIMES = (
        CREATE_WAIT_SECS, UPDATE_WAIT_SECS, DELETE_WAIT_SECS
    ) = (
        'create', 'update', 'delete')

    PROPERTIES = (
        VALUE, UPDATE_REPLACE, FAIL,
        CLIENT_NAME, ENTITY_NAME,
        WAIT_SECS, ACTION_WAIT_SECS, ATTR_WAIT_SECS,
        CONSTRAINT_PROP_SECS, UPDATE_REPLACE_VALUE,
    ) = (
        'value', 'update_replace', 'fail',
        'client_name', 'entity_name',
        'wait_secs', 'action_wait_secs', 'attr_wait_secs',
        'constraint_prop_secs', 'update_replace_value',
    )

    ATTRIBUTES = (
        OUTPUT,
    ) = (
        'output',
    )

    properties_schema = {
        CONSTRAINT_PROP_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Number value for delay during resolve constraint.'),
            default=0,
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('test_constr')
            ],
            support_status=support.SupportStatus(version='6.0.0')
        ),
        ATTR_WAIT_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Number value for timeout during resolving output value.'),
            default=0,
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        ),
        VALUE: properties.Schema(
            properties.Schema.STRING,
            _('The input string to be stored.'),
            default='test_string',
            update_allowed=True
        ),
        UPDATE_REPLACE_VALUE: properties.Schema(
            properties.Schema.STRING,
            _('Some value that can be stored but can not be updated.'),
            support_status=support.SupportStatus(version='7.0.0')
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
              'the particular resource.'),
            update_allowed=True,
            default=False
        ),
        WAIT_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Seconds to wait after an action (-1 is infinite).'),
            update_allowed=True,
            default=0,
        ),
        ACTION_WAIT_SECS: properties.Schema(
            properties.Schema.MAP,
            _('Options for simulating waiting.'),
            update_allowed=True,
            schema={
                CREATE_WAIT_SECS: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Seconds to wait after a create. '
                      'Defaults to the global wait_secs.'),
                    update_allowed=True,
                ),
                UPDATE_WAIT_SECS: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Seconds to wait after an update. '
                      'Defaults to the global wait_secs.'),
                    update_allowed=True,
                ),
                DELETE_WAIT_SECS: properties.Schema(
                    properties.Schema.NUMBER,
                    _('Seconds to wait after a delete. '
                      'Defaults to the global wait_secs.'),
                    update_allowed=True,
                ),
            }
        ),
        CLIENT_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Client to poll.'),
            default='',
            update_allowed=True
        ),
        ENTITY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Client entity to poll.'),
            default='',
            update_allowed=True
        ),
    }

    attributes_schema = {
        OUTPUT: attributes.Schema(
            _('The string that was stored. This value is '
              'also available by referencing the resource.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    def _wait_secs(self):
        secs = None
        if self.properties[self.ACTION_WAIT_SECS]:
            secs = self.properties[self.ACTION_WAIT_SECS][self.action.lower()]
        if secs is None:
            secs = self.properties[self.WAIT_SECS]
        LOG.info('%(name)s wait_secs:%(wait)s, action:%(action)s',
                 {'name': self.name,
                  'wait': secs,
                  'action': self.action.lower()})
        return secs

    def handle_create(self):
        fail_prop = self.properties.get(self.FAIL)
        if not fail_prop:
            value = self.properties.get(self.VALUE)
            self.data_set('value', value, redact=False)
            self.resource_id_set(self.physical_resource_name())

        return timeutils.utcnow(), self._wait_secs()

    def needs_replace_with_prop_diff(self, changed_properties_set,
                                     after_props, before_props):
        if self.VALUE in changed_properties_set:
            return after_props[self.UPDATE_REPLACE]

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        value = prop_diff.get(self.VALUE)
        if value:
            # emulate failure
            fail_prop = self.properties[self.FAIL]
            if not fail_prop:
                # update in place
                self.data_set('value', value, redact=False)
            return timeutils.utcnow(), self._wait_secs()
        return timeutils.utcnow(), 0

    def handle_delete(self):
        return timeutils.utcnow(), self._wait_secs()

    def check_create_complete(self, cookie):
        return self._check_status_complete(*cookie)

    def check_update_complete(self, cookie):
        return self._check_status_complete(*cookie)

    def check_delete_complete(self, cookie):
        return self._check_status_complete(*cookie)

    def _check_status_complete(self, started_at, wait_secs):
        def simulated_effort():
            client_name = self.properties[self.CLIENT_NAME]
            self.entity = self.properties[self.ENTITY_NAME]
            if client_name and self.entity:
                # Allow the user to set the value to a real resource id.
                entity_id = self.data().get('value') or self.resource_id
                try:
                    obj = getattr(self.client(name=client_name), self.entity)
                    obj.get(entity_id)
                except Exception as exc:
                    LOG.debug('%s.%s(%s) %s' % (client_name, self.entity,
                                                entity_id, six.text_type(exc)))
            else:
                # just sleep some more
                eventlet.sleep(1)

        if isinstance(started_at, six.string_types):
            started_at = timeutils.parse_isotime(started_at)

        started_at = timeutils.normalize_time(started_at)
        waited = timeutils.utcnow() - started_at
        LOG.info("Resource %(name)s waited %(waited)s/%(sec)s seconds",
                 {'name': self.name,
                  'waited': waited,
                  'sec': wait_secs})

        # wait_secs < 0 is an infinite wait time.
        if wait_secs >= 0 and waited > datetime.timedelta(seconds=wait_secs):
            fail_prop = self.properties[self.FAIL]
            if fail_prop and self.action != self.DELETE:
                raise ValueError("Test Resource failed %s" % self.name)
            return True

        simulated_effort()
        return False

    def _resolve_attribute(self, name):
        eventlet.sleep(self.properties[self.ATTR_WAIT_SECS])
        if name == self.OUTPUT:
            return self.data().get('value')


def resource_mapping():
    return {
        'OS::Heat::TestResource': TestResource,
    }
