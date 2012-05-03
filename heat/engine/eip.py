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

import eventlet
import logging
import os

from heat.common import exception
from heat.engine.resources import Resource

logger = logging.getLogger(__file__)


class ElasticIp(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIp, self).__init__(name, json_snippet, stack)
        self.ipaddress = ''

        if 'Domain' in self.t['Properties']:
            logger.warn('*** can\'t support Domain %s yet' % \
                        (self.t['Properties']['Domain']))

    def create(self):
        """Allocate a floating IP for the current tenant."""
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIp, self).create()

        ips = self.nova().floating_ips.create()
        logger.info('ElasticIp create %s' % str(ips))
        self.ipaddress = ips.ip
        self.instance_id_set(ips.id)
        self.state_set(self.CREATE_COMPLETE)

    def reload(self):
        '''
        get the ipaddress here
        '''
        if self.instance_id != None:
            try:
                ips = self.nova().floating_ips.get(self.instance_id)
                self.ipaddress = ips.ip
            except Exception as ex:
                logger.warn("Error getting floating IPs: %s" % str(ex))

        Resource.reload(self)

    def delete(self):
        """De-allocate a floating IP."""
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        if self.instance_id != None:
            self.nova().floating_ips.delete(self.instance_id)

        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.ipaddress)

    def FnGetAtt(self, key):
        if key == 'AllocationId':
            return unicode(self.instance_id)
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


class ElasticIpAssociation(Resource):
    def __init__(self, name, json_snippet, stack):
        super(ElasticIpAssociation, self).__init__(name, json_snippet, stack)

    def FnGetRefId(self):
        if not 'EIP' in self.t['Properties']:
            return unicode('0.0.0.0')
        else:
            return unicode(self.t['Properties']['EIP'])

    def create(self):
        """Add a floating IP address to a server."""

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(ElasticIpAssociation, self).create()
        logger.debug('ElasticIpAssociation %s.add_floating_ip(%s)' % \
                     (self.t['Properties']['InstanceId'],
                      self.t['Properties']['EIP']))

        server = self.nova().servers.get(self.t['Properties']['InstanceId'])
        server.add_floating_ip(self.t['Properties']['EIP'])
        self.instance_id_set(self.t['Properties']['EIP'])
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        """Remove a floating IP address from a server."""
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        server = self.nova().servers.get(self.t['Properties']['InstanceId'])
        server.remove_floating_ip(self.t['Properties']['EIP'])

        self.state_set(self.DELETE_COMPLETE)


