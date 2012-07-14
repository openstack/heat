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
from heat.engine.resources import Resource
from novaclient.exceptions import NotFound

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.eip')


class ElasticIp(Resource):
    properties_schema = {'Domain': {'Type': 'String',
                                    'Implemented': False},
                         'InstanceId': {'Type': 'String'}}

    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = None

    def _ipaddress(self):
        if self.ipaddress is None:
            if self.instance_id is not None:
                try:
                    ips = self.nova().floating_ips.get(self.instance_id)
                except NotFound as ex:
                    logger.warn("Floating IPs not found: %s" % str(ex))
                else:
                    self.ipaddress = ips.ip
        return self.ipaddress or ''

    def handle_create(self):
        """Allocate a floating IP for the current tenant."""
        ips = self.nova().floating_ips.create()
        logger.info('ElasticIp create %s' % str(ips))
        self.ipaddress = ips.ip
        self.instance_id_set(ips.id)

    def validate(self):
        '''
        Validate the ip address here
        '''
        return Resource.validate(self)

    def handle_delete(self):
        """De-allocate a floating IP."""
        if self.instance_id is not None:
            self.nova().floating_ips.delete(self.instance_id)

    def FnGetRefId(self):
        return unicode(self._ipaddress())

    def FnGetAtt(self, key):
        if key == 'AllocationId':
            return unicode(self.instance_id)
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


class ElasticIpAssociation(Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': True},
                         'EIP': {'Type': 'String'},
                         'AllocationId': {'Type': 'String',
                                          'Implemented': False}}

    def __init__(self, name, json_snippet, stack):
        super(ElasticIpAssociation, self).__init__(name, json_snippet, stack)

    def FnGetRefId(self):
        if not 'EIP' in self.properties:
            return unicode('0.0.0.0')
        else:
            return unicode(self.properties['EIP'])

    def validate(self):
        '''
        Validate the ip address here
        '''
        return Resource.validate(self)

    def handle_create(self):
        """Add a floating IP address to a server."""
        logger.debug('ElasticIpAssociation %s.add_floating_ip(%s)' %
                     (self.properties['InstanceId'],
                      self.properties['EIP']))

        server = self.nova().servers.get(self.properties['InstanceId'])
        server.add_floating_ip(self.properties['EIP'])
        self.instance_id_set(self.properties['EIP'])

    def handle_delete(self):
        """Remove a floating IP address from a server."""
        try:
            server = self.nova().servers.get(self.properties['InstanceId'])
            if server:
                server.remove_floating_ip(self.properties['EIP'])
        except NotFound as ex:
            pass
