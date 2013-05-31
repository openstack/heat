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

from oslo.config import cfg

from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import volume

from heat.common import exception
from heat.engine.resources.network_interface import NetworkInterface

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
    # AWS does not require InstanceType but Heat does because the nova
    # create api call requires a flavor
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
                         'SecurityGroupIds': {'Type': 'List'},
                         'NetworkInterfaces': {'Type': 'List'},
                         'SourceDestCheck': {'Type': 'Boolean',
                                             'Implemented': False},
                         'SubnetId': {'Type': 'String'},
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

    _deferred_server_statuses = ['BUILD',
                                 'HARD_REBOOT',
                                 'PASSWORD',
                                 'REBOOT',
                                 'RESCUE',
                                 'RESIZE',
                                 'REVERT_RESIZE',
                                 'SHUTOFF',
                                 'SUSPENDED',
                                 'VERIFY_RESIZE']

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

    def _build_nics(self, network_interfaces, subnet_id=None):

        nics = None

        if network_interfaces:
            unsorted_nics = []
            for entry in network_interfaces:
                nic = (entry
                       if not isinstance(entry, basestring)
                       else {'NetworkInterfaceId': entry,
                             'DeviceIndex': len(unsorted_nics)})
                unsorted_nics.append(nic)
            sorted_nics = sorted(unsorted_nics,
                                 key=lambda nic: int(nic['DeviceIndex']))
            nics = [{'port-id': nic['NetworkInterfaceId']}
                    for nic in sorted_nics]
        else:
            # if SubnetId property in Instance, ensure subnet exists
            if subnet_id:
                quantumclient = self.quantum()
                network_id = NetworkInterface.network_id_from_subnet_id(
                    quantumclient, subnet_id)
                # if subnet verified, create a port to use this subnet
                # if port is not created explicitly, nova will choose
                # the first subnet in the given network.
                if network_id:
                    fixed_ip = {'subnet_id': subnet_id}
                    props = {
                        'admin_state_up': True,
                        'network_id': network_id,
                        'fixed_ips': [fixed_ip]
                    }
                    port = quantumclient.create_port({'port': props})['port']
                    nics = [{'port-id': port['id']}]

        return nics

    def _get_security_groups(self):
        security_groups = []
        for property in ('SecurityGroups', 'SecurityGroupIds'):
            if self.properties.get(property) is not None:
                for sg in self.properties.get(property):
                    security_groups.append(sg)
        if not security_groups:
            security_groups = None
        return security_groups

    def handle_create(self):
        security_groups = self._get_security_groups()

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

        nics = self._build_nics(self.properties['NetworkInterfaces'],
                                subnet_id=self.properties['SubnetId'])

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

        attach_tasks = (volume.VolumeAttachTask(self.stack,
                                                self.resource_id,
                                                volume_id,
                                                device)
                        for volume_id, device in self.volumes())
        attach_volumes_task = scheduler.PollingTaskGroup(attach_tasks)

        return server, scheduler.TaskRunner(attach_volumes_task)

    def check_create_complete(self, cookie):
        server, volume_attach = cookie

        if not volume_attach.started():
            if server.status != 'ACTIVE':
                server.get()

            if server.status in self._deferred_server_statuses:
                return False
            elif server.status == 'ACTIVE':
                self._set_ipaddress(server.networks)
                volume_attach.start()
                return volume_attach.done()
            else:
                raise exception.Error('%s instance[%s] status[%s]' %
                                      ('nova reported unexpected',
                                       self.name, server.status))
        else:
            return volume_attach.step()

    def volumes(self):
        """
        Return an iterator over (volume_id, device) tuples for all volumes
        that should be attached to this instance.
        """
        volumes = self.properties['Volumes']
        if volumes is None:
            return []

        return ((vol['VolumeId'], vol['Device']) for vol in volumes)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if 'Metadata' in tmpl_diff:
            self.metadata = tmpl_diff.get('Metadata', {})

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
        key_name = self.properties.get('KeyName', None)
        if key_name:
            keypairs = self.nova().keypairs.list()
            if not any(k.name == key_name for k in keypairs):
                return {'Error':
                        'Provided KeyName is not registered with nova'}

        # check validity of security groups vs. network interfaces
        security_groups = self._get_security_groups()
        if security_groups and self.properties.get('NetworkInterfaces'):
            return {'Error':
                    'Cannot define both SecurityGroups/SecurityGroupIds and '
                    'NetworkInterfaces properties.'}

        return

    def _delete_server(self, server):
        '''
        Return a co-routine that deletes the server and waits for it to
        disappear from Nova.
        '''
        server.delete()

        while True:
            yield

            try:
                server.get()
            except clients.novaclient.exceptions.NotFound:
                break

    def handle_delete(self):
        '''
        Delete an instance, blocking until it is disposed by OpenStack
        '''
        if self.resource_id is None:
            return

        detach_tasks = (volume.VolumeDetachTask(self.stack,
                                                self.resource_id,
                                                volume_id)
                        for volume_id, device in self.volumes())
        scheduler.TaskRunner(scheduler.PollingTaskGroup(detach_tasks))()

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            pass
        else:
            delete = scheduler.TaskRunner(self._delete_server, server)
            delete(wait_time=0.2)

        self.resource_id = None


def resource_mapping():
    return {
        'AWS::EC2::Instance': Instance,
        'OS::Heat::HARestarter': Restarter,
    }
