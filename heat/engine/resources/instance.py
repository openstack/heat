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

from heat.engine import signal_responder
from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler
from heat.engine.resources import nova_utils
from heat.engine.resources import volume

from heat.common import exception
from heat.engine.resources.network_interface import NetworkInterface

from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class Restarter(signal_responder.SignalResponder):
    properties_schema = {
        'InstanceId': {
            'Type': 'String',
            'Required': True,
            'Description': _('Instance ID to be restarted.')}}
    attributes_schema = {
        "AlarmUrl": _("A signed url to handle the alarm "
                      "(Heat extension).")
    }

    def _find_resource(self, resource_id):
        '''
        Return the resource with the specified instance ID, or None if it
        cannot be found.
        '''
        for resource in self.stack:
            if resource.resource_id == resource_id:
                return resource
        return None

    def handle_signal(self, details=None):
        if details is None:
            alarm_state = 'alarm'
        else:
            alarm_state = details.get('state', 'alarm').lower()

        logger.info('%s Alarm, new state %s' % (self.name, alarm_state))

        if alarm_state != 'alarm':
            return

        victim = self._find_resource(self.properties['InstanceId'])
        if victim is None:
            logger.info('%s Alarm, can not find instance %s' %
                       (self.name, self.properties['InstanceId']))
            return

        logger.info('%s Alarm, restarting resource: %s' %
                    (self.name, victim.name))
        self.stack.restart_resource(victim.name)

    def _resolve_attribute(self, name):
        '''
        heat extension: "AlarmUrl" returns the url to post to the policy
        when there is an alarm.
        '''
        if name == 'AlarmUrl' and self.resource_id is not None:
            return unicode(self._get_signed_url())


class Instance(resource.Resource):
    # AWS does not require InstanceType but Heat does because the nova
    # create api call requires a flavor
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'ImageId': {
            'Type': 'String',
            'Required': True,
            'Description': _('Glance image ID or name.')},
        'InstanceType': {
            'Type': 'String',
            'Required': True,
            'Description': _('Nova instance type (flavor).')},
        'KeyName': {
            'Type': 'String',
            'Description': _('Optional Nova keypair name.')},
        'AvailabilityZone': {
            'Type': 'String',
            'Description': _('Availability zone to launch the instance in.')},
        'DisableApiTermination': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'KernelId': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'Monitoring': {
            'Type': 'Boolean',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'PlacementGroupName': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'PrivateIpAddress': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'RamDiskId': {
            'Type': 'String',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'SecurityGroups': {
            'Type': 'List',
            'Description': _('Security group names to assign.')},
        'SecurityGroupIds': {
            'Type': 'List',
            'Description': _('Security group IDs to assign.')},
        'NetworkInterfaces': {
            'Type': 'List',
            'Description': _('Network interfaces to associate with '
                             'instance.')},
        'SourceDestCheck': {
            'Type': 'Boolean',
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'SubnetId': {
            'Type': 'String',
            'Description': _('Subnet ID to launch instance in.')},
        'Tags': {
            'Type': 'List',
            'Schema': {'Type': 'Map', 'Schema': tags_schema},
            'Description': _('Tags to attach to instance.')},
        'NovaSchedulerHints': {
            'Type': 'List',
            'Schema': {'Type': 'Map', 'Schema': tags_schema},
            'Description': _('Scheduler hints to pass '
                             'to Nova (Heat extension).')},
        'Tenancy': {
            'Type': 'String',
            'AllowedValues': ['dedicated', 'default'],
            'Implemented': False,
            'Description': _('Not Implemented.')},
        'UserData': {
            'Type': 'String',
            'Description': _('User data to pass to instance.')},
        'Volumes': {
            'Type': 'List',
            'Description': _('Volumes to attach to instance.')}}

    attributes_schema = {'AvailabilityZone': _('The Availability Zone where '
                                               'the specified instance is '
                                               'launched.'),
                         'PrivateDnsName': _('Private DNS name of the'
                                             ' specified instance.'),
                         'PublicDnsName': _('Public DNS name of the specified '
                                            'instance.'),
                         'PrivateIp': _('Private IP address of the specified '
                                        'instance.'),
                         'PublicIp': _('Public IP address of the specified '
                                       'instance.')}

    update_allowed_keys = ('Metadata', 'Properties')
    update_allowed_properties = ('InstanceType',)

    # Server host name limit to 53 characters by due to typical default
    # linux HOST_NAME_MAX of 64, minus the .novalocal appended to the name
    physical_resource_name_limit = 53

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
            if len(networks[n]) > 0:
                self.ipaddress = networks[n][0]
                break

    def _ipaddress(self):
        '''
        Return the server's IP address, fetching it from Nova if necessary
        '''
        if self.ipaddress is None:
            self.ipaddress = nova_utils.server_to_ipaddress(
                self.nova(), self.resource_id)

        return self.ipaddress or '0.0.0.0'

    def _resolve_attribute(self, name):
        res = None
        if name == 'AvailabilityZone':
            res = self.properties['AvailabilityZone']
        elif name in ['PublicIp', 'PrivateIp', 'PublicDnsName',
                      'PrivateDnsName']:
            res = self._ipaddress()

        logger.info('%s._resolve_attribute(%s) == %s' % (self.name, name, res))
        return unicode(res) if res else None

    def _build_nics(self, network_interfaces,
                    security_groups=None, subnet_id=None):

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
                neutronclient = self.neutron()
                network_id = NetworkInterface.network_id_from_subnet_id(
                    neutronclient, subnet_id)
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

                    if security_groups:
                        props['security_groups'] = \
                            self._get_security_groups_id(security_groups)

                    port = neutronclient.create_port({'port': props})['port']
                    nics = [{'port-id': port['id']}]

        return nics

    def _get_security_groups_id(self, security_groups):
        """Extract security_groups ids from security group list

        This function will be deprecated if Neutron client resolves security
        group name to id internally.

        Args:
            security_groups : A list contains security_groups ids or names
        Returns:
            A list of security_groups ids.
        """
        ids = []
        response = self.neutron().list_security_groups(self.resource_id)
        for item in response:
            if item['security_groups'] is not None:
                for security_group in security_groups:
                    for groups in item['security_groups']:
                        if groups['name'] == security_group \
                                and groups['id'] not in ids:
                            ids.append(groups['id'])
                        elif groups['id'] == security_group \
                                and groups['id'] not in ids:
                            ids.append(groups['id'])
        return ids

    def _get_security_groups(self):
        security_groups = []
        for property in ('SecurityGroups', 'SecurityGroupIds'):
            if self.properties.get(property) is not None:
                for sg in self.properties.get(property):
                    security_groups.append(sg)
        if not security_groups:
            security_groups = None
        return security_groups

    def get_mime_string(self, userdata):
        if not self.mime_string:
            self.mime_string = nova_utils.build_userdata(self, userdata)
        return self.mime_string

    def handle_create(self):
        security_groups = self._get_security_groups()

        userdata = self.properties['UserData'] or ''
        flavor = self.properties['InstanceType']
        availability_zone = self.properties['AvailabilityZone']

        key_name = self.properties['KeyName']
        if key_name:
            # confirm keypair exists
            nova_utils.get_keypair(self.nova(), key_name)

        image_name = self.properties['ImageId']

        image_id = nova_utils.get_image_id(self.nova(), image_name)

        flavor_id = nova_utils.get_flavor_id(self.nova(), flavor)

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
                                security_groups=security_groups,
                                subnet_id=self.properties['SubnetId'])
        server = None

        try:
            server = self.nova().servers.create(
                name=self.physical_resource_name(),
                image=image_id,
                flavor=flavor_id,
                key_name=key_name,
                security_groups=security_groups,
                userdata=self.get_mime_string(userdata),
                meta=tags,
                scheduler_hints=scheduler_hints,
                nics=nics,
                availability_zone=availability_zone)
        finally:
            # Avoid a race condition where the thread could be cancelled
            # before the ID is stored
            if server is not None:
                self.resource_id_set(server.id)

        return server, scheduler.TaskRunner(self._attach_volumes_task())

    def _attach_volumes_task(self):
        attach_tasks = (volume.VolumeAttachTask(self.stack,
                                                self.resource_id,
                                                volume_id,
                                                device)
                        for volume_id, device in self.volumes())
        return scheduler.PollingTaskGroup(attach_tasks)

    def check_create_complete(self, cookie):
        return self._check_active(cookie)

    def _check_active(self, cookie):
        server, volume_attach = cookie

        if not volume_attach.started():
            if server.status != 'ACTIVE':
                server.get()

            # Some clouds append extra (STATUS) strings to the status
            short_server_status = server.status.split('(')[0]
            if short_server_status in nova_utils.deferred_server_statuses:
                return False
            elif server.status == 'ACTIVE':
                self._set_ipaddress(server.networks)
                volume_attach.start()
                return volume_attach.done()
            elif server.status == 'ERROR':
                fault = getattr(server, 'fault', {})
                message = fault.get('message', 'Unknown')
                code = fault.get('code', 500)
                exc = exception.Error(_("Creation of server %(server)s "
                                        "failed: %(message)s (%(code)s)") %
                                      dict(server=server.name,
                                           message=message,
                                           code=code))
                raise exc
            else:
                exc = exception.Error(_("Creation of server %(server)s failed "
                                        "with unknown status: %(status)s") %
                                      dict(server=server.name,
                                           status=server.status))
                raise exc
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
            self.metadata = tmpl_diff['Metadata']
        if 'InstanceType' in prop_diff:
            flavor = prop_diff['InstanceType']
            flavor_id = nova_utils.get_flavor_id(self.nova(), flavor)
            server = self.nova().servers.get(self.resource_id)
            server.resize(flavor_id)
            checker = scheduler.TaskRunner(nova_utils.check_resize,
                                           server, flavor)
            checker.start()
            return checker

    def check_update_complete(self, checker):
        return checker.step() if checker is not None else True

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
            nova_utils.get_keypair(self.nova(), key_name)

        # check validity of security groups vs. network interfaces
        security_groups = self._get_security_groups()
        if security_groups and self.properties.get('NetworkInterfaces'):
            raise exception.ResourcePropertyConflict(
                'SecurityGroups/SecurityGroupIds',
                'NetworkInterfaces')

        # make sure the image exists.
        nova_utils.get_image_id(self.nova(), self.properties['ImageId'])

    @scheduler.wrappertask
    def _delete_server(self, server):
        '''
        Return a co-routine that deletes the server and waits for it to
        disappear from Nova.
        '''
        yield self._detach_volumes_task()()
        server.delete()

        while True:
            yield

            try:
                server.get()
            except clients.novaclient.exceptions.NotFound:
                self.resource_id = None
                break

    def _detach_volumes_task(self):
        '''
        Detach volumes from the instance
        '''
        detach_tasks = (volume.VolumeDetachTask(self.stack,
                                                self.resource_id,
                                                volume_id)
                        for volume_id, device in self.volumes())
        return scheduler.PollingTaskGroup(detach_tasks)

    def handle_delete(self):
        '''
        Delete an instance, blocking until it is disposed by OpenStack
        '''
        if self.resource_id is None:
            return

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            self.resource_id = None
            return

        server_delete_task = scheduler.TaskRunner(self._delete_server,
                                                  server=server)
        server_delete_task.start()
        return server_delete_task

    def check_delete_complete(self, server_delete_task):
        # if the resource was already deleted, server_delete_task will be None
        if server_delete_task is None:
            return True
        else:
            return server_delete_task.step()

    def handle_suspend(self):
        '''
        Suspend an instance - note we do not wait for the SUSPENDED state,
        this is polled for by check_suspend_complete in a similar way to the
        create logic so we can take advantage of coroutines
        '''
        if self.resource_id is None:
            raise exception.Error(_('Cannot suspend %s, resource_id not set') %
                                  self.name)

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            raise exception.NotFound(_('Failed to find instance %s') %
                                     self.resource_id)
        else:
            logger.debug("suspending instance %s" % self.resource_id)
            # We want the server.suspend to happen after the volume
            # detachement has finished, so pass both tasks and the server
            suspend_runner = scheduler.TaskRunner(server.suspend)
            volumes_runner = scheduler.TaskRunner(self._detach_volumes_task())
            return server, suspend_runner, volumes_runner

    def check_suspend_complete(self, cookie):
        server, suspend_runner, volumes_runner = cookie

        if not volumes_runner.started():
            volumes_runner.start()

        if volumes_runner.done():
            if not suspend_runner.started():
                suspend_runner.start()

            if suspend_runner.done():
                if server.status == 'SUSPENDED':
                    return True

                server.get()
                logger.debug("%s check_suspend_complete status = %s" %
                             (self.name, server.status))
                if server.status in list(nova_utils.deferred_server_statuses +
                                         ['ACTIVE']):
                    return server.status == 'SUSPENDED'
                else:
                    raise exception.Error(_(' nova reported unexpected '
                                            'instance[%(instance)s] '
                                            'status[%(status)s]') %
                                          {'instance': self.name,
                                           'status': server.status})
            else:
                suspend_runner.step()
        else:
            return volumes_runner.step()

    def handle_resume(self):
        '''
        Resume an instance - note we do not wait for the ACTIVE state,
        this is polled for by check_resume_complete in a similar way to the
        create logic so we can take advantage of coroutines
        '''
        if self.resource_id is None:
            raise exception.Error(_('Cannot resume %s, resource_id not set') %
                                  self.name)

        try:
            server = self.nova().servers.get(self.resource_id)
        except clients.novaclient.exceptions.NotFound:
            raise exception.NotFound(_('Failed to find instance %s') %
                                     self.resource_id)
        else:
            logger.debug("resuming instance %s" % self.resource_id)
            server.resume()
            return server, scheduler.TaskRunner(self._attach_volumes_task())

    def check_resume_complete(self, cookie):
        return self._check_active(cookie)


def resource_mapping():
    return {
        'AWS::EC2::Instance': Instance,
        'OS::Heat::HARestarter': Restarter,
    }
