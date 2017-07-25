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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import resource

LOG = logging.getLogger(__name__)


class NeutronResource(resource.Resource):

    default_client_name = 'neutron'

    res_info_key = None

    def get_resource_plural(self):
        """Return the plural of resource type.

        The default implementation is to return self.entity + 's',
        the rule is not appropriate for some special resources,
        e.g. qos_policy, this method should be overridden by the
        special resources if needed.
        """
        if not self.entity:
            return
        return self.entity + 's'

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

    def _store_config_default_properties(self, attrs):
        """A method for storing properties, which defaults stored in config.

        A method allows to store properties default values, which cannot be
        defined in schema in case of specifying in config file.
        """
        if 'port_security_enabled' in attrs:
            self.data_set('port_security_enabled',
                          attrs['port_security_enabled'])

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
        elif status in ('ERROR', 'DEGRADED'):
            raise exception.ResourceInError(
                resource_status=status)
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('Resource is not built'))

    def _res_get_args(self):
        return [self.resource_id]

    def _show_resource(self):
        try:
            method_name = 'show_' + self.entity
            client_method = getattr(self.client(), method_name)
            args = self._res_get_args()
            res_info = client_method(*args)
            key = self.res_info_key if self.res_info_key else self.entity
            return res_info[key]
        except AttributeError as ex:
            LOG.warning("Resolving 'show' attribute has failed : %s", ex)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        attributes = self._show_resource()
        return attributes[name]

    def needs_replace_failed(self):
        if not self.resource_id:
            return True

        with self.client_plugin().ignore_not_found:
            res_attrs = self._show_resource()
            if 'status' in res_attrs:
                return res_attrs['status'] == 'ERROR'
            return False

        return True

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

        if not self._not_found_in_call(self._show_resource):
            raise exception.PhysicalResourceExists(
                name=self.physical_resource_name_or_FnGetRefId())
        return True

    def set_tags(self, tags):
        resource_plural = self.get_resource_plural()
        if resource_plural:
            tags = tags or []
            body = {'tags': tags}
            self.client().replace_tag(resource_plural,
                                      self.resource_id,
                                      body)

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(NeutronResource, self).parse_live_resource_data(
            resource_properties, resource_data)

        if 'value_specs' in self.properties.keys():
            result.update({self.VALUE_SPECS: {}})
            for key in self.properties.get(self.VALUE_SPECS):
                if key in resource_data:
                    result[self.VALUE_SPECS][key] = resource_data.get(key)

        # We already get real `port_security_enabled` from
        # super().parse_live_resource_data above, so just check and remove
        # if that's same value as old port value.
        if 'port_security_enabled' in self.properties.keys():
            old_port = bool(self.data().get(self.PORT_SECURITY_ENABLED))
            new_port = resource_data.get(self.PORT_SECURITY_ENABLED)
            if old_port == new_port:
                del result[self.PORT_SECURITY_ENABLED]

        return result
