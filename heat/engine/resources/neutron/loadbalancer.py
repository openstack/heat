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
from heat.db.sqlalchemy import api as db_api
from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import nova_utils
from heat.engine.resources.neutron import neutron

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException


class HealthMonitor(neutron.NeutronResource):
    """
    A resource for managing health monitors for load balancers in Neutron.
    """

    properties_schema = {
        'delay': {
            'Type': 'Integer', 'Required': True,
            'Description': _('The minimum time in seconds between regular '
                             'connections of the member.')},
        'type': {
            'Type': 'String', 'Required': True,
            'AllowedValues': ['PING', 'TCP', 'HTTP', 'HTTPS'],
            'Description': _('One of predefined health monitor types.')},
        'max_retries': {
            'Type': 'Integer', 'Required': True,
            'Description': _('Number of permissible connection failures before'
                             ' changing the member status to INACTIVE.')},
        'timeout': {
            'Type': 'Integer', 'Required': True,
            'Description': _('Maximum number of seconds for a monitor to '
                             'wait for a connection to be established before '
                             'it times out.')},
        'admin_state_up': {
            'Default': True, 'Type': 'Boolean',
            'Description': _('The administrative state of the health '
                             'monitor.')},
        'http_method': {
            'Type': 'String',
            'Description': _('The HTTP method used for requests by the '
                             'monitor of type HTTP.')},
        'expected_codes': {
            'Type': 'String',
            'Description': _('The list of HTTP status codes expected in '
                             'response from the member to declare it '
                             'healthy.')},
        'url_path': {
            'Type': 'String',
            'Description': _('The HTTP path used in the HTTP request used '
                             'by the monitor to test a member health.')},
    }

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('delay', 'max_retries', 'timeout',
                                 'admin_state_up', 'http_method',
                                 'expected_codes', 'url_path')

    attributes_schema = {
        'admin_state_up': _('The administrative state of this health '
                            'monitor.'),
        'delay': _('The minimum time in seconds between regular connections '
                   'of the member.'),
        'expected_codes': _('The list of HTTP status codes expected in '
                            'response from the member to declare it healthy.'),
        'http_method': _('The HTTP method used for requests by the monitor of '
                         'type HTTP.'),
        'max_retries': _('Number of permissible connection failures before '
                         'changing the member status to INACTIVE.'),
        'timeout': _('Maximum number of seconds for a monitor to wait for a '
                     'connection to be established before it times out.'),
        'type': _('One of predefined health monitor types.'),
        'url_path': _('The HTTP path used in the HTTP request used by the '
                      'monitor to test a member health.'),
        'tenant_id': _('Tenant owning the health monitor.'),
        'show': _('All attributes.'),
    }

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        health_monitor = self.neutron().create_health_monitor(
            {'health_monitor': properties})['health_monitor']
        self.resource_id_set(health_monitor['id'])

    def _show_resource(self):
        return self.neutron().show_health_monitor(
            self.resource_id)['health_monitor']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_health_monitor(
                self.resource_id, {'health_monitor': prop_diff})

    def handle_delete(self):
        try:
            self.neutron().delete_health_monitor(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


class Pool(neutron.NeutronResource):
    """
    A resource for managing load balancer pools in Neutron.
    """

    vip_schema = {
        'name': {
            'Type': 'String',
            'Description': _('Name of the vip.')},
        'description': {
            'Type': 'String',
            'Description': _('Description of the vip.')},
        'address': {
            'Type': 'String',
            'Description': _('IP address of the vip.')},
        'connection_limit': {
            'Type': 'Integer',
            'Description': _('The maximum number of connections per second '
                             'allowed for the vip.')},
        'protocol_port': {
            'Type': 'Integer', 'Required': True,
            'Description': _('TCP port on which to listen for client traffic '
                             'that is associated with the vip address.')},
        'admin_state_up': {
            'Default': True, 'Type': 'Boolean',
            'Description': _('The administrative state of this vip.')}
    }

    properties_schema = {
        'protocol': {
            'Type': 'String', 'Required': True,
            'AllowedValues': ['TCP', 'HTTP', 'HTTPS'],
            'Description': _('Protocol for balancing.')},
        'subnet_id': {
            'Type': 'String', 'Required': True,
            'Description': _('The subnet on which the members of the pool '
                             'will be located.')},
        'lb_method': {
            'Type': 'String', 'Required': True,
            'AllowedValues': ['ROUND_ROBIN', 'LEAST_CONNECTIONS',
                              'SOURCE_IP'],
            'Description': _('The algorithm used to distribute load between '
                             'the members of the pool.')},
        'name': {
            'Type': 'String',
            'Description': _('Name of the pool.')},
        'description': {
            'Type': 'String',
            'Description': _('Description of the pool.')},
        'admin_state_up': {
            'Default': True, 'Type': 'Boolean',
            'Description': _('The administrative state of this pool.')},
        'vip': {
            'Type': 'Map', 'Schema': vip_schema, 'Required': True,
            'Description': _('IP address and port of the pool.')},
        'monitors': {
            'Type': 'List',
            'Description': _('List of health monitors associated with the '
                             'pool.')},
    }

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('description', 'admin_state_up', 'lb_method',
                                 'monitors')

    attributes_schema = {
        'admin_state_up': _('The administrative state of this pool.'),
        'name': _('Name of the pool.'),
        'protocol': _('Protocol to balance.'),
        'subnet_id': _('The subnet on which the members of the pool '
                       'will be located.'),
        'lb_method': _('The algorithm used to distribute load between the '
                       'members of the pool.'),
        'description': _('Description of the pool.'),
        'tenant_id': _('Tenant owning the pool.'),
        'vip': _('Vip associated with the pool.'),
    }

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        vip_properties = properties.pop('vip')
        monitors = properties.pop('monitors', [])
        client = self.neutron()
        pool = client.create_pool({'pool': properties})['pool']
        self.resource_id_set(pool['id'])

        for monitor in monitors:
            client.associate_health_monitor(
                pool['id'], {'health_monitor': {'id': monitor}})

        vip_arguments = self.prepare_properties(
            vip_properties,
            '%s.vip' % (self.name,))
        vip_arguments['protocol'] = self.properties['protocol']
        vip_arguments['subnet_id'] = self.properties['subnet_id']
        vip_arguments['pool_id'] = pool['id']
        vip = client.create_vip({'vip': vip_arguments})['vip']

        self.metadata = {'vip': vip['id']}

    def _show_resource(self):
        return self.neutron().show_pool(self.resource_id)['pool']

    def check_create_complete(self, data):
        attributes = self._show_resource()
        if attributes['status'] == 'PENDING_CREATE':
            return False
        elif attributes['status'] == 'ACTIVE':
            vip_attributes = self.neutron().show_vip(
                self.metadata['vip'])['vip']
            if vip_attributes['status'] == 'PENDING_CREATE':
                return False
            elif vip_attributes['status'] == 'ACTIVE':
                return True
            raise exception.Error(
                'neutron reported unexpected vip resource[%s] status[%s]' %
                (vip_attributes['name'], vip_attributes['status']))
        raise exception.Error(
            'neutron report unexpected pool resource[%s] status[%s]' %
            (attributes['name'], attributes['status']))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            client = self.neutron()
            monitors = set(prop_diff.pop('monitors', []))
            if monitors:
                old_monitors = set(self.t['Properties']['monitors'])
                for monitor in old_monitors - monitors:
                    client.disassociate_health_monitor(
                        self.resource_id, {'health_monitor': {'id': monitor}})
                for monitor in monitors - old_monitors:
                    client.associate_health_monitor(
                        self.resource_id, {'health_monitor': {'id': monitor}})

            if prop_diff:
                client.update_pool(self.resource_id, {'pool': prop_diff})

    def _resolve_attribute(self, name):
        if name == 'vip':
            return self.neutron().show_vip(self.metadata['vip'])['vip']
        return super(Pool, self)._resolve_attribute(name)

    def _confirm_vip_delete(self):
        client = self.neutron()
        while True:
            try:
                yield
                client.show_vip(self.metadata['vip'])
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise ex
                break
        self._delete_pool()

    def _delete_pool(self):
        try:
            self.neutron().delete_pool(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()

    def handle_delete(self):
        if self.metadata:
            try:
                self.neutron().delete_vip(self.metadata['vip'])
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise ex
                self._delete_pool()
            else:
                return scheduler.TaskRunner(self._confirm_vip_delete)()
        else:
            self._delete_pool()


class LoadBalancer(resource.Resource):
    """
    A resource to link a neutron pool with servers.
    """

    properties_schema = {
        'pool_id': {
            'Type': 'String', 'Required': True,
            'Description': _('The ID of the load balancing pool.')},
        'protocol_port': {
            'Type': 'Integer', 'Required': True,
            'Description': _('Port number on which the servers are '
                             'running on the members.')},
        'members': {
            'Type': 'List',
            'Description': _('The list of Nova server IDs load balanced.')},
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('members', 'pool_id',)

    def handle_create(self):
        pool = self.properties['pool_id']
        client = self.neutron()
        nova_client = self.nova()
        protocol_port = self.properties['protocol_port']
        for member in self.properties.get('members', []):
            address = nova_utils.server_to_ipaddress(nova_client, member)
            lb_member = client.create_member({
                'member': {
                    'pool_id': pool,
                    'address': address,
                    'protocol_port': protocol_port}})['member']
            db_api.resource_data_set(self, member, lb_member['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if 'members' in prop_diff:
            members = set(prop_diff['members'])
            old_members = set(self.t['Properties'].get('members', []))
            client = self.neutron()
            for member in old_members - members:
                member_id = db_api.resource_data_get(self, member)
                try:
                    client.delete_member(member_id)
                except NeutronClientException as ex:
                    if ex.status_code != 404:
                        raise ex
                db_api.resource_data_delete(self, member)
            pool = self.properties['pool_id']
            nova_client = self.nova()
            protocol_port = self.properties['protocol_port']
            for member in members - old_members:
                address = nova_utils.server_to_ipaddress(nova_client, member)
                lb_member = client.create_member({
                    'member': {
                        'pool_id': pool,
                        'address': address,
                        'protocol_port': protocol_port}})['member']
                db_api.resource_data_set(self, member, lb_member['id'])

    def handle_delete(self):
        client = self.neutron()
        for member in self.properties.get('members', []):
            member_id = db_api.resource_data_get(self, member)
            try:
                client.delete_member(member_id)
            except NeutronClientException as ex:
                if ex.status_code != 404:
                    raise ex
            db_api.resource_data_delete(self, member)


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::HealthMonitor': HealthMonitor,
        'OS::Neutron::Pool': Pool,
        'OS::Neutron::LoadBalancer': LoadBalancer,
    }
