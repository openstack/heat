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
import re

from heat.common import exception
from heat.engine.resources import Resource

logger = logging.getLogger(__file__)


class Volume(Resource):
    properties_schema = {'AvailabilityZone': {'Type': 'String',
                                              'Required': True},
                         'Size': {'Type': 'Number'},
                         'SnapshotId': {'Type': 'String'},
                         'Tags': {'Type': 'List'}}

    def __init__(self, name, json_snippet, stack):
        super(Volume, self).__init__(name, json_snippet, stack)

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(Volume, self).create()

        vol = self.nova('volume').volumes.create(self.properties['Size'],
                                                 display_name=self.name,
                                                 display_description=self.name)

        while vol.status == 'creating':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'available':
            self.instance_id_set(vol.id)
            self.state_set(self.CREATE_COMPLETE)
        else:
            raise exception.Error(vol.status)

    def validate(self):
        '''
        Validate the volume
        '''
        return Resource.validate(self)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        if self.instance_id != None:
            vol = self.nova('volume').volumes.get(self.instance_id)
            if vol.status == 'in-use':
                logger.warn('cant delete volume when in-use')
                raise exception.Error("Volume in use")

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        if self.instance_id != None:
            self.nova('volume').volumes.delete(self.instance_id)
        self.state_set(self.DELETE_COMPLETE)


class VolumeAttachment(Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': True},
                         'VolumeId': {'Type': 'String',
                                      'Required': True},
                         'Device': {'Type': "String",
                                    'Required': True,
                                    'AllowedPattern': '/dev/vd[b-z]'}}

    def __init__(self, name, json_snippet, stack):
        super(VolumeAttachment, self).__init__(name, json_snippet, stack)

    def create(self):

        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(VolumeAttachment, self).create()

        server_id = self.properties['InstanceId']
        volume_id = self.properties['VolumeId']
        logger.warn('Attaching InstanceId %s VolumeId %s Device %s' %
                    (server_id, volume_id, self.properties['Device']))
        volapi = self.nova().volumes
        va = volapi.create_server_volume(server_id=server_id,
                                         volume_id=volume_id,
                                         device=self.properties['Device'])

        vol = self.nova('volume').volumes.get(va.id)
        while vol.status == 'available' or vol.status == 'attaching':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'in-use':
            self.instance_id_set(va.id)
            self.state_set(self.CREATE_COMPLETE)
        else:
            raise exception.Error(vol.status)

    def validate(self):
        '''
        Validate the mountpoint device
        '''
        return Resource.validate(self)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return
        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)

        server_id = self.properties['InstanceId']
        volume_id = self.properties['VolumeId']
        logger.info('VolumeAttachment un-attaching %s %s' % \
                    (server_id, volume_id))

        volapi = self.nova().volumes
        volapi.delete_server_volume(server_id,
                                    volume_id)

        vol = self.nova('volume').volumes.get(volume_id)
        logger.info('un-attaching %s, status %s' % (volume_id, vol.status))
        while vol.status == 'in-use':
            logger.info('trying to un-attach %s, but still %s' %
                        (volume_id, vol.status))
            eventlet.sleep(1)
            try:
                volapi.delete_server_volume(server_id,
                                            volume_id)
            except Exception:
                pass
            vol.get()

        self.state_set(self.DELETE_COMPLETE)
