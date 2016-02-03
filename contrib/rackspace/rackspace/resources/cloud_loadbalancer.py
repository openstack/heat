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

import copy
import itertools

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import function
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

try:
    from pyrax.exceptions import NotFound  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    # Setup fake exception for testing without pyrax
    class NotFound(Exception):
        pass
    PYRAX_INSTALLED = False


LOG = logging.getLogger(__name__)


def lb_immutable(exc):
    if 'immutable' in six.text_type(exc):
        return True
    return False


class LoadbalancerBuildError(exception.HeatException):
    msg_fmt = _("There was an error building the loadbalancer:%(lb_name)s.")


class CloudLoadBalancer(resource.Resource):
    """Represents a Rackspace Cloud Loadbalancer."""

    support_status = support.SupportStatus(
        status=support.UNSUPPORTED,
        message=_('This resource is not supported, use at your own risk.'))

    PROPERTIES = (
        NAME, NODES, PROTOCOL, ACCESS_LIST, HALF_CLOSED, ALGORITHM,
        CONNECTION_LOGGING, METADATA, PORT, TIMEOUT,
        CONNECTION_THROTTLE, SESSION_PERSISTENCE, VIRTUAL_IPS,
        CONTENT_CACHING, HEALTH_MONITOR, SSL_TERMINATION, ERROR_PAGE,
        HTTPS_REDIRECT,
    ) = (
        'name', 'nodes', 'protocol', 'accessList', 'halfClosed', 'algorithm',
        'connectionLogging', 'metadata', 'port', 'timeout',
        'connectionThrottle', 'sessionPersistence', 'virtualIps',
        'contentCaching', 'healthMonitor', 'sslTermination', 'errorPage',
        'httpsRedirect',
    )

    LB_UPDATE_PROPS = (NAME, ALGORITHM, PROTOCOL, HALF_CLOSED, PORT, TIMEOUT,
                       HTTPS_REDIRECT)

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
        VIRTUAL_IP_TYPE, VIRTUAL_IP_IP_VERSION, VIRTUAL_IP_ID
    ) = (
        'type', 'ipVersion', 'id'
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

    ATTRIBUTES = (
        PUBLIC_IP, VIPS
    ) = (
        'PublicIp', 'virtualIps'
    )

    ALGORITHMS = ["LEAST_CONNECTIONS", "RANDOM", "ROUND_ROBIN",
                  "WEIGHTED_LEAST_CONNECTIONS", "WEIGHTED_ROUND_ROBIN"]

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
            properties.Schema.STRING,
            update_allowed=True
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
                        properties.Schema.INTEGER,
                        required=True
                    ),
                    NODE_CONDITION: properties.Schema(
                        properties.Schema.STRING,
                        default='ENABLED',
                        constraints=[
                            constraints.AllowedValues(['ENABLED',
                                                       'DISABLED',
                                                       'DRAINING']),
                        ]
                    ),
                    NODE_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        default='PRIMARY',
                        constraints=[
                            constraints.AllowedValues(['PRIMARY',
                                                       'SECONDARY']),
                        ]
                    ),
                    NODE_WEIGHT: properties.Schema(
                        properties.Schema.NUMBER,
                        default=1,
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
            ],
            update_allowed=True
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
            properties.Schema.BOOLEAN,
            update_allowed=True
        ),
        ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(ALGORITHMS)
            ],
            update_allowed=True
        ),
        CONNECTION_LOGGING: properties.Schema(
            properties.Schema.BOOLEAN,
            update_allowed=True
        ),
        METADATA: properties.Schema(
            properties.Schema.MAP,
            update_allowed=True
        ),
        PORT: properties.Schema(
            properties.Schema.INTEGER,
            required=True,
            update_allowed=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.NUMBER,
            constraints=[
                constraints.Range(1, 120),
            ],
            update_allowed=True
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
                    properties.Schema.INTEGER,
                    constraints=[
                        constraints.Range(1, 1000),
                    ]
                ),
                CONNECTION_THROTTLE_MAX_CONNECTIONS: properties.Schema(
                    properties.Schema.INTEGER,
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
            },
            update_allowed=True
        ),
        SESSION_PERSISTENCE: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['HTTP_COOKIE', 'SOURCE_IP']),
            ],
            update_allowed=True
        ),
        VIRTUAL_IPS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    VIRTUAL_IP_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        "The type of VIP (public or internal). This property"
                        " cannot be specified if 'id' is specified. This "
                        "property must be specified if id is not specified.",
                        constraints=[
                            constraints.AllowedValues(['SERVICENET',
                                                       'PUBLIC']),
                        ]
                    ),
                    VIRTUAL_IP_IP_VERSION: properties.Schema(
                        properties.Schema.STRING,
                        "IP version of the VIP. This property cannot be "
                        "specified if 'id' is specified. This property must "
                        "be specified if id is not specified.",
                        constraints=[
                            constraints.AllowedValues(['IPV6', 'IPV4']),
                        ]
                    ),
                    VIRTUAL_IP_ID: properties.Schema(
                        properties.Schema.NUMBER,
                        "ID of a shared VIP to use instead of creating a "
                        "new one. This property cannot be specified if type"
                        " or version is specified."
                    )
                },
            ),
            required=True,
            constraints=[
                constraints.Length(min=1)
            ]
        ),
        CONTENT_CACHING: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['ENABLED', 'DISABLED']),
            ],
            update_allowed=True
        ),
        HEALTH_MONITOR: properties.Schema(
            properties.Schema.MAP,
            schema=_health_monitor_schema,
            update_allowed=True
        ),
        SSL_TERMINATION: properties.Schema(
            properties.Schema.MAP,
            schema={
                SSL_TERMINATION_SECURE_PORT: properties.Schema(
                    properties.Schema.INTEGER,
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
            },
            update_allowed=True
        ),
        ERROR_PAGE: properties.Schema(
            properties.Schema.STRING,
            update_allowed=True
        ),
        HTTPS_REDIRECT: properties.Schema(
            properties.Schema.BOOLEAN,
            _("Enables or disables HTTP to HTTPS redirection for the load "
              "balancer. When enabled, any HTTP request returns status code "
              "301 (Moved Permanently), and the requester is redirected to "
              "the requested URL via the HTTPS protocol on port 443. Only "
              "available for HTTPS protocol (port=443), or HTTP protocol with "
              "a properly configured SSL termination (secureTrafficOnly=true, "
              "securePort=443)."),
            update_allowed=True,
            default=False,
            support_status=support.SupportStatus(version="2015.1")
        )
    }

    attributes_schema = {
        PUBLIC_IP: attributes.Schema(
            _('Public IP address of the specified instance.')
        ),
        VIPS: attributes.Schema(
            _("A list of assigned virtual ip addresses")
        )
    }

    ACTIVE_STATUS = 'ACTIVE'
    DELETED_STATUS = 'DELETED'
    PENDING_DELETE_STATUS = 'PENDING_DELETE'
    PENDING_UPDATE_STATUS = 'PENDING_UPDATE'

    def __init__(self, name, json_snippet, stack):
        super(CloudLoadBalancer, self).__init__(name, json_snippet, stack)
        self.clb = self.cloud_lb()

    def cloud_lb(self):
        return self.client('cloud_lb')

    def _setup_properties(self, properties, function):
        """Use defined schema properties as kwargs for loadbalancer objects."""
        if properties and function:
            return [function(**self._remove_none(item_dict))
                    for item_dict in properties]
        elif function:
            return [function()]

    def _alter_properties_for_api(self):
        """Set up required, but useless, key/value pairs.

        The following properties have useless key/value pairs which must
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
                        for k, v
                        in six.iteritems(self.properties[self.METADATA])]

        return (session_persistence, connection_logging, metadata)

    def _check_active(self, lb=None):
        """Update the loadbalancer state, check the status."""
        if not lb:
            lb = self.clb.get(self.resource_id)
        if lb.status == self.ACTIVE_STATUS:
            return True
        else:
            return False

    def _valid_HTTPS_redirect_with_HTTP_prot(self):
        """Determine if HTTPS redirect is valid when protocol is HTTP"""
        proto = self.properties[self.PROTOCOL]
        redir = self.properties[self.HTTPS_REDIRECT]
        termcfg = self.properties.get(self.SSL_TERMINATION) or {}
        seconly = termcfg.get(self.SSL_TERMINATION_SECURE_TRAFFIC_ONLY, False)
        secport = termcfg.get(self.SSL_TERMINATION_SECURE_PORT, 0)
        if (redir and (proto == "HTTP") and seconly and (secport == 443)):
            return True
        return False

    def _process_node(self, node):
        for addr in node.get(self.NODE_ADDRESSES, []):
            norm_node = copy.deepcopy(node)
            norm_node['address'] = addr
            del norm_node[self.NODE_ADDRESSES]
            yield norm_node

    def _process_nodes(self, node_list):
        node_itr = six.moves.map(self._process_node, node_list)
        return itertools.chain.from_iterable(node_itr)

    def _validate_https_redirect(self):
        redir = self.properties[self.HTTPS_REDIRECT]
        proto = self.properties[self.PROTOCOL]

        if (redir and (proto != "HTTPS") and
                not self._valid_HTTPS_redirect_with_HTTP_prot()):
            message = _("HTTPS redirect is only available for the HTTPS "
                        "protocol (port=443), or the HTTP protocol with "
                        "a properly configured SSL termination "
                        "(secureTrafficOnly=true, securePort=443).")
            raise exception.StackValidationFailed(message=message)

    def handle_create(self):
        node_list = self._process_nodes(self.properties.get(self.NODES))
        nodes = [self.clb.Node(**node) for node in node_list]
        vips = self.properties.get(self.VIRTUAL_IPS)

        virtual_ips = self._setup_properties(vips, self.clb.VirtualIP)

        (session_persistence, connection_logging, metadata
         ) = self._alter_properties_for_api()

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
            self.HTTPS_REDIRECT: self.properties[self.HTTPS_REDIRECT]
        }
        if self._valid_HTTPS_redirect_with_HTTP_prot():
            lb_body[self.HTTPS_REDIRECT] = False
        self._validate_https_redirect()

        lb_name = (self.properties.get(self.NAME) or
                   self.physical_resource_name())
        LOG.debug("Creating loadbalancer: %s" % {lb_name: lb_body})
        lb = self.clb.create(lb_name, **lb_body)
        self.resource_id_set(str(lb.id))

    def check_create_complete(self, *args):
        lb = self.clb.get(self.resource_id)
        return (self._check_active(lb) and
                self._create_access_list(lb) and
                self._create_errorpage(lb) and
                self._create_ssl_term(lb) and
                self._create_redirect(lb) and
                self._create_cc(lb))

    def _create_access_list(self, lb):
        if not self.properties[self.ACCESS_LIST]:
            return True

        old_access_list = lb.get_access_list()
        new_access_list = self.properties[self.ACCESS_LIST]
        if not self._access_list_needs_update(old_access_list,
                                              new_access_list):
            return True

        try:
            lb.add_access_list(new_access_list)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise
        return False

    def _create_errorpage(self, lb):
        if not self.properties[self.ERROR_PAGE]:
            return True

        old_errorpage = lb.get_error_page()
        new_errorpage_content = self.properties[self.ERROR_PAGE]
        new_errorpage = {'errorpage': {'content': new_errorpage_content}}
        if not self._errorpage_needs_update(old_errorpage, new_errorpage):
            return True

        try:
            lb.set_error_page(new_errorpage_content)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise
        return False

    def _create_ssl_term(self, lb):
        if not self.properties[self.SSL_TERMINATION]:
            return True

        old_ssl_term = lb.get_ssl_termination()
        new_ssl_term = self.properties[self.SSL_TERMINATION]
        if not self._ssl_term_needs_update(old_ssl_term, new_ssl_term):
            return True

        try:
            lb.add_ssl_termination(**new_ssl_term)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise
        return False

    def _create_redirect(self, lb):
        if not self._valid_HTTPS_redirect_with_HTTP_prot():
            return True

        old_redirect = lb.httpsRedirect
        new_redirect = self.properties[self.HTTPS_REDIRECT]
        if not self._redirect_needs_update(old_redirect, new_redirect):
            return True

        try:
            lb.update(httpsRedirect=True)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise
        return False

    def _create_cc(self, lb):
        if not self.properties[self.CONTENT_CACHING]:
            return True

        old_cc = lb.content_caching
        new_cc = self.properties[self.CONTENT_CACHING] == 'ENABLED'
        if not self._cc_needs_update(old_cc, new_cc):
            return True

        try:
            lb.content_caching = new_cc
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise
        return False

    def handle_check(self):
        lb = self.clb.get(self.resource_id)
        if not self._check_active():
            raise exception.Error(_("Cloud Loadbalancer is not ACTIVE "
                                    "(was: %s)") % lb.status)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        return prop_diff

    def check_update_complete(self, prop_diff):
        lb = self.clb.get(self.resource_id)
        return (lb.status != self.PENDING_UPDATE_STATUS and  # lb immutable?
                self._update_props(lb, prop_diff) and
                self._update_nodes_add(lb, prop_diff) and
                self._update_nodes_delete(lb, prop_diff) and
                self._update_nodes_change(lb, prop_diff) and
                self._update_health_monitor(lb, prop_diff) and
                self._update_session_persistence(lb, prop_diff) and
                self._update_ssl_termination(lb, prop_diff) and
                self._update_metadata(lb, prop_diff) and
                self._update_errorpage(lb, prop_diff) and
                self._update_connection_logging(lb, prop_diff) and
                self._update_connection_throttle(lb, prop_diff) and
                self._update_content_caching(lb, prop_diff))

    def _nodes_need_update_add(self, old, new):
        if not old:
            return True

        new = list(self._process_nodes(new))
        new_nodes = ["%s%s" % (x['address'], x['port']) for x in new]
        old_nodes = ["%s%s" % (x.address, x.port) for x in old]
        for node in new_nodes:
            if node not in old_nodes:
                return True

        return False

    def _nodes_need_update_delete(self, old, new):
        if not new:
            return True

        new = list(self._process_nodes(new))
        new_nodes = ["%s%s" % (x['address'], x['port']) for x in new]
        old_nodes = ["%s%s" % (x.address, x.port) for x in old]
        for node in old_nodes:
            if node not in new_nodes:
                return True

        return False

    def _nodes_need_update_change(self, old, new):
        def find_node(nodes, address, port):
            for node in nodes:
                if node['address'] == address and node['port'] == port:
                    return node

        new = list(self._process_nodes(new))
        for old_node in old:
            new_node = find_node(new, old_node.address, old_node.port)
            if (new_node['condition'] != old_node.condition or
                    new_node['type'] != old_node.type or
                    new_node['weight'] != old_node.weight):
                return True

        return False

    def _needs_update_comparison(self, old, new):
        if old != new:
            return True
        return False

    def _needs_update_comparison_bool(self, old, new):
        if new is None:
            return old
        return self._needs_update_comparison(old, new)

    def _needs_update_comparison_nullable(self, old, new):
        if not old and not new:
            return False
        return self._needs_update_comparison(old, new)

    def _props_need_update(self, old, new):
        return self._needs_update_comparison_nullable(old, new)  # dict

    def _hm_needs_update(self, old, new):
        return self._needs_update_comparison_nullable(old, new)  # dict

    def _sp_needs_update(self, old, new):
        return self._needs_update_comparison_bool(old, new)  # bool

    def _metadata_needs_update(self, old, new):
        return self._needs_update_comparison_nullable(old, new)  # dict

    def _errorpage_needs_update(self, old, new):
        return self._needs_update_comparison_nullable(old, new)  # str

    def _cl_needs_update(self, old, new):
        return self._needs_update_comparison_bool(old, new)  # bool

    def _ct_needs_update(self, old, new):
        return self._needs_update_comparison_nullable(old, new)  # dict

    def _cc_needs_update(self, old, new):
        return self._needs_update_comparison_bool(old, new)  # bool

    def _ssl_term_needs_update(self, old, new):
        if new is None:
            return self._needs_update_comparison_nullable(
                old, new)  # dict

        # check all relevant keys
        if (old.get(self.SSL_TERMINATION_SECURE_PORT) !=
                new[self.SSL_TERMINATION_SECURE_PORT]):
            return True
        if (old.get(self.SSL_TERMINATION_SECURE_TRAFFIC_ONLY) !=
                new[self.SSL_TERMINATION_SECURE_TRAFFIC_ONLY]):
            return True
        if (old.get(self.SSL_TERMINATION_CERTIFICATE, '').strip() !=
                new.get(self.SSL_TERMINATION_CERTIFICATE, '').strip()):
            return True
        if (new.get(self.SSL_TERMINATION_INTERMEDIATE_CERTIFICATE, '')
                and (old.get(self.SSL_TERMINATION_INTERMEDIATE_CERTIFICATE,
                             '').strip()
                     != new.get(self.SSL_TERMINATION_INTERMEDIATE_CERTIFICATE,
                                '').strip())):
            return True
        return False

    def _access_list_needs_update(self, old, new):
        old = [{key: al[key] for key in self._ACCESS_LIST_KEYS} for al in old]
        old = set([frozenset(s.items()) for s in old])
        new = set([frozenset(s.items()) for s in new])
        return old != new

    def _redirect_needs_update(self, old, new):
        return self._needs_update_comparison_bool(old, new)  # bool

    def _update_props(self, lb, prop_diff):
        old_props = {}
        new_props = {}

        for prop in six.iterkeys(prop_diff):
            if prop in self.LB_UPDATE_PROPS:
                old_props[prop] = getattr(lb, prop)
                new_props[prop] = prop_diff[prop]

        if new_props and self._props_need_update(old_props, new_props):
            try:
                lb.update(**new_props)
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise
            return False

        return True

    def _nodes_update_data(self, lb, prop_diff):
        current_nodes = lb.nodes
        diff_nodes = self._process_nodes(prop_diff[self.NODES])
        # Loadbalancers can be uniquely identified by address and
        # port.  Old is a dict of all nodes the loadbalancer
        # currently knows about.
        old = dict(("{0.address}{0.port}".format(node), node)
                   for node in current_nodes)
        # New is a dict of the nodes the loadbalancer will know
        # about after this update.
        new = dict(("%s%s" % (node["address"],
                              node[self.NODE_PORT]), node)
                   for node in diff_nodes)

        old_set = set(six.iterkeys(old))
        new_set = set(six.iterkeys(new))

        deleted = old_set.difference(new_set)
        added = new_set.difference(old_set)
        updated = new_set.intersection(old_set)

        return old, new, deleted, added, updated

    def _update_nodes_add(self, lb, prop_diff):
        """Add loadbalancers in the new map that are not in the old map."""
        if self.NODES not in prop_diff:
            return True

        old_nodes = lb.nodes if hasattr(lb, self.NODES) else None
        new_nodes = prop_diff[self.NODES]
        if not self._nodes_need_update_add(old_nodes, new_nodes):
            return True

        old, new, deleted, added, updated = self._nodes_update_data(lb,
                                                                    prop_diff)
        new_nodes = [self.clb.Node(**new[lb_node]) for lb_node in added]
        if new_nodes:
            try:
                lb.add_nodes(new_nodes)
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise

        return False

    def _update_nodes_delete(self, lb, prop_diff):
        """Delete loadbalancers in the old dict that aren't in the new dict."""
        if self.NODES not in prop_diff:
            return True

        old_nodes = lb.nodes if hasattr(lb, self.NODES) else None
        new_nodes = prop_diff[self.NODES]
        if not self._nodes_need_update_delete(old_nodes, new_nodes):
            return True

        old, new, deleted, added, updated = self._nodes_update_data(lb,
                                                                    prop_diff)
        for node in deleted:
            try:
                old[node].delete()
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise

        return False

    def _update_nodes_change(self, lb, prop_diff):
        """Update nodes that have been changed."""
        if self.NODES not in prop_diff:
            return True

        old_nodes = lb.nodes if hasattr(lb, self.NODES) else None
        new_nodes = prop_diff[self.NODES]
        if not self._nodes_need_update_change(old_nodes, new_nodes):
            return True

        old, new, deleted, added, updated = self._nodes_update_data(lb,
                                                                    prop_diff)

        for node in updated:
            node_changed = False
            for attribute in six.iterkeys(new[node]):
                new_value = new[node][attribute]
                if new_value and new_value != getattr(old[node], attribute):
                    node_changed = True
                    setattr(old[node], attribute, new_value)
            if node_changed:
                try:
                    old[node].update()
                except Exception as exc:
                    if lb_immutable(exc):
                        return False
                    raise

        return False

    def _update_health_monitor(self, lb, prop_diff):
        if self.HEALTH_MONITOR not in prop_diff:
            return True

        old_hm = lb.get_health_monitor()
        new_hm = prop_diff[self.HEALTH_MONITOR]
        if not self._hm_needs_update(old_hm, new_hm):
            return True

        try:
            if new_hm is None:
                lb.delete_health_monitor()
            else:
                # Adding a health monitor is a destructive, so there's
                # no need to delete, then add
                lb.add_health_monitor(**new_hm)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_session_persistence(self, lb, prop_diff):
        if self.SESSION_PERSISTENCE not in prop_diff:
            return True

        old_sp = lb.session_persistence
        new_sp = prop_diff[self.SESSION_PERSISTENCE]
        if not self._sp_needs_update(old_sp, new_sp):
            return True

        try:
            if new_sp is None:
                lb.session_persistence = ''
            else:
                # Adding session persistence is destructive
                lb.session_persistence = new_sp
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_ssl_termination(self, lb, prop_diff):
        if self.SSL_TERMINATION not in prop_diff:
            return True

        old_ssl_term = lb.get_ssl_termination()
        new_ssl_term = prop_diff[self.SSL_TERMINATION]
        if not self._ssl_term_needs_update(old_ssl_term, new_ssl_term):
            return True

        try:
            if new_ssl_term is None:
                lb.delete_ssl_termination()
            else:
                # Adding SSL termination is destructive
                lb.add_ssl_termination(**new_ssl_term)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_metadata(self, lb, prop_diff):
        if self.METADATA not in prop_diff:
            return True

        old_metadata = lb.get_metadata()
        new_metadata = prop_diff[self.METADATA]
        if not self._metadata_needs_update(old_metadata, new_metadata):
            return True

        try:
            if new_metadata is None:
                lb.delete_metadata()
            else:
                lb.set_metadata(new_metadata)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_errorpage(self, lb, prop_diff):
        if self.ERROR_PAGE not in prop_diff:
            return True

        old_errorpage = lb.get_error_page()['errorpage']['content']
        new_errorpage = prop_diff[self.ERROR_PAGE]
        if not self._errorpage_needs_update(old_errorpage, new_errorpage):
            return True

        try:
            if new_errorpage is None:
                lb.clear_error_page()
            else:
                lb.set_error_page(new_errorpage)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_connection_logging(self, lb, prop_diff):
        if self.CONNECTION_LOGGING not in prop_diff:
            return True

        old_cl = lb.connection_logging
        new_cl = prop_diff[self.CONNECTION_LOGGING]
        if not self._cl_needs_update(old_cl, new_cl):
            return True

        try:
            if new_cl:
                lb.connection_logging = True
            else:
                lb.connection_logging = False
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_connection_throttle(self, lb, prop_diff):
        if self.CONNECTION_THROTTLE not in prop_diff:
            return True

        old_ct = lb.get_connection_throttle()
        new_ct = prop_diff[self.CONNECTION_THROTTLE]
        if not self._ct_needs_update(old_ct, new_ct):
            return True

        try:
            if new_ct is None:
                lb.delete_connection_throttle()
            else:
                lb.add_connection_throttle(**new_ct)
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def _update_content_caching(self, lb, prop_diff):
        if self.CONTENT_CACHING not in prop_diff:
            return True

        old_cc = lb.content_caching
        new_cc = prop_diff[self.CONTENT_CACHING] == 'ENABLED'
        if not self._cc_needs_update(old_cc, new_cc):
            return True

        try:
            lb.content_caching = new_cc
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def check_delete_complete(self, *args):
        if self.resource_id is None:
            return True

        try:
            loadbalancer = self.clb.get(self.resource_id)
        except NotFound:
            return True

        if loadbalancer.status == self.DELETED_STATUS:
            return True

        elif loadbalancer.status == self.PENDING_DELETE_STATUS:
            return False

        else:
            try:
                loadbalancer.delete()
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise

        return False

    def _remove_none(self, property_dict):
        """Remove None values that would cause schema validation problems.

        These are values that may be initialized to None.
        """
        return dict((key, value)
                    for (key, value) in six.iteritems(property_dict)
                    if value is not None)

    def validate(self):
        """Validate any of the provided params."""
        res = super(CloudLoadBalancer, self).validate()
        if res:
            return res

        if self.properties.get(self.HALF_CLOSED):
            if not (self.properties[self.PROTOCOL] == 'TCP' or
                    self.properties[self.PROTOCOL] == 'TCP_CLIENT_FIRST'):
                message = (_('The %s property is only available for the TCP '
                             'or TCP_CLIENT_FIRST protocols')
                           % self.HALF_CLOSED)
                raise exception.StackValidationFailed(message=message)

        # health_monitor connect and http types require completely different
        # schema
        if self.properties.get(self.HEALTH_MONITOR):
            prop_val = self.properties[self.HEALTH_MONITOR]
            health_monitor = self._remove_none(prop_val)

            schema = self._health_monitor_schema
            if health_monitor[self.HEALTH_MONITOR_TYPE] == 'CONNECT':
                schema = dict((k, v) for k, v in schema.items()
                              if k in self._HEALTH_MONITOR_CONNECT_KEYS)
            properties.Properties(schema,
                                  health_monitor,
                                  function.resolve,
                                  self.name).validate()

        # validate if HTTPS_REDIRECT is true
        self._validate_https_redirect()
        # if a vip specifies and id, it can't specify version or type;
        # otherwise version and type are required
        for vip in self.properties.get(self.VIRTUAL_IPS, []):
            has_id = vip.get(self.VIRTUAL_IP_ID) is not None
            has_version = vip.get(self.VIRTUAL_IP_IP_VERSION) is not None
            has_type = vip.get(self.VIRTUAL_IP_TYPE) is not None
            if has_id:
                if (has_version or has_type):
                    message = _("Cannot specify type or version if VIP id is"
                                " specified.")
                    raise exception.StackValidationFailed(message=message)
            elif not (has_version and has_type):
                message = _("Must specify VIP type and version if no id "
                            "specified.")
                raise exception.StackValidationFailed(message=message)

    def _public_ip(self, lb):
        for ip in lb.virtual_ips:
            if ip.type == 'PUBLIC':
                return six.text_type(ip.address)

    def _resolve_attribute(self, key):
        if self.resource_id:
            lb = self.clb.get(self.resource_id)
            attribute_function = {
                self.PUBLIC_IP: self._public_ip(lb),
                self.VIPS: [{"id": vip.id,
                             "type": vip.type,
                             "ip_version": vip.ip_version,
                             "address": vip.address}
                            for vip in lb.virtual_ips]
            }
            if key not in attribute_function:
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key=key)
            function = attribute_function[key]
            LOG.info(_LI('%(name)s.GetAtt(%(key)s) == %(function)s'),
                     {'name': self.name, 'key': key, 'function': function})
            return function


def resource_mapping():
    return {'Rackspace::Cloud::LoadBalancer': CloudLoadBalancer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
