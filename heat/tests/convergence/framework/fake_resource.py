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
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class TestResource(resource.Resource):

    PROPERTIES = (
        A, B, C, CA, rA, rB
    ) = (
        'a', 'b', 'c', 'ca', '!a', '!b'
    )

    ATTRIBUTES = (
        A, rA
    ) = (
        'a', '!a'
    )

    properties_schema = {
        A: properties.Schema(
            properties.Schema.STRING,
            _('Fake property a.'),
            default='a',
            update_allowed=True
        ),
        B: properties.Schema(
            properties.Schema.STRING,
            _('Fake property b.'),
            default='b',
            update_allowed=True
        ),
        C: properties.Schema(
            properties.Schema.STRING,
            _('Fake property c.'),
            update_allowed=True,
            default='c'
        ),
        CA: properties.Schema(
            properties.Schema.STRING,
            _('Fake property ca.'),
            update_allowed=True,
            default='ca'
        ),
        rA: properties.Schema(
            properties.Schema.STRING,
            _('Fake property !a.'),
            update_allowed=True,
            default='!a'
        ),
        rB: properties.Schema(
            properties.Schema.STRING,
            _('Fake property !c.'),
            update_allowed=True,
            default='!b'
        ),
    }

    attributes_schema = {
        A: attributes.Schema(
            _('Fake attribute a.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
        rA: attributes.Schema(
            _('Fake attribute !a.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    def handle_create(self):
        LOG.info('Creating resource %s with properties %s',
                 self.name, dict(self.properties))
        for prop in self.properties.props.keys():
            self.data_set(prop, self.properties.get(prop), redact=False)

        self.resource_id_set(self.physical_resource_name())

    def handle_update(self, json_snippet=None, tmpl_diff=None, prop_diff=None):
        LOG.info('Updating resource %s with prop_diff %s',
                 self.name, prop_diff)
        for prop in prop_diff:
            if '!' in prop:
                raise resource.UpdateReplace(self.name)
            self.data_set(prop, prop_diff.get(prop), redact=False)

    def _resolve_attribute(self, name):
        if name in self.attributes:
            return self.data().get(name)
