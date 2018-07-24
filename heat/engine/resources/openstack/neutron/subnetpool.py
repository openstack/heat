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
from heat.common import netutils
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class SubnetPool(neutron.NeutronResource):
    """A resource that implements neutron subnet pool.

    This resource can be used to create a subnet pool with a large block
    of addresses and create subnets from it.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'subnet_allocation'

    entity = 'subnetpool'

    PROPERTIES = (
        NAME, PREFIXES, ADDRESS_SCOPE, DEFAULT_QUOTA,
        DEFAULT_PREFIXLEN, MIN_PREFIXLEN, MAX_PREFIXLEN,
        IS_DEFAULT, TENANT_ID, SHARED, TAGS,
    ) = (
        'name', 'prefixes', 'address_scope', 'default_quota',
        'default_prefixlen', 'min_prefixlen', 'max_prefixlen',
        'is_default', 'tenant_id', 'shared', 'tags',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the subnet pool.'),
            update_allowed=True
        ),
        PREFIXES: properties.Schema(
            properties.Schema.LIST,
            _('List of subnet prefixes to assign.'),
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[
                    constraints.CustomConstraint('net_cidr'),
                ],
            ),
            constraints=[constraints.Length(min=1)],
            required=True,
            update_allowed=True,
        ),
        ADDRESS_SCOPE: properties.Schema(
            properties.Schema.STRING,
            _('An address scope ID to assign to the subnet pool.'),
            constraints=[
                constraints.CustomConstraint('neutron.address_scope')
            ],
            update_allowed=True,
        ),
        DEFAULT_QUOTA: properties.Schema(
            properties.Schema.INTEGER,
            _('A per-tenant quota on the prefix space that can be allocated '
              'from the subnet pool for tenant subnets.'),
            constraints=[constraints.Range(min=0)],
            update_allowed=True,
        ),
        DEFAULT_PREFIXLEN: properties.Schema(
            properties.Schema.INTEGER,
            _('The size of the prefix to allocate when the cidr or '
              'prefixlen attributes are not specified while creating '
              'a subnet.'),
            constraints=[constraints.Range(min=0)],
            update_allowed=True,
        ),
        MIN_PREFIXLEN: properties.Schema(
            properties.Schema.INTEGER,
            _('Smallest prefix size that can be allocated '
              'from the subnet pool.'),
            constraints=[constraints.Range(min=0)],
            update_allowed=True,
            ),
        MAX_PREFIXLEN: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum prefix size that can be allocated '
              'from the subnet pool.'),
            constraints=[constraints.Range(min=0)],
            update_allowed=True,
        ),
        IS_DEFAULT: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this is default IPv4/IPv6 subnet pool. '
              'There can only be one default subnet pool for each IP family. '
              'Note that the default policy setting restricts administrative '
              'users to set this to True.'),
            default=False,
            update_allowed=True,
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant who owns the subnet pool. Only '
              'administrative users can specify a tenant ID '
              'other than their own.')
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the subnet pool will be shared across all tenants. '
              'Note that the default policy setting restricts usage of this '
              'attribute to administrative users only.'),
            default=False,
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The tags to be added to the subnetpool.'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True,
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    def validate(self):
        super(SubnetPool, self).validate()
        self._validate_prefix_bounds()

    def _validate_prefix_bounds(self):
        min_prefixlen = self.properties[self.MIN_PREFIXLEN]
        default_prefixlen = self.properties[self.DEFAULT_PREFIXLEN]
        max_prefixlen = self.properties[self.MAX_PREFIXLEN]
        msg_fmt = _('Illegal prefix bounds: %(key1)s=%(value1)s, '
                    '%(key2)s=%(value2)s.')
        # min_prefixlen can not be greater than max_prefixlen
        if min_prefixlen and max_prefixlen and min_prefixlen > max_prefixlen:
            msg = msg_fmt % dict(key1=self.MAX_PREFIXLEN,
                                 value1=max_prefixlen,
                                 key2=self.MIN_PREFIXLEN,
                                 value2=min_prefixlen)
            raise exception.StackValidationFailed(message=msg)

        if default_prefixlen:
            # default_prefixlen can not be greater than max_prefixlen
            if max_prefixlen and default_prefixlen > max_prefixlen:
                msg = msg_fmt % dict(key1=self.MAX_PREFIXLEN,
                                     value1=max_prefixlen,
                                     key2=self.DEFAULT_PREFIXLEN,
                                     value2=default_prefixlen)
                raise exception.StackValidationFailed(message=msg)
            # min_prefixlen can not be greater than default_prefixlen
            if min_prefixlen and min_prefixlen > default_prefixlen:
                msg = msg_fmt % dict(key1=self.MIN_PREFIXLEN,
                                     value1=min_prefixlen,
                                     key2=self.DEFAULT_PREFIXLEN,
                                     value2=default_prefixlen)
                raise exception.StackValidationFailed(message=msg)

    def _validate_prefixes_for_update(self, prop_diff):
        old_prefixes = self.properties[self.PREFIXES]
        new_prefixes = prop_diff[self.PREFIXES]
        # check new_prefixes is a superset of old_prefixes
        if not netutils.is_prefix_subset(old_prefixes, new_prefixes):
            msg = (_('Property %(key)s updated value %(new)s should '
                     'be superset of existing value '
                     '%(old)s.') % dict(key=self.PREFIXES,
                                        new=sorted(new_prefixes),
                                        old=sorted(old_prefixes)))
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        if self.ADDRESS_SCOPE in props and props[self.ADDRESS_SCOPE]:
            client_plugin = self.client_plugin()
            scope_id = client_plugin.find_resourceid_by_name_or_id(
                client_plugin.RES_TYPE_ADDRESS_SCOPE,
                props.pop(self.ADDRESS_SCOPE))
            props['address_scope_id'] = scope_id
        tags = props.pop(self.TAGS, [])
        subnetpool = self.client().create_subnetpool(
            {'subnetpool': props})['subnetpool']
        self.resource_id_set(subnetpool['id'])

        if tags:
            self.set_tags(tags)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_subnetpool(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        # check that new prefixes are superset of existing prefixes
        if self.PREFIXES in prop_diff:
            self._validate_prefixes_for_update(prop_diff)
        if self.ADDRESS_SCOPE in prop_diff:
            if prop_diff[self.ADDRESS_SCOPE]:
                client_plugin = self.client_plugin()
                scope_id = client_plugin.find_resourceid_by_name_or_id(
                    self.client(),
                    client_plugin.RES_TYPE_ADDRESS_SCOPE,
                    prop_diff.pop(self.ADDRESS_SCOPE))
            else:
                scope_id = prop_diff.pop(self.ADDRESS_SCOPE)
            prop_diff['address_scope_id'] = scope_id
        if self.TAGS in prop_diff:
            tags = prop_diff.pop(self.TAGS)
            self.set_tags(tags)
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_subnetpool(
                self.resource_id, {'subnetpool': prop_diff})


def resource_mapping():
    return {
        'OS::Neutron::SubnetPool': SubnetPool,
    }
