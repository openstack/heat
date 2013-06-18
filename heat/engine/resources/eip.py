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

from heat.engine import clients
from heat.common import exception
from heat.engine import resource

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class ElasticIp(resource.Resource):
    properties_schema = {'Domain': {'Type': 'String',
                                    'Implemented': False},
                         'InstanceId': {'Type': 'String'}}

    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _ipaddress(self):
        if self.ipaddress is None:
            if self.resource_id is not None:
                try:
                    ips = self.nova().floating_ips.get(self.resource_id)
                except clients.novaclient.exceptions.NotFound as ex:
                    logger.warn("Floating IPs not found: %s" % str(ex))
                else:
                    self.ipaddress = ips.ip
        return self.ipaddress or ''

    def handle_create(self):
        """Allocate a floating IP for the current tenant."""
        ips = self.nova().floating_ips.create()
        logger.info('ElasticIp create %s' % str(ips))
        self.ipaddress = ips.ip
        self.resource_id_set(ips.id)

        if self.properties['InstanceId']:
            server = self.nova().servers.get(self.properties['InstanceId'])
            res = server.add_floating_ip(self._ipaddress())

    def handle_delete(self):
        if self.properties['InstanceId']:
            try:
                server = self.nova().servers.get(self.properties['InstanceId'])
                if server:
                    server.remove_floating_ip(self._ipaddress())
            except clients.novaclient.exceptions.NotFound as ex:
                pass

        """De-allocate a floating IP."""
        if self.resource_id is not None:
            self.nova().floating_ips.delete(self.resource_id)

    def FnGetRefId(self):
        return unicode(self._ipaddress())

    def FnGetAtt(self, key):
        if key == 'AllocationId':
            return unicode(self.resource_id)
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


class ElasticIpAssociation(resource.Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': False},
                         'EIP': {'Type': 'String'},
                         'AllocationId': {'Type': 'String',
                                          'Implemented': False}}

    def FnGetRefId(self):
        return unicode(self.properties.get('EIP', '0.0.0.0'))

    def handle_create(self):
        """Add a floating IP address to a server."""
        logger.debug('ElasticIpAssociation %s.add_floating_ip(%s)' %
                     (self.properties['InstanceId'],
                      self.properties['EIP']))

        if self.properties['InstanceId']:
            server = self.nova().servers.get(self.properties['InstanceId'])
            server.add_floating_ip(self.properties['EIP'])
        self.resource_id_set(self.properties['EIP'])

    def handle_delete(self):
        """Remove a floating IP address from a server."""
        if self.properties['InstanceId']:
            try:
                server = self.nova().servers.get(self.properties['InstanceId'])
                if server:
                    server.remove_floating_ip(self.properties['EIP'])
            except clients.novaclient.exceptions.NotFound as ex:
                pass


def resource_mapping():
    return {
        'AWS::EC2::EIP': ElasticIp,
        'AWS::EC2::EIPAssociation': ElasticIpAssociation,
    }
