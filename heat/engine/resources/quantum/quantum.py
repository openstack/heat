# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from heat.engine import resource

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class QuantumResource(resource.Resource):

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(QuantumResource, self).validate()
        if res:
            return res
        return self.validate_properties(self.properties)

    @staticmethod
    def validate_properties(properties):
        '''
        Validates to ensure nothing in value_specs overwrites
        any key that exists in the schema.

        Also ensures that shared and tenant_id is not specified
        in value_specs.
        '''
        if 'value_specs' in properties.keys():
            vs = properties.get('value_specs')
            banned_keys = set(['shared', 'tenant_id']).union(
                properties.keys())
            for k in banned_keys.intersection(vs.keys()):
                return '%s not allowed in value_specs' % k

    @staticmethod
    def prepare_properties(properties, name):
        '''
        Prepares the property values so that they can be passed directly to
        the Quantum call.

        Removes None values and value_specs, merges value_specs with the main
        values.
        '''
        props = dict((k, v) for k, v in properties.items()
                     if v is not None and k != 'value_specs')

        if 'name' in properties.keys():
            props.setdefault('name', name)

        if 'value_specs' in properties.keys():
            props.update(properties.get('value_specs'))

        return props

    @staticmethod
    def handle_get_attributes(name, key, attributes):
        '''
        Support method for responding to FnGetAtt
        '''
        if key == 'show':
            return attributes

        if key in attributes.keys():
            return attributes[key]

        raise exception.InvalidTemplateAttribute(resource=name, key=key)

    @staticmethod
    def is_built(attributes):
        if attributes['status'] == 'BUILD':
            return False
        if attributes['status'] in ('ACTIVE', 'DOWN'):
            return True
        else:
            raise exception.Error('%s resource[%s] status[%s]' %
                                  ('quantum reported unexpected',
                                   attributes['name'], attributes['status']))

    def FnGetRefId(self):
        return unicode(self.resource_id)
