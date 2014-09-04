#
# Copyright (c) 2013 Docker, Inc.
# All Rights Reserved.
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

from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)

DOCKER_INSTALLED = False
# conditionally import so tests can work without having the dependency
# satisfied
try:
    import docker
    DOCKER_INSTALLED = True
except ImportError:
    docker = None


class DockerContainer(resource.Resource):

    PROPERTIES = (
        DOCKER_ENDPOINT, HOSTNAME, USER, MEMORY, PORT_SPECS,
        PRIVILEGED, TTY, OPEN_STDIN, STDIN_ONCE, ENV, CMD, DNS,
        IMAGE, VOLUMES, VOLUMES_FROM, PORT_BINDINGS, LINKS, NAME,
    ) = (
        'docker_endpoint', 'hostname', 'user', 'memory', 'port_specs',
        'privileged', 'tty', 'open_stdin', 'stdin_once', 'env', 'cmd', 'dns',
        'image', 'volumes', 'volumes_from', 'port_bindings', 'links', 'name'
    )

    ATTRIBUTES = (
        INFO, NETWORK_INFO, NETWORK_IP, NETWORK_GATEWAY,
        NETWORK_TCP_PORTS, NETWORK_UDP_PORTS, LOGS, LOGS_HEAD,
        LOGS_TAIL,
    ) = (
        'info', 'network_info', 'network_ip', 'network_gateway',
        'network_tcp_ports', 'network_udp_ports', 'logs', 'logs_head',
        'logs_tail',
    )

    properties_schema = {
        DOCKER_ENDPOINT: properties.Schema(
            properties.Schema.STRING,
            _('Docker daemon endpoint (by default the local docker daemon '
              'will be used).'),
            default=None
        ),
        HOSTNAME: properties.Schema(
            properties.Schema.STRING,
            _('Hostname of the container.'),
            default=''
        ),
        USER: properties.Schema(
            properties.Schema.STRING,
            _('Username or UID.'),
            default=''
        ),
        MEMORY: properties.Schema(
            properties.Schema.INTEGER,
            _('Memory limit (Bytes).'),
            default=0
        ),
        PORT_SPECS: properties.Schema(
            properties.Schema.LIST,
            _('TCP/UDP ports mapping.'),
            default=None
        ),
        PORT_BINDINGS: properties.Schema(
            properties.Schema.MAP,
            _('TCP/UDP ports bindings.'),
        ),
        LINKS: properties.Schema(
            properties.Schema.MAP,
            _('Links to other containers.'),
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the container.'),
        ),
        PRIVILEGED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enable extended privileges.'),
            default=False
        ),
        TTY: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Allocate a pseudo-tty.'),
            default=False
        ),
        OPEN_STDIN: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Open stdin.'),
            default=False
        ),
        STDIN_ONCE: properties.Schema(
            properties.Schema.BOOLEAN,
            _('If true, close stdin after the 1 attached client disconnects.'),
            default=False
        ),
        ENV: properties.Schema(
            properties.Schema.LIST,
            _('Set environment variables.'),
        ),
        CMD: properties.Schema(
            properties.Schema.LIST,
            _('Command to run after spawning the container.'),
            default=[]
        ),
        DNS: properties.Schema(
            properties.Schema.LIST,
            _('Set custom dns servers.'),
        ),
        IMAGE: properties.Schema(
            properties.Schema.STRING,
            _('Image name.')
        ),
        VOLUMES: properties.Schema(
            properties.Schema.MAP,
            _('Create a bind mount.'),
            default={}
        ),
        VOLUMES_FROM: properties.Schema(
            properties.Schema.LIST,
            _('Mount all specified volumes.'),
            default=''
        ),
    }

    attributes_schema = {
        INFO: attributes.Schema(
            _('Container info.')
        ),
        NETWORK_INFO: attributes.Schema(
            _('Container network info.')
        ),
        NETWORK_IP: attributes.Schema(
            _('Container ip address.')
        ),
        NETWORK_GATEWAY: attributes.Schema(
            _('Container ip gateway.')
        ),
        NETWORK_TCP_PORTS: attributes.Schema(
            _('Container TCP ports.')
        ),
        NETWORK_UDP_PORTS: attributes.Schema(
            _('Container UDP ports.')
        ),
        LOGS: attributes.Schema(
            _('Container logs.')
        ),
        LOGS_HEAD: attributes.Schema(
            _('Container first logs line.')
        ),
        LOGS_TAIL: attributes.Schema(
            _('Container last logs line.')
        ),
    }

    def get_client(self):
        client = None
        if DOCKER_INSTALLED:
            endpoint = self.properties.get(self.DOCKER_ENDPOINT)
            if endpoint:
                client = docker.Client(endpoint)
            else:
                client = docker.Client()
        return client

    def _parse_networkinfo_ports(self, networkinfo):
        tcp = []
        udp = []
        for port, info in six.iteritems(networkinfo['Ports']):
            p = port.split('/')
            if not info or len(p) != 2 or 'HostPort' not in info[0]:
                continue
            port = info[0]['HostPort']
            if p[1] == 'tcp':
                tcp.append(port)
            elif p[1] == 'udp':
                udp.append(port)
        return (','.join(tcp), ','.join(udp))

    def _container_networkinfo(self, client, resource_id):
        info = client.inspect_container(self.resource_id)
        networkinfo = info['NetworkSettings']
        ports = self._parse_networkinfo_ports(networkinfo)
        networkinfo['TcpPorts'] = ports[0]
        networkinfo['UdpPorts'] = ports[1]
        return networkinfo

    def _resolve_attribute(self, name):
        if not self.resource_id:
            return
        if name == 'info':
            client = self.get_client()
            return client.inspect_container(self.resource_id)
        if name == 'network_info':
            client = self.get_client()
            networkinfo = self._container_networkinfo(client, self.resource_id)
            return networkinfo
        if name == 'network_ip':
            client = self.get_client()
            networkinfo = self._container_networkinfo(client, self.resource_id)
            return networkinfo['IPAddress']
        if name == 'network_gateway':
            client = self.get_client()
            networkinfo = self._container_networkinfo(client, self.resource_id)
            return networkinfo['Gateway']
        if name == 'network_tcp_ports':
            client = self.get_client()
            networkinfo = self._container_networkinfo(client, self.resource_id)
            return networkinfo['TcpPorts']
        if name == 'network_udp_ports':
            client = self.get_client()
            networkinfo = self._container_networkinfo(client, self.resource_id)
            return networkinfo['UdpPorts']
        if name == 'logs':
            client = self.get_client()
            logs = client.logs(self.resource_id)
            return logs
        if name == 'logs_head':
            client = self.get_client()
            logs = client.logs(self.resource_id)
            return logs.split('\n')[0]
        if name == 'logs_tail':
            client = self.get_client()
            logs = client.logs(self.resource_id)
            return logs.split('\n').pop()

    def handle_create(self):
        create_args = {
            'image': self.properties[self.IMAGE],
            'command': self.properties[self.CMD],
            'hostname': self.properties[self.HOSTNAME],
            'user': self.properties[self.USER],
            'stdin_open': self.properties[self.OPEN_STDIN],
            'tty': self.properties[self.TTY],
            'mem_limit': self.properties[self.MEMORY],
            'ports': self.properties[self.PORT_SPECS],
            'environment': self.properties[self.ENV],
            'dns': self.properties[self.DNS],
            'volumes': self.properties[self.VOLUMES],
            'name': self.properties[self.NAME]
        }
        client = self.get_client()
        client.pull(self.properties[self.IMAGE])
        result = client.create_container(**create_args)
        container_id = result['Id']
        self.resource_id_set(container_id)

        start_args = {}

        if self.properties[self.PRIVILEGED]:
            start_args[self.PRIVILEGED] = True
        if self.properties[self.VOLUMES]:
            start_args['binds'] = self.properties[self.VOLUMES]
        if self.properties[self.VOLUMES_FROM]:
            start_args['volumes_from'] = self.properties[self.VOLUMES_FROM]
        if self.properties[self.PORT_BINDINGS]:
            start_args['port_bindings'] = self.properties[self.PORT_BINDINGS]
        if self.properties[self.LINKS]:
            start_args['links'] = self.properties[self.LINKS]

        client.start(container_id, **start_args)
        return container_id

    def _get_container_status(self, container_id):
        client = self.get_client()
        info = client.inspect_container(container_id)
        return info['State']

    def check_create_complete(self, container_id):
        status = self._get_container_status(container_id)
        return status['Running']

    def handle_delete(self):
        if self.resource_id is None:
            return
        client = self.get_client()
        try:
            client.kill(self.resource_id)
        except docker.errors.APIError as ex:
            if ex.response.status_code != 404:
                raise
        return self.resource_id

    def check_delete_complete(self, container_id):
        if container_id is None:
            return True
        try:
            status = self._get_container_status(container_id)
        except docker.errors.APIError as ex:
            if ex.response.status_code == 404:
                return True
            raise
        return (not status['Running'])

    def handle_suspend(self):
        if not self.resource_id:
            return
        client = self.get_client()
        client.stop(self.resource_id)
        return self.resource_id

    def check_suspend_complete(self, container_id):
        status = self._get_container_status(container_id)
        return (not status['Running'])

    def handle_resume(self):
        if not self.resource_id:
            return
        client = self.get_client()
        client.start(self.resource_id)
        return self.resource_id

    def check_resume_complete(self, container_id):
        status = self._get_container_status(container_id)
        return status['Running']


def resource_mapping():
    return {
        'DockerInc::Docker::Container': DockerContainer,
    }


def available_resource_mapping():
    if DOCKER_INSTALLED:
        return resource_mapping()
    else:
        LOG.warn(_("Docker plug-in loaded, but docker lib not installed."))
        return {}
