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

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import os
import pkgutil
from urlparse import urlparse

import eventlet
from oslo.config import cfg

from heat.engine import clients
from heat.engine import resource
from heat.common import exception

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class Restarter(resource.Resource):
    properties_schema = {'InstanceId': {'Type': 'String',
                                        'Required': True}}

    def _find_resource(self, resource_id):
        '''
        Return the resource with the specified instance ID, or None if it
        cannot be found.
        '''
        for resource in self.stack:
            if resource.resource_id == resource_id:
                return resource
        return None

    def alarm(self):
        victim = self._find_resource(self.properties['InstanceId'])

        if victim is None:
            logger.info('%s Alarm, can not find instance %s' %
                       (self.name, self.properties['InstanceId']))
            return

        logger.info('%s Alarm, restarting resource: %s' %
                    (self.name, victim.name))
        self.stack.restart_resource(victim.name)


class Instance(resource.Resource):
    # AWS does not require KeyName and InstanceType but we seem to
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {'ImageId': {'Type': 'String',
                                     'Required': True},
                         'InstanceType': {'Type': 'String',
                                          'Required': True},
                         'KeyName': {'Type': 'String'},
                         'AvailabilityZone': {'Type': 'String'},
                         'DisableApiTermination': {'Type': 'String',
                                                   'Implemented': False},
                         'KernelId': {'Type': 'String',
                                      'Implemented': False},
                         'Monitoring': {'Type': 'Boolean',
                                        'Implemented': False},
                         'PlacementGroupName': {'Type': 'String',
                                                'Implemented': False},
                         'PrivateIpAddress': {'Type': 'String',
                                              'Implemented': False},
                         'RamDiskId': {'Type': 'String',
                                       'Implemented': False},
                         'SecurityGroups': {'Type': 'List'},
                         'SecurityGroupIds': {'Type': 'List',
                                              'Implemented': False},
                         'NetworkInterfaces': {'Type': 'List'},
                         'SourceDestCheck': {'Type': 'Boolean',
                                             'Implemented': False},
                         'SubnetId': {'Type': 'String',
                                      'Implemented': False},
                         'Tags': {'Type': 'List',
                                  'Schema': {'Type': 'Map',
                                             'Schema': tags_schema}},
                         'NovaSchedulerHints': {'Type': 'List',
                                                'Schema': {
                                                    'Type': 'Map',
                                                    'Schema': tags_schema
                                                }},
                         'Tenancy': {'Type': 'String',
                                     'AllowedValues': ['dedicated', 'default'],
                                     'Implemented': False},
                         'UserData': {'Type': 'String'},
                         'Volumes': {'Type': 'List'}}

    # template keys supported for handle_update, note trailing comma
    # is required for a single item to get a tuple not a string
    update_allowed_keys = ('Metadata',)

    def __init__(self, name, json_snippet, stack):
        super(Instance, self).__init__(name, json_snippet, stack)
        self.ipaddress = None
        self.mime_string = None

    def _set_ipaddress(self, networks):
        '''
        Read the server's IP address from a list of networks provided by Nova
        '''
        # Just record the first ipaddress
        for n in networks:
            self.ipaddress = networks[n][0]
            break

    def _ipaddress(self):
        '''
        Return the server's IP address, fetching it from Nova if necessary
        '''
        if self.ipaddress is None:
            try:
                server = self.nova().servers.get(self.resource_id)
            except clients.novaclient.exceptions.NotFound as ex:
                logger.warn('Instance IP address not found (%s)' % str(ex))
            else:
                self._set_ipaddress(server.networks)

        return self.ipaddress or '0.0.0.0'

    def FnGetAtt(self, key):
        res = None
        if key == 'AvailabilityZone':
            res = self.properties['AvailabilityZone']
        elif key == 'PublicIp':
            res = self._ipaddress()
        elif key == 'PrivateIp':
            res = self._ipaddress()
        elif key == 'PublicDnsName':
            res = self._ipaddress()
        elif key == 'PrivateDnsName':
            res = self._ipaddress()
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.info('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)

    def _build_userdata(self, userdata):
        if not self.mime_string:
            # Build mime multipart data blob for cloudinit userdata

            def make_subpart(content, filename, subtype=None):
                if subtype is None:
                    subtype = os.path.splitext(filename)[0]
                msg = MIMEText(content, _subtype=subtype)
                msg.add_header('Content-Disposition', 'attachment',
                               filename=filename)
                return msg

            def read_cloudinit_file(fn):
                data = pkgutil.get_data('heat', 'cloudinit/%s' % fn)
                data = data.replace('@INSTANCE_USER@',
                                    cfg.CONF.instance_user)
                return data

            attachments = [(read_cloudinit_file('config'), 'cloud-config'),
                           (read_cloudinit_file('boothook.sh'), 'boothook.sh',
                            'cloud-boothook'),
                           (read_cloudinit_file('part-handler.py'),
                            'part-handler.py'),
                           (userdata, 'cfn-userdata', 'x-cfninitdata'),
                           (read_cloudinit_file('loguserdata.py'),
                            'loguserdata.py', 'x-shellscript')]

            if 'Metadata' in self.t:
                attachments.append((json.dumps(self.metadata),
                                    'cfn-init-data', 'x-cfninitdata'))

            attachments.append((cfg.CONF.heat_watch_server_url,
                                'cfn-watch-server', 'x-cfninitdata'))

            attachments.append((cfg.CONF.heat_metadata_server_url,
                                'cfn-metadata-server', 'x-cfninitdata'))

            # Create a boto config which the cfntools on the host use to know
            # where the cfn and cw API's are to be accessed
            cfn_url = urlparse(cfg.CONF.heat_metadata_server_url)
            cw_url = urlparse(cfg.CONF.heat_watch_server_url)
            is_secure = cfg.CONF.instance_connection_is_secure
            vcerts = cfg.CONF.instance_connection_https_validate_certificates
            boto_cfg = "\n".join(["[Boto]",
                                  "debug = 0",
                                  "is_secure = %s" % is_secure,
                                  "https_validate_certificates = %s" % vcerts,
                                  "cfn_region_name = heat",
                                  "cfn_region_endpoint = %s" %
                                  cfn_url.hostname,
                                  "cloudwatch_region_name = heat",
                                  "cloudwatch_region_endpoint = %s" %
                                  cw_url.hostname])
            attachments.append((boto_cfg,
                                'cfn-boto-cfg', 'x-cfninitdata'))

            subparts = [make_subpart(*args) for args in attachments]
            mime_blob = MIMEMultipart(_subparts=subparts)

            self.mime_string = mime_blob.as_string()

        return self.mime_string

    @staticmethod
    def _build_nics(network_interfaces):
        if not network_interfaces:
            return None

        nics = []
        for nic in network_interfaces:
            if isinstance(nic, basestring):
                nics.append({
                    'NetworkInterfaceId': nic,
                    'DeviceIndex': len(nics)})
            else:
                nics.append(nic)
        sorted_nics = sorted(nics, key=lambda nic: int(nic['DeviceIndex']))

        return [{'port-id': nic['NetworkInterfaceId']} for nic in sorted_nics]

    def handle_create(self):
        if self.properties.get('SecurityGroups') is None:
            security_groups = None
        else:
            security_groups = [self.physical_resource_name_find(sg)
                               for sg in self.properties.get('SecurityGroups')]

        userdata = self.properties['UserData'] or ''
        flavor = self.properties['InstanceType']
        key_name = self.properties['KeyName']
        availability_zone = self.properties['AvailabilityZone']

        keypairs = [k.name for k in self.nova().keypairs.list()]
        if key_name not in keypairs and key_name is not None:
            raise exception.UserKeyPairMissing(key_name=key_name)

        image_name = self.properties['ImageId']
        image_id = None
        image_list = self.nova().images.list()
        for o in image_list:
            if o.name == image_name:
                image_id = o.id
                break

        if image_id is None:
            logger.info("Image %s was not found in glance" % image_name)
            raise exception.ImageNotFound(image_name=image_name)

        flavor_id = None
        flavor_list = self.nova().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id
                break
        if flavor_id is None:
            raise exception.FlavorMissing(flavor_id=flavor)

        tags = {}
        if self.properties['Tags']:
            for tm in self.properties['Tags']:
                tags[tm['Key']] = tm['Value']
        else:
            tags = None

        scheduler_hints = {}
        if self.properties['NovaSchedulerHints']:
            for tm in self.properties['NovaSchedulerHints']:
                scheduler_hints[tm['Key']] = tm['Value']
        else:
            scheduler_hints = None

        nics = self._build_nics(self.properties['NetworkInterfaces'])

        server_userdata = self._build_userdata(userdata)
        server = None
        try:
            server = self.nova().servers.create(
                name=self.physical_resource_name(),
                image=image_id,
                flavor=flavor_id,
                key_name=key_name,
                security_groups=security_groups,
                userdata=server_userdata,
                meta=tags,
                scheduler_hints=scheduler_hints,
                nics=nics,
                availability_zone=availability_zone)
        finally:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            if server is not None:
                self.resource_id_set(server.id)

        return server

    def check_active(self, server):
        if server.status == 'ACTIVE':
            return True

        server.get()
        if server.status == 'BUILD':
            return False
        if server.status == 'ACTIVE':
            self._set_ipaddress(server.networks)
            self.attach_volumes()
            return True
        else:
            raise exception.Error('%s instance[%s] status[%s]' %
                                  ('nova reported unexpected',
                                   self.name, server.status))

    def attach_volumes(self):
        if not self.properties['Volumes']:
            return
        server_id = self.resource_id
        for vol in self.properties['Volumes']:
            if 'DeviceId' in vol:
                dev = vol['DeviceId']
            else:
                dev = vol['Device']
            self.stack.clients.attach_volume_to_instance(server_id,
                                                         vol['VolumeId'],
                                                         dev)

    def detach_volumes(self):
        server_id = self.resource_id
        for vol in self.properties['Volumes']:
            self.stack.clients.detach_volume_from_instance(server_id,
                                                           vol['VolumeId'])

    def handle_update(self, json_snippet):
        status = self.UPDATE_REPLACE
        try:
            tmpl_diff = self.update_template_diff(json_snippet)
        except NotImplementedError:
            return self.UPDATE_REPLACE

        for k in tmpl_diff:
            if k == 'Metadata':
                self.metadata = json_snippet.get('Metadata', {})
                status = self.UPDATE_COMPLETE
            else:
                return self.UPDATE_REPLACE

        return status

    def metadata_update(self, new_metadata=None):
        '''
        Refresh the metadata if new_metadata is None
        '''
        if new_metadata is None:
            self.metadata = self.parsed_template('Metadata')

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(Instance, self).validate()
        if res:
            return res

        # check validity of key
        try:
            key_name = self.properties['KeyName']
            if key_name is None:
                return
        except ValueError:
            return
        else:
            keypairs = self.nova().keypairs.list()
            for k in keypairs:
                if k.name == key_name:
                    return
        return {'Error':
                'Provided KeyName is not registered with nova'}

    def handle_delete(self):
        '''
        Delete an instance, blocking until it is disposed by OpenStack
        '''
        if self.resource_id is None:
            return

        if self.properties['Volumes']:
            self.detach_volumes()

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            pass
        else:
            server.delete()
            while True:
                try:
                    server.get()
                except clients.novaclient.exceptions.NotFound:
                    break
                eventlet.sleep(0.2)
        self.resource_id = None


def resource_mapping():
    return {
        'AWS::EC2::Instance': Instance,
        'OS::Heat::HARestarter': Restarter,
    }
