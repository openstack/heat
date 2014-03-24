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

from heat.engine import properties
from heat.engine import resource
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

DOCKER_INSTALLED = False
# conditionally import so tests can work without having the dependency
# satisfied
try:
    import docker
    DOCKER_INSTALLED = True
except ImportError:
    docker = None


class DockerContainer(resource.Resource):

    properties_schema = {
        'docker_endpoint': properties.Schema(
            properties.Schema.STRING,
            _('Docker daemon endpoint (by default the local docker daemon '
              'will be used)'),
            default=None
        ),
        'hostname': properties.Schema(
            properties.Schema.STRING,
            _('Hostname of the container'),
            default=''
        ),
        'user': properties.Schema(
            properties.Schema.STRING,
            _('Username or UID'),
            default=''
        ),
        'memory': properties.Schema(
            properties.Schema.INTEGER,
            _('Memory limit (Bytes)'),
            default=0
        ),
        'attach_stdin': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Attach to the the process\' standard input'),
            default=False
        ),
        'attach_stdout': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Attach to the process\' standard output'),
            default=True
        ),
        'attach_stderr': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Attach to the process\' standard error'),
            default=True
        ),
        'port_specs': properties.Schema(
            properties.Schema.LIST,
            _('TCP/UDP ports mapping'),
            default=None
        ),
        'privileged': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enable extended privileges'),
            default=False
        ),
        'tty': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Allocate a pseudo-tty'),
            default=False
        ),
        'open_stdin': properties.Schema(
            properties.Schema.BOOLEAN,
            _('Open stdin'),
            default=False
        ),
        'stdin_once': properties.Schema(
            properties.Schema.BOOLEAN,
            _('If true, close stdin after the 1 attached client disconnects'),
            default=False
        ),
        'env': properties.Schema(
            properties.Schema.LIST,
            _('Set environment variables'),
            default=None
        ),
        'cmd': properties.Schema(
            properties.Schema.LIST,
            _('Command to run after spawning the container'),
            default=[]
        ),
        'dns': properties.Schema(
            properties.Schema.LIST,
            _('Set custom dns servers'),
            default=None
        ),
        'image': properties.Schema(
            properties.Schema.STRING,
            _('Image name')
        ),
        'volumes': properties.Schema(
            properties.Schema.MAP,
            _('Create a bind mount'),
            default={}
        ),
        'volumes_from': properties.Schema(
            properties.Schema.STRING,
            _('Mount all specified volumes'),
            default=''
        ),
    }

    attributes_schema = {
        'info': _('Container info'),
        'network_info': _('Container network info'),
        'network_ip': _('Container ip address'),
        'network_gateway': _('Container ip gateway'),
        'network_tcp_ports': _('Container TCP ports'),
        'network_udp_ports': _('Container UDP ports'),
        'logs': _('Container logs'),
        'logs_head': _('Container first logs line'),
        'logs_tail': _('Container last logs line')
    }

    def get_client(self):
        client = None
        if DOCKER_INSTALLED:
            endpoint = self.properties.get('docker_endpoint')
            if endpoint:
                client = docker.Client(endpoint)
            else:
                client = docker.Client()
        return client

    def _parse_networkinfo_ports(self, networkinfo):
        tcp = []
        udp = []
        for port, info in networkinfo['Ports'].iteritems():
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
        args = {
            'image': self.properties['image'],
            'command': self.properties['cmd'],
            'hostname': self.properties['hostname'],
            'user': self.properties['user'],
            'stdin_open': self.properties['open_stdin'],
            'tty': self.properties['tty'],
            'mem_limit': self.properties['memory'],
            'ports': self.properties['port_specs'],
            'environment': self.properties['env'],
            'dns': self.properties['dns'],
            'volumes': self.properties['volumes'],
            'volumes_from': self.properties['volumes_from'],
        }
        client = self.get_client()
        result = client.create_container(**args)
        container_id = result['Id']
        self.resource_id_set(container_id)

        kwargs = {}
        if self.properties['privileged']:
            kwargs['privileged'] = True
        client.start(container_id, **kwargs)
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
        client.kill(self.resource_id)
        return self.resource_id

    def check_delete_complete(self, container_id):
        status = self._get_container_status(container_id)
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
        logger.warn(_("Docker plug-in loaded, but docker lib not installed."))
        return {}
