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
from heat.engine import resource


class NeutronResource(resource.Resource):

    default_client_name = 'neutron'

    def validate(self):
        """Validate any of the provided params."""
        res = super(NeutronResource, self).validate()
        if res:
            return res
        return self.validate_properties(self.properties)

    @staticmethod
    def validate_properties(properties):
        """Validate properties for the resource.

        Validates to ensure nothing in value_specs overwrites any key that
        exists in the schema.

        Also ensures that shared and tenant_id is not specified
        in value_specs.
        """
        if 'value_specs' in properties:
            banned_keys = set(['shared', 'tenant_id']).union(set(properties))
            found = banned_keys.intersection(set(properties['value_specs']))
            if found:
                return '%s not allowed in value_specs' % ', '.join(found)

    @staticmethod
    def prepare_properties(properties, name):
        """Prepares the property values for correct Neutron create call.

        Prepares the property values so that they can be passed directly to
        the Neutron create call.

        Removes None values and value_specs, merges value_specs with the main
        values.
        """
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)

        if 'name' in properties:
            props.setdefault('name', name)

        if 'value_specs' in props:
            NeutronResource.merge_value_specs(props)
        return props

    @staticmethod
    def merge_value_specs(props):
        value_spec_props = props.pop('value_specs')
        props.update(value_spec_props)

    def prepare_update_properties(self, prop_diff):
        """Prepares prop_diff values for correct neutron update call.

        1. Merges value_specs
        2. Defaults resource name to physical resource name if None
        """
        if 'value_specs' in prop_diff and prop_diff['value_specs']:
            NeutronResource.merge_value_specs(prop_diff)
        if 'name' in prop_diff and prop_diff['name'] is None:
            prop_diff['name'] = self.physical_resource_name()

    @staticmethod
    def is_built(attributes):
        status = attributes['status']
        if status == 'BUILD':
            return False
        if status in ('ACTIVE', 'DOWN'):
            return True
        elif status == 'ERROR':
            raise exception.ResourceInError(
                resource_status=status)
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('Resource is not built'))

    def _resolve_attribute(self, name):
        attributes = self._show_resource()
        return attributes[name]

    def get_reference_id(self):
        return self.resource_id

    def _not_found_in_call(self, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True
        else:
            return False

    def check_delete_complete(self, check):
        # NOTE(pshchelo): when longer check is needed, check is returned
        # as True, otherwise None is implicitly returned as check
        if not check:
            return True

        return self._not_found_in_call(self._show_resource)
