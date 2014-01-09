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
    PYRAX_INSTALLED = True
except ImportError:
    #Setup fake exception for testing without pyrax
    class NotFound(Exception):
        pass

    PYRAX_INSTALLED = False

import copy
import itertools

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _
from heat.engine import scheduler
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.properties import Properties
from heat.common import exception

logger = logging.getLogger(__name__)


class LoadbalancerBuildError(exception.HeatException):
    msg_fmt = _("There was an error building the loadbalancer:%(lb_name)s.")


class CloudLoadBalancer(resource.Resource):

    PROPERTIES = (
        NAME, NODES, PROTOCOL, ACCESS_LIST, HALF_CLOSED, ALGORITHM,
        CONNECTION_LOGGING, METADATA, PORT, TIMEOUT,
        CONNECTION_THROTTLE, SESSION_PERSISTENCE, VIRTUAL_IPS,
        CONTENT_CACHING, HEALTH_MONITOR, SSL_TERMINATION, ERROR_PAGE,
    ) = (
        'name', 'nodes', 'protocol', 'accessList', 'halfClosed', 'algorithm',
        'connectionLogging', 'metadata', 'port', 'timeout',
        'connectionThrottle', 'sessionPersistence', 'virtualIps',
        'contentCaching', 'healthMonitor', 'sslTermination', 'errorPage',
    )

    _NODE_KEYS = (
        NODE_ADDRESSES, NODE_PORT, NODE_CONDITION, NODE_TYPE,
        NODE_WEIGHT,
    ) = (
        'addresses', 'port', 'condition', 'type',
        'weight',
    )

    _ACCESS_LIST_KEYS = (
        ACCESS_LIST_ADDRESS, ACCESS_LIST_TYPE,
    ) = (
        'address', 'type',
    )

    _CONNECTION_THROTTLE_KEYS = (
        CONNECTION_THROTTLE_MAX_CONNECTION_RATE,
        CONNECTION_THROTTLE_MIN_CONNECTIONS,
        CONNECTION_THROTTLE_MAX_CONNECTIONS,
        CONNECTION_THROTTLE_RATE_INTERVAL,
    ) = (
        'maxConnectionRate',
        'minConnections',
        'maxConnections',
        'rateInterval',
    )

    _VIRTUAL_IP_KEYS = (
        VIRTUAL_IP_TYPE, VIRTUAL_IP_IP_VERSION,
    ) = (
        'type', 'ipVersion',
    )

    _HEALTH_MONITOR_KEYS = (
        HEALTH_MONITOR_ATTEMPTS_BEFORE_DEACTIVATION, HEALTH_MONITOR_DELAY,
        HEALTH_MONITOR_TIMEOUT, HEALTH_MONITOR_TYPE, HEALTH_MONITOR_BODY_REGEX,
        HEALTH_MONITOR_HOST_HEADER, HEALTH_MONITOR_PATH,
        HEALTH_MONITOR_STATUS_REGEX,
    ) = (
        'attemptsBeforeDeactivation', 'delay',
        'timeout', 'type', 'bodyRegex',
        'hostHeader', 'path',
        'statusRegex',
    )
    _HEALTH_MONITOR_CONNECT_KEYS = (
        HEALTH_MONITOR_ATTEMPTS_BEFORE_DEACTIVATION, HEALTH_MONITOR_DELAY,
        HEALTH_MONITOR_TIMEOUT, HEALTH_MONITOR_TYPE,
    )

    _SSL_TERMINATION_KEYS = (
        SSL_TERMINATION_SECURE_PORT, SSL_TERMINATION_PRIVATEKEY,
        SSL_TERMINATION_CERTIFICATE, SSL_TERMINATION_INTERMEDIATE_CERTIFICATE,
        SSL_TERMINATION_SECURE_TRAFFIC_ONLY,
    ) = (
        'securePort', 'privatekey',
        'certificate', 'intermediateCertificate',
        'secureTrafficOnly',
    )

    _health_monitor_schema = {
        HEALTH_MONITOR_ATTEMPTS_BEFORE_DEACTIVATION: properties.Schema(
            properties.Schema.NUMBER,
            required=True,
            constraints=[
                constraints.Range(1, 10),
            ]
        ),
        HEALTH_MONITOR_DELAY: properties.Schema(
            properties.Schema.NUMBER,
            required=True,
            constraints=[
                constraints.Range(1, 3600),
            ]
        ),
        HEALTH_MONITOR_TIMEOUT: properties.Schema(
            properties.Schema.NUMBER,
            required=True,
            constraints=[
                constraints.Range(1, 300),
            ]
        ),
        HEALTH_MONITOR_TYPE: properties.Schema(
            properties.Schema.STRING,
            required=True,
            constraints=[
                constraints.AllowedValues(['CONNECT', 'HTTP', 'HTTPS']),
            ]
        ),
        HEALTH_MONITOR_BODY_REGEX: properties.Schema(
            properties.Schema.STRING
        ),
        HEALTH_MONITOR_HOST_HEADER: properties.Schema(
            properties.Schema.STRING
        ),
        HEALTH_MONITOR_PATH: properties.Schema(
            properties.Schema.STRING
        ),
        HEALTH_MONITOR_STATUS_REGEX: properties.Schema(
            properties.Schema.STRING
        ),
    }

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING
        ),
        NODES: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NODE_ADDRESSES: properties.Schema(
                        properties.Schema.LIST,
                        required=True,
                        description=(_("IP addresses for the load balancer "
                                     "node. Must have at least one "
                                     "address.")),
                        schema=properties.Schema(
                            properties.Schema.STRING
                        )
                    ),
                    NODE_PORT: properties.Schema(
                        properties.Schema.NUMBER,
                        required=True
                    ),
                    NODE_CONDITION: properties.Schema(
                        properties.Schema.STRING,
                        default='ENABLED',
                        constraints=[
                            constraints.AllowedValues(['ENABLED',
                                                       'DISABLED']),
                        ]
                    ),
                    NODE_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        constraints=[
                            constraints.AllowedValues(['PRIMARY',
                                                       'SECONDARY']),
                        ]
                    ),
                    NODE_WEIGHT: properties.Schema(
                        properties.Schema.NUMBER,
                        constraints=[
                            constraints.Range(1, 100),
                        ]
                    ),
                },
            ),
            required=True,
            update_allowed=True
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            required=True,
            constraints=[
                constraints.AllowedValues(['DNS_TCP', 'DNS_UDP', 'FTP',
                                           'HTTP', 'HTTPS', 'IMAPS',
                                           'IMAPv4', 'LDAP', 'LDAPS',
                                           'MYSQL', 'POP3', 'POP3S', 'SMTP',
                                           'TCP', 'TCP_CLIENT_FIRST', 'UDP',
                                           'UDP_STREAM', 'SFTP']),
            ]
        ),
        ACCESS_LIST: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ACCESS_LIST_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    ACCESS_LIST_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        required=True,
                        constraints=[
                            constraints.AllowedValues(['ALLOW', 'DENY']),
                        ]
                    ),
                },
            )
        ),
        HALF_CLOSED: properties.Schema(
            properties.Schema.BOOLEAN
        ),
        ALGORITHM: properties.Schema(
            properties.Schema.STRING
        ),
        CONNECTION_LOGGING: properties.Schema(
            properties.Schema.BOOLEAN
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP
        ),
        PORT: properties.Schema(
            properties.Schema.NUMBER,
            required=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.NUMBER,
            constraints=[
                constraints.Range(1, 120),
            ]
        ),
        CONNECTION_THROTTLE: properties.Schema(
            properties.Schema.MAP,
            schema={
                CONNECTION_THROTTLE_MAX_CONNECTION_RATE: properties.Schema(
                    properties.Schema.NUMBER,
                    constraints=[
                        constraints.Range(0, 100000),
                    ]
                ),
                CONNECTION_THROTTLE_MIN_CONNECTIONS: properties.Schema(
                    properties.Schema.NUMBER,
                    constraints=[
                        constraints.Range(1, 1000),
                    ]
                ),
                CONNECTION_THROTTLE_MAX_CONNECTIONS: properties.Schema(
                    properties.Schema.NUMBER,
                    constraints=[
                        constraints.Range(1, 100000),
                    ]
                ),
                CONNECTION_THROTTLE_RATE_INTERVAL: properties.Schema(
                    properties.Schema.NUMBER,
                    constraints=[
                        constraints.Range(1, 3600),
                    ]
                ),
            }
        ),
        SESSION_PERSISTENCE: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['HTTP_COOKIE', 'SOURCE_IP']),
            ]
        ),
        VIRTUAL_IPS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    VIRTUAL_IP_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        required=True,
                        constraints=[
                            constraints.AllowedValues(['SERVICENET',
                                                       'PUBLIC']),
                        ]
                    ),
                    VIRTUAL_IP_IP_VERSION: properties.Schema(
                        properties.Schema.STRING,
                        default='IPV6',
                        constraints=[
                            constraints.AllowedValues(['IPV6', 'IPV4']),
                        ]
                    ),
                },
            ),
            required=True
        ),
        CONTENT_CACHING: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['ENABLED', 'DISABLED']),
            ]
        ),
        HEALTH_MONITOR: properties.Schema(
            properties.Schema.MAP,
            schema=_health_monitor_schema
        ),
        SSL_TERMINATION: properties.Schema(
            properties.Schema.MAP,
            schema={
                SSL_TERMINATION_SECURE_PORT: properties.Schema(
                    properties.Schema.NUMBER,
                    default=443
                ),
                SSL_TERMINATION_PRIVATEKEY: properties.Schema(
                    properties.Schema.STRING,
                    required=True
                ),
                SSL_TERMINATION_CERTIFICATE: properties.Schema(
                    properties.Schema.STRING,
                    required=True
                ),
                # only required if configuring intermediate ssl termination
                # add to custom validation
                SSL_TERMINATION_INTERMEDIATE_CERTIFICATE: properties.Schema(
                    properties.Schema.STRING
                ),
                # pyrax will default to false
                SSL_TERMINATION_SECURE_TRAFFIC_ONLY: properties.Schema(
                    properties.Schema.BOOLEAN,
                    default=False
                ),
            }
        ),
        ERROR_PAGE: properties.Schema(
            properties.Schema.STRING
        ),
    }

    attributes_schema = {
        'PublicIp': _('Public IP address of the specified '
                      'instance.')}

    update_allowed_keys = ('Properties',)

    def __init__(self, name, json_snippet, stack):
        super(CloudLoadBalancer, self).__init__(name, json_snippet, stack)
        self.clb = self.cloud_lb()

    def cloud_lb(self):
        return self.stack.clients.cloud_lb()

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
        if self.SESSION_PERSISTENCE in self.properties.data:
            session_persistence = {'persistenceType':
                                   self.properties[self.SESSION_PERSISTENCE]}
        connection_logging = None
        if self.CONNECTION_LOGGING in self.properties.data:
            connection_logging = {"enabled":
                                  self.properties[self.CONNECTION_LOGGING]}
        metadata = None
        if self.METADATA in self.properties.data:
            metadata = [{'key': k, 'value': v}
                        for k, v in self.properties[self.METADATA].iteritems()]

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
        if self.properties[self.ACCESS_LIST]:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.add_access_list(self.properties[self.ACCESS_LIST])

        if self.properties[self.ERROR_PAGE]:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.set_error_page(self.properties[self.ERROR_PAGE])

        if self.properties[self.SSL_TERMINATION]:
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            ssl_term = self.properties[self.SSL_TERMINATION]
            loadbalancer.add_ssl_termination(
                ssl_term[self.SSL_TERMINATION_SECURE_PORT],
                ssl_term[self.SSL_TERMINATION_PRIVATEKEY],
                ssl_term[self.SSL_TERMINATION_CERTIFICATE],
                intermediateCertificate=ssl_term[
                    self.SSL_TERMINATION_INTERMEDIATE_CERTIFICATE],
                enabled=True,
                secureTrafficOnly=ssl_term[
                    self.SSL_TERMINATION_SECURE_TRAFFIC_ONLY])

        if self.CONTENT_CACHING in self.properties:
            enabled = self.properties[self.CONTENT_CACHING] == 'ENABLED'
            while not self._check_status(loadbalancer, ['ACTIVE']):
                yield
            loadbalancer.content_caching = enabled

    def _process_node(self, node):
        if not node.get(self.NODE_ADDRESSES):
            yield node
        else:
            for addr in node.get(self.NODE_ADDRESSES):
                norm_node = copy.deepcopy(node)
                norm_node['address'] = addr
                del norm_node[self.NODE_ADDRESSES]
                yield norm_node

    def _process_nodes(self, node_list):
        node_itr = itertools.imap(self._process_node, node_list)
        return itertools.chain.from_iterable(node_itr)

    def handle_create(self):
        node_list = self._process_nodes(self.properties.get(self.NODES))
        nodes = [self.clb.Node(**node) for node in node_list]
        vips = self.properties.get(self.VIRTUAL_IPS)
        virtual_ips = self._setup_properties(vips, self.clb.VirtualIP)

        (session_persistence, connection_logging, metadata) = \
            self._alter_properties_for_api()

        lb_body = {
            'port': self.properties[self.PORT],
            'protocol': self.properties[self.PROTOCOL],
            'nodes': nodes,
            'virtual_ips': virtual_ips,
            'algorithm': self.properties.get(self.ALGORITHM),
            'halfClosed': self.properties.get(self.HALF_CLOSED),
            'connectionThrottle': self.properties.get(
                self.CONNECTION_THROTTLE),
            'metadata': metadata,
            'healthMonitor': self.properties.get(self.HEALTH_MONITOR),
            'sessionPersistence': session_persistence,
            'timeout': self.properties.get(self.TIMEOUT),
            'connectionLogging': connection_logging,
        }

        lb_name = (self.properties.get(self.NAME) or
                   self.physical_resource_name())
        logger.debug(_("Creating loadbalancer: %s") % {lb_name: lb_body})
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
        if self.NODES in prop_diff:
            current_nodes = loadbalancer.nodes
            diff_nodes = self._process_nodes(prop_diff[self.NODES])
            #Loadbalancers can be uniquely identified by address and port.
            #Old is a dict of all nodes the loadbalancer currently knows about.
            old = dict(("{0.address}{0.port}".format(node), node)
                       for node in current_nodes)
            #New is a dict of the nodes the loadbalancer will know about after
            #this update.
            new = dict(("%s%s" % (node["address"],
                                  node[self.NODE_PORT]), node)
                       for node in diff_nodes)

            old_set = set(old.keys())
            new_set = set(new.keys())

            deleted = old_set.difference(new_set)
            added = new_set.difference(old_set)
            updated = new_set.intersection(old_set)

            if len(current_nodes) + len(added) - len(deleted) < 1:
                raise ValueError(_("The loadbalancer:%s requires at least one "
                                 "node.") % self.name)
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

        if self.properties.get(self.HALF_CLOSED):
            if not (self.properties[self.PROTOCOL] == 'TCP' or
                    self.properties[self.PROTOCOL] == 'TCP_CLIENT_FIRST'):
                return {'Error':
                        'The %s property is only available for the TCP or '
                        'TCP_CLIENT_FIRST protocols' % self.HALF_CLOSED}

        #health_monitor connect and http types require completely different
        #schema
        if self.properties.get(self.HEALTH_MONITOR):
            health_monitor = \
                self._remove_none(self.properties[self.HEALTH_MONITOR])

            schema = self._health_monitor_schema
            if health_monitor[self.HEALTH_MONITOR_TYPE] == 'CONNECT':
                schema = dict((k, v) for k, v in schema.items()
                              if k in self._HEALTH_MONITOR_CONNECT_KEYS)
            try:
                Properties(schema,
                           health_monitor,
                           self.stack.resolve_runtime_data,
                           self.name).validate()
            except exception.StackValidationFailed as svf:
                return {'Error': str(svf)}

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
        logger.info(_('%(name)s.GetAtt(%(key)s) == %(function)s'),
                    {'name': self.name, 'key': key, 'function': function})
        return unicode(function)


def resource_mapping():
    return {'Rackspace::Cloud::LoadBalancer': CloudLoadBalancer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
