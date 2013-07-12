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
try:
    from pyrax.exceptions import NotFound
except ImportError:
    #Setup fake exception for testing without pyrax
    class NotFound(Exception):
        pass

from heat.openstack.common import log as logging
from heat.openstack.common.exception import OpenstackException
from heat.openstack.common.gettextutils import _
from heat.engine import scheduler
from heat.engine.properties import Properties
from heat.engine.resources.rackspace import rackspace_resource
from heat.common import exception

logger = logging.getLogger(__name__)


class LoadbalancerBuildError(OpenstackException):
    message = _("There was an error building the loadbalancer:%(lb_name)s.")


class CloudLoadBalancer(rackspace_resource.RackspaceResource):

    protocol_values = ["DNS_TCP", "DNS_UDP", "FTP", "HTTP", "HTTPS", "IMAPS",
                       "IMAPv4", "LDAP", "LDAPS", "MYSQL", "POP3", "POP3S",
                       "SMTP", "TCP", "TCP_CLIENT_FIRST", "UDP", "UDP_STREAM",
                       "SFTP"]

    algorithm_values = ["LEAST_CONNECTIONS", "RANDOM", "ROUND_ROBIN",
                        "WEIGHTED_LEAST_CONNECTIONS", "WEIGHTED_ROUND_ROBIN"]

    nodes_schema = {
        'address': {'Type': 'String', 'Required': False},
        'ref': {'Type': 'String', 'Required': False},
        'port': {'Type': 'Number', 'Required': True},
        'condition': {'Type': 'String', 'Required': True,
                      'AllowedValues': ['ENABLED', 'DISABLED'],
                      'Default': 'ENABLED'},
        'type': {'Type': 'String', 'Required': False,
                 'AllowedValues': ['PRIMARY', 'SECONDARY']},
        'weight': {'Type': 'Number', 'MinValue': 1, 'MaxValue': 100}
    }

    access_list_schema = {
        'address': {'Type': 'String', 'Required': True},
        'type': {'Type': 'String', 'Required': True,
                 'AllowedValues': ['ALLOW', 'DENY']}
    }

    connection_logging_schema = {
        'enabled': {'Type': 'String', 'Required': True,
                    'AllowedValues': ["true", "false"]}
    }

    connection_throttle_schema = {
        'maxConnectionRate': {'Type': 'Number', 'Required': False,
                              'MinValue': 0, 'MaxValue': 100000},
        'minConnections': {'Type': 'Number', 'Required': False, 'MinValue': 1,
                           'MaxValue': 1000},
        'maxConnections': {'Type': 'Number', 'Required': False, 'MinValue': 1,
                           'MaxValue': 100000},
        'rateInterval': {'Type': 'Number', 'Required': False, 'MinValue': 1,
                         'MaxValue': 3600}
    }

    virtualip_schema = {
        'type': {'Type': 'String', 'Required': True,
                 'AllowedValues': ['SERVICENET', 'PUBLIC']},
        'ipVersion': {'Type': 'String', 'Required': False,
                      'AllowedValues': ['IPV6', 'IPV4'],
                      'Default': 'IPV6'}
    }

    health_monitor_base_schema = {
        'attemptsBeforeDeactivation': {'Type': 'Number', 'MinValue': 1,
                                       'MaxValue': 10, 'Required': True},
        'delay': {'Type': 'Number', 'MinValue': 1, 'MaxValue': 3600,
                  'Required': True},
        'timeout': {'Type': 'Number', 'MinValue': 1, 'MaxValue': 300,
                    'Required': True},
        'type': {'Type': 'String',
                 'AllowedValues': ['CONNECT', 'HTTP', 'HTTPS'],
                 'Required': True},
        'bodyRegex': {'Type': 'String', 'Required': False},
        'hostHeader': {'Type': 'String', 'Required': False},
        'path': {'Type': 'String', 'Required': False},
        'statusRegex': {'Type': 'String', 'Required': False},
    }

    health_monitor_connect_schema = {
        'attemptsBeforeDeactivation': {'Type': 'Number', 'MinValue': 1,
                                       'MaxValue': 10, 'Required': True},
        'delay': {'Type': 'Number', 'MinValue': 1, 'MaxValue': 3600,
                  'Required': True},
        'timeout': {'Type': 'Number', 'MinValue': 1, 'MaxValue': 300,
                    'Required': True},
        'type': {'Type': 'String', 'AllowedValues': ['CONNECT'],
                 'Required': True}
    }

    health_monitor_http_schema = {
        'attemptsBeforeDeactivation': {'Type': 'Number', 'Required': True,
                                       'MaxValue': 10, 'MinValue': 1},
        'bodyRegex': {'Type': 'String', 'Required': True},
        'delay': {'Type': 'Number', 'Required': True,
                  'MaxValue': 3600, 'MinValue': 1},
        'hostHeader': {'Type': 'String', 'Required': False},
        'path': {'Type': 'String', 'Required': True},
        'statusRegex': {'Type': 'String', 'Required': True},
        'timeout': {'Type': 'Number', 'Required': True,
                    'MaxValue': 300, 'MinValue': 1},
        'type': {'Type': 'String', 'Required': True,
                 'AllowedValues': ['HTTP', 'HTTPS']}
    }

    ssl_termination_base_schema = {
        "enabled": {'Type': 'Boolean', 'Required': True},
        "securePort": {'Type': 'Number', 'Required': False},
        "privatekey": {'Type': 'String', 'Required': False},
        "certificate": {'Type': 'String', 'Required': False},
        #only required if configuring intermediate ssl termination
        #add to custom validation
        "intermediateCertificate": {'Type': 'String', 'Required': False},
        #pyrax will default to false
        "secureTrafficOnly": {'Type': 'Boolean', 'Required': False}
    }

    ssl_termination_enabled_schema = {
        "securePort": {'Type': 'Number', 'Required': True},
        "privatekey": {'Type': 'String', 'Required': True},
        "certificate": {'Type': 'String', 'Required': True},
        "intermediateCertificate": {'Type': 'String', 'Required': False},
        "enabled": {'Type': 'Boolean', 'Required': True,
                    'AllowedValues': [True]},
        "secureTrafficOnly": {'Type': 'Boolean', 'Required': False}
    }

    properties_schema = {
        'name': {'Type': 'String', 'Required': False},
        'nodes': {'Type': 'List', 'Required': True,
                  'Schema': {'Type': 'Map', 'Schema': nodes_schema}},
        'protocol': {'Type': 'String', 'Required': True,
                     'AllowedValues': protocol_values},
        'accessList': {'Type': 'List', 'Required': False,
                       'Schema': {'Type': 'Map',
                                  'Schema': access_list_schema}},
        'halfClosed': {'Type': 'Boolean', 'Required': False},
        'algorithm': {'Type': 'String', 'Required': False},
        'connectionLogging': {'Type': 'Boolean', 'Required': False},
        'metadata': {'Type': 'Map', 'Required': False},
        'port': {'Type': 'Number', 'Required': True},
        'timeout': {'Type': 'Number', 'Required': False, 'MinValue': 1,
                    'MaxValue': 120},
        'connectionThrottle': {'Type': 'Map', 'Required': False,
                               'Schema': connection_throttle_schema},
        'sessionPersistence': {'Type': 'String', 'Required': False,
                               'AllowedValues': ['HTTP_COOKIE', 'SOURCE_IP']},
        'virtualIps': {'Type': 'List', 'Required': True,
                       'Schema': {'Type': 'Map', 'Schema': virtualip_schema}},
        'contentCaching': {'Type': 'String', 'Required': False,
                           'AllowedValues': ['ENABLED', 'DISABLED']},
        'healthMonitor': {'Type': 'Map', 'Required': False,
                          'Schema': health_monitor_base_schema},
        'sslTermination': {'Type': 'Map', 'Required': False,
                           'Schema': ssl_termination_base_schema},
        'errorPage': {'Type': 'String', 'Required': False}
    }

    attributes_schema = {
        'PublicIp': ('Public IP address of the specified '
                     'instance.')}

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('nodes',)

    def __init__(self, name, json_snippet, stack):
        super(CloudLoadBalancer, self).__init__(name, json_snippet, stack)
        self.clb = self.cloud_lb()

    def _setup_properties(self, properties, function):
        """Use defined schema properties as kwargs for loadbalancer objects."""
        if properties and function:
            return [function(**item_dict) for item_dict in properties]
        elif function:
            return [function()]

    def _alter_properties_for_api(self):
        """The following properties have usless key/value pairs which must
        be passed into the api. Set them up to make template definition easier.
        """
        session_persistence = None
        if'sessionPersistence' in self.properties.data:
            session_persistence = {'persistenceType':
                                   self.properties['sessionPersistence']}
        connection_logging = None
        if 'connectionLogging' in self.properties.data:
            connection_logging = {'enabled':
                                  self.properties['connectionLogging']}
        metadata = None
        if 'metadata' in self.properties.data:
            metadata = [{'key': k, 'value': v}
                        for k, v in self.properties['metadata'].iteritems()]

        return (session_persistence, connection_logging, metadata)

    def _check_status(self, loadbalancer, status_list):
        """Update the loadbalancer state, check the status."""
        loadbalancer.get()
        if loadbalancer.status in status_list:
            return True
        else:
            return False

    def _configure_post_creation(self, loadbalancer):
        """Configure all load balancer properties that must be done post
        creation.
        """
        if self.properties['accessList']:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.add_access_list(self.properties['accessList'])

        if self.properties['errorPage']:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.set_error_page(self.properties['errorPage'])

        if self.properties['sslTermination']:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.add_ssl_termination(
                self.properties['sslTermination']['securePort'],
                self.properties['sslTermination']['privatekey'],
                self.properties['sslTermination']['certificate'],
                intermediateCertificate=
                self.properties['sslTermination']
                ['intermediateCertificate'],
                enabled=self.properties['sslTermination']['enabled'],
                secureTrafficOnly=self.properties['sslTermination']
                ['secureTrafficOnly'])

        if 'contentCaching' in self.properties:
            enabled = True if self.properties['contentCaching'] == 'ENABLED'\
                else False
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.content_caching = enabled

    def handle_create(self):
        node_list = []
        for node in self.properties['nodes']:
            # resolve references to stack resource IP's
            if node.get('ref'):
                node['address'] = (self.stack
                                   .resource_by_refid(node['ref'])
                                   .FnGetAtt('PublicIp'))
            del node['ref']
            node_list.append(node)

        nodes = self._setup_properties(node_list, self.clb.Node)
        virtual_ips = self._setup_properties(self.properties.get('virtualIps'),
                                             self.clb.VirtualIP)

        (session_persistence, connection_logging, metadata) = \
            self._alter_properties_for_api()

        lb_body = {
            'port': self.properties['port'],
            'protocol': self.properties['protocol'],
            'nodes': nodes,
            'virtual_ips': virtual_ips,
            'algorithm': self.properties.get('algorithm'),
            'halfClosed': self.properties.get('halfClosed'),
            'connectionThrottle': self.properties.get('connectionThrottle'),
            'metadata': metadata,
            'healthMonitor': self.properties.get('healthMonitor'),
            'sessionPersistence': session_persistence,
            'timeout': self.properties.get('timeout'),
            'connectionLogging': connection_logging,
        }

        lb_name = self.properties.get('name') or self.physical_resource_name()
        logger.debug('Creating loadbalancer: %s' % {lb_name: lb_body})
        loadbalancer = self.clb.create(lb_name, **lb_body)
        self.resource_id_set(str(loadbalancer.id))

        post_create = scheduler.TaskRunner(self._configure_post_creation,
                                           loadbalancer)
        post_create(timeout=600)
        return loadbalancer

    def check_create_complete(self, loadbalancer):
        return self._check_status(loadbalancer, ['ACTIVE'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """
        Add and remove nodes specified in the prop_diff.
        """
        loadbalancer = self.clb.get(self.resource_id)
        if 'nodes' in prop_diff:
            current_nodes = loadbalancer.nodes
            #Loadbalancers can be uniquely identified by address and port.
            #Old is a dict of all nodes the loadbalancer currently knows about.
            for node in prop_diff['nodes']:
                # resolve references to stack resource IP's
                if node.get('ref'):
                    node['address'] = (self.stack
                                       .resource_by_refid(node['ref'])
                                       .FnGetAtt('PublicIp'))
                    del node['ref']
            old = dict(("{0.address}{0.port}".format(node), node)
                       for node in current_nodes)
            #New is a dict of the nodes the loadbalancer will know about after
            #this update.
            new = dict(("%s%s" % (node['address'], node['port']), node)
                       for node in prop_diff['nodes'])

            old_set = set(old.keys())
            new_set = set(new.keys())

            deleted = old_set.difference(new_set)
            added = new_set.difference(old_set)
            updated = new_set.intersection(old_set)

            if len(current_nodes) + len(added) - len(deleted) < 1:
                raise ValueError("The loadbalancer:%s requires at least one "
                                 "node." % self.name)
            """
            Add loadbalancers in the new map that are not in the old map.
            Add before delete to avoid deleting the last node and getting in
            an invalid state.
            """
            new_nodes = [self.clb.Node(**new[lb_node])
                         for lb_node in added]
            if new_nodes:
                loadbalancer.add_nodes(new_nodes)

            #Delete loadbalancers in the old dict that are not in the new dict.
            for node in deleted:
                old[node].delete()

            #Update nodes that have been changed
            for node in updated:
                node_changed = False
                for attribute in new[node].keys():
                    if new[node][attribute] != getattr(old[node], attribute):
                        node_changed = True
                        setattr(old[node], attribute, new[node][attribute])
                if node_changed:
                    old[node].update()

    def handle_delete(self):
        if self.resource_id is None:
            return
        try:
            loadbalancer = self.clb.get(self.resource_id)
        except NotFound:
            pass
        else:
            if loadbalancer.status != 'DELETED':
                loadbalancer.delete()
                self.resource_id_set(None)

    def _remove_none(self, property_dict):
        '''
        Remove values that may be initialized to None and would cause problems
        during schema validation.
        '''
        return dict((key, value)
                    for (key, value) in property_dict.iteritems()
                    if value)

    def validate(self):
        """
        Validate any of the provided params
        """
        res = super(CloudLoadBalancer, self).validate()
        if res:
            return res

        if self.properties.get('halfClosed'):
            if not (self.properties['protocol'] == 'TCP' or
                    self.properties['protocol'] == 'TCP_CLIENT_FIRST'):
                return {'Error':
                        'The halfClosed property is only available for the '
                        'TCP or TCP_CLIENT_FIRST protocols'}

        #health_monitor connect and http types require completely different
        #schema
        if self.properties.get('healthMonitor'):
            health_monitor = \
                self._remove_none(self.properties['healthMonitor'])

            if health_monitor['type'] == 'CONNECT':
                schema = CloudLoadBalancer.health_monitor_connect_schema
            else:
                schema = CloudLoadBalancer.health_monitor_http_schema
            try:
                Properties(schema,
                           health_monitor,
                           self.stack.resolve_runtime_data,
                           self.name).validate()
            except exception.StackValidationFailed as svf:
                return {'Error': str(svf)}

        if self.properties.get('sslTermination'):
            ssl_termination = self._remove_none(
                self.properties['sslTermination'])

            if ssl_termination['enabled']:
                try:
                    Properties(CloudLoadBalancer.
                               ssl_termination_enabled_schema,
                               ssl_termination,
                               self.stack.resolve_runtime_data,
                               self.name).validate()
                except exception.StackValidationFailed as svf:
                    return {'Error': str(svf)}

    def FnGetRefId(self):
        return unicode(self.name)

    def _public_ip(self):
        #TODO(andrew-plunk) return list here and let caller choose ip
        for ip in self.clb.get(self.resource_id).virtual_ips:
            if ip.type == 'PUBLIC':
                return ip.address

    def _resolve_attribute(self, key):
        attribute_function = {
            'PublicIp': self._public_ip()
        }
        if key not in attribute_function:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)
        function = attribute_function[key]
        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, function))
        return unicode(function)


def resource_mapping():
    if rackspace_resource.PYRAX_INSTALLED:
        return {
            'Rackspace::Cloud::LoadBalancer': CloudLoadBalancer
        }
    else:
        return {}
