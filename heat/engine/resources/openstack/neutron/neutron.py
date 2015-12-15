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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import resource


class NeutronResource(resource.Resource):

    default_client_name = 'neutron'

    # Subclasses provide a list of properties which, although
    # update_allowed in the schema, should be excluded from the
    # call to neutron, because they are handled in _needs_update
    update_exclude_properties = []

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
        if 'value_specs' in six.iterkeys(properties):
            vs = properties.get('value_specs')
            banned_keys = set(['shared', 'tenant_id']).union(
                six.iterkeys(properties))
            for k in banned_keys.intersection(six.iterkeys(vs)):
                return '%s not allowed in value_specs' % k

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

        if 'name' in six.iterkeys(properties):
            props.setdefault('name', name)

        if 'value_specs' in props:
            NeutronResource.merge_value_specs(props)
        return props

    @staticmethod
    def merge_value_specs(props):
        value_spec_props = props.pop('value_specs')
        props.update(value_spec_props)

    def prepare_update_properties(self, definition):
        """Prepares the property values for correct Neutron update call.

        Prepares the property values so that they can be passed directly to
        the Neutron update call.

        Removes any properties which are not update_allowed, then processes
        as for prepare_properties.
        """
        p = definition.properties(self.properties_schema, self.context)
        update_props = dict((k, v) for k, v in p.items()
                            if p.props.get(k).schema.update_allowed and
                            k not in self.update_exclude_properties)

        props = self.prepare_properties(
            update_props,
            self.physical_resource_name())
        return props

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
        return six.text_type(self.resource_id)

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
