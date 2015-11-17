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
import uuid

from glanceclient import exc as glance_exceptions
import mock
import mox
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.clients import progress
from heat.engine import environment
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine.resources import scheduler_hints as sh
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "NovaSchedulerHints" : [{"Key": "foo", "Value": "spam"},
                                {"Key": "bar", "Value": "eggs"},
                                {"Key": "foo", "Value": "ham"},
                                {"Key": "foo", "Value": "baz"}],
        "UserData"       : "wordpress",
        "BlockDeviceMappings": [
            {
                "DeviceName": "vdb",
                "Ebs": {"SnapshotId": "9ef5496e-7426-446a-bbc8-01f84d9c9972",
                        "DeleteOnTermination": "True"}
            }],
        "Volumes" : [
            {
                "Device": "/dev/vdc",
                "VolumeId": "cccc"
            },
            {
                "Device": "/dev/vdd",
                "VolumeId": "dddd"
            }]
      }
    }
  }
}
'''


class InstancesTest(common.HeatTestCase):
    def setUp(self):
        super(InstancesTest, self).setUp()
        self.fc = fakes_nova.FakeClient()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        tmpl = template.Template(
            t, env=environment.Environment({'KeyName': 'test'}))
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl,
                             stack_id=str(uuid.uuid4()))
        return (tmpl, stack)

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            imageId_input).MultipleTimes().AndReturn(imageId)

    def _mock_get_image_id_fail(self, image_id, exp):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(image_id).AndRaise(exp)

    def _get_test_template(self, stack_name, image_id=None, volumes=False):
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'ImageId'] = image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties'][
            'InstanceType'] = '256 MB Server'
        if not volumes:
            tmpl.t['Resources']['WebServer']['Properties']['Volumes'] = []

        return tmpl, stack

    def _setup_test_instance(self, return_server, name, image_id=None,
                             stub_create=True, stub_complete=False,
                             volumes=False):
        stack_name = '%s_s' % name
        tmpl, self.stack = self._get_test_template(stack_name, image_id,
                                                   volumes=volumes)
        resource_defns = tmpl.resource_definitions(self.stack)
        instance = instances.Instance(name, resource_defns['WebServer'],
                                      self.stack)
        bdm = {"vdb": "9ef5496e-7426-446a-bbc8-01f84d9c9972:snap::True"}

        self._mock_get_image_id_success(image_id or 'CentOS 5.2', 1)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_SnapshotConstraint_validate()

        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1, flavor=1, key_name='test',
                name=utils.PhysName(
                    stack_name,
                    instance.name,
                    limit=instance.physical_resource_name_limit),
                security_groups=None,
                userdata=mox.IgnoreArg(),
                scheduler_hints={'foo': ['spam', 'ham', 'baz'], 'bar': 'eggs'},
                meta=None, nics=None, availability_zone=None,
                block_device_mapping=bdm).AndReturn(
                    return_server)
            if stub_complete:
                self.m.StubOutWithMock(self.fc.servers, 'get')
                self.fc.servers.get(return_server.id
                                    ).MultipleTimes().AndReturn(return_server)
        return instance

    def _create_test_instance(self, return_server, name,
                              stub_create=True):
        instance = self._setup_test_instance(return_server, name,
                                             stub_create=stub_create,
                                             stub_complete=True)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.m.UnsetStubs()
        return instance

    def _stub_glance_for_update(self, image_id=None):
        self._mock_get_image_id_success(image_id or 'CentOS 5.2', 1)

    def test_instance_create(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_create')
        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        expected_az = getattr(return_server, 'OS-EXT-AZ:availability_zone')

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(instance.resource_id).MultipleTimes(
        ).AndReturn(return_server)
        self.m.ReplayAll()
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_az, instance.FnGetAtt('AvailabilityZone'))

        self.m.VerifyAll()

    def test_instance_create_with_BlockDeviceMappings(self):
        return_server = self.fc.servers.list()[4]
        instance = self._create_test_instance(return_server,
                                              'create_with_bdm')
        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        expected_az = getattr(return_server, 'OS-EXT-AZ:availability_zone')

        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_az, instance.FnGetAtt('AvailabilityZone'))

        self.m.VerifyAll()

    def test_build_block_device_mapping(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_build_bdm')
        self.assertIsNone(instance._build_block_device_mapping([]))
        self.assertIsNone(instance._build_block_device_mapping(None))

        self.assertEqual({
            'vdb': '1234:snap:',
            'vdc': '5678:snap::False',
        }, instance._build_block_device_mapping([
            {'DeviceName': 'vdb', 'Ebs': {'SnapshotId': '1234'}},
            {'DeviceName': 'vdc', 'Ebs': {'SnapshotId': '5678',
                                          'DeleteOnTermination': False}},
        ]))

        self.assertEqual({
            'vdb': '1234:snap:1',
            'vdc': '5678:snap:2:True',
        }, instance._build_block_device_mapping([
            {'DeviceName': 'vdb', 'Ebs': {'SnapshotId': '1234',
                                          'VolumeSize': '1'}},
            {'DeviceName': 'vdc', 'Ebs': {'SnapshotId': '5678',
                                          'VolumeSize': '2',
                                          'DeleteOnTermination': True}},
        ]))

    def test_validate_Volumes_property(self):
        stack_name = 'validate_volumes'
        tmpl, stack = self._setup_test_stack(stack_name)
        volumes = [{'Device': 'vdb', 'VolumeId': '1234'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['Volumes'] = volumes
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('validate_volumes',
                                      resource_defns['WebServer'], stack)
        self.stub_ImageConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.m.StubOutWithMock(cinder.CinderClientPlugin, 'get_volume')
        ex = exception.EntityNotFound(entity='Volume', name='1234')
        cinder.CinderClientPlugin.get_volume('1234').AndRaise(ex)
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                instance.validate)
        self.assertIn("WebServer.Properties.Volumes[0].VolumeId: "
                      "Error validating value '1234': The Volume "
                      "(1234) could not be found.",
                      six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_VolumeSize_valid_str(self):
        stack_name = 'val_VolumeSize_valid'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': '1'}}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['BlockDeviceMappings'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('validate_volume_size',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_success('F17-x86_64-gold', 1)
        self.stub_SnapshotConstraint_validate()
        self.stub_VolumeConstraint_validate()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        self.assertIsNone(instance.validate())

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_Ebs_property(self):
        stack_name = 'without_Ebs'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'DeviceName': 'vdb'}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['BlockDeviceMappings'] = bdm
        wsp['Volumes'] = []
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('validate_without_Ebs',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_success('F17-x86_64-gold', 1)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                instance.validate)
        self.assertIn("Ebs is missing, this is required",
                      six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_SnapshotId_property(self):
        stack_name = 'without_SnapshotId'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'VolumeSize': '1'}}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['BlockDeviceMappings'] = bdm
        wsp['Volumes'] = []
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('validate_without_SnapshotId',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_success('F17-x86_64-gold', 1)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                instance.validate)
        self.assertIn("SnapshotId is missing, this is required",
                      six.text_type(exc))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_DeviceName_property(self):
        stack_name = 'without_DeviceName'
        tmpl, stack = self._setup_test_stack(stack_name)
        bdm = [{'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': '1'}}]
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['BlockDeviceMappings'] = bdm
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('validate_without_DeviceName',
                                      resource_defns['WebServer'], stack)

        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                instance.validate)
        excepted_error = (
            'Property error: '
            'Resources.WebServer.Properties.BlockDeviceMappings[0]: '
            'Property DeviceName not assigned')
        self.assertIn(excepted_error, six.text_type(exc))

        self.m.VerifyAll()

    def test_instance_create_with_image_id(self):
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server,
                                             'in_create_imgid',
                                             image_id='1')

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        expected_ip = return_server.networks['public'][0]
        expected_az = getattr(return_server, 'OS-EXT-AZ:availability_zone')

        self.assertEqual(expected_ip, instance.FnGetAtt('PublicIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateIp'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PublicDnsName'))
        self.assertEqual(expected_ip, instance.FnGetAtt('PrivateDnsName'))
        self.assertEqual(expected_az, instance.FnGetAtt('AvailabilityZone'))

        self.m.VerifyAll()

    def test_instance_create_resolve_az_attribute(self):
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server,
                                             'create_resolve_az_attribute')
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        expected_az = getattr(return_server, 'OS-EXT-AZ:availability_zone')
        actual_az = instance._availability_zone()

        self.assertEqual(expected_az, actual_az)
        self.m.VerifyAll()

    def test_instance_create_image_name_err(self):
        stack_name = 'test_instance_create_image_name_err_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an instance with non exist image name
        tmpl.t['Resources']['WebServer']['Properties']['ImageId'] = 'Slackware'
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('instance_create_image_err',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('Slackware',
                                     exception.EntityNotFound(
                                         entity='Image', name='Slackware'))
        self.stub_VolumeConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(instance.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            "StackValidationFailed: resources.instance_create_image_err: "
            "Property error: "
            "WebServer.Properties.ImageId: Error validating value "
            "'Slackware': The Image (Slackware) could not be found.",
            six.text_type(error))

        self.m.VerifyAll()

    def test_instance_create_duplicate_image_name_err(self):
        stack_name = 'test_instance_create_image_name_err_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an instance with a non unique image name
        wsp = tmpl.t['Resources']['WebServer']['Properties']
        wsp['ImageId'] = 'CentOS 5.2'
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('instance_create_image_err',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('CentOS 5.2',
                                     exception.PhysicalResourceNameAmbiguity(
                                         name='CentOS 5.2'))

        self.stub_KeypairConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.stub_VolumeConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(instance.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            'StackValidationFailed: resources.instance_create_image_err: '
            'Property error: '
            'WebServer.Properties.ImageId: Multiple physical '
            'resources were found with name (CentOS 5.2).',
            six.text_type(error))

        self.m.VerifyAll()

    def test_instance_create_image_id_err(self):
        stack_name = 'test_instance_create_image_id_err_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        # create an instance with non exist image Id
        tmpl.t['Resources']['WebServer']['Properties']['ImageId'] = '1'
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('instance_create_image_err',
                                      resource_defns['WebServer'], stack)

        self._mock_get_image_id_fail('1', glance_exceptions.NotFound(404))

        self.stub_VolumeConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.m.ReplayAll()

        create = scheduler.TaskRunner(instance.create)
        error = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(
            'StackValidationFailed: resources.instance_create_image_err: '
            'Property error: WebServer.Properties.ImageId: 404 (HTTP 404)',
            six.text_type(error))

        self.m.VerifyAll()

    def test_handle_check(self):
        (tmpl, stack) = self._setup_test_stack('test_instance_check_active')
        res_definitions = tmpl.resource_definitions(stack)

        instance = instances.Instance('instance_create_image',
                                      res_definitions['WebServer'], stack)
        instance.client = mock.Mock()
        self.patchobject(nova.NovaClientPlugin, '_check_active',
                         return_value=True)

        self.assertIsNone(instance.handle_check())

    def test_handle_check_raises_exception_if_instance_not_active(self):
        (tmpl, stack) = self._setup_test_stack('test_instance_check_inactive')
        res_definitions = tmpl.resource_definitions(stack)

        instance = instances.Instance('instance_create_image',
                                      res_definitions['WebServer'], stack)
        instance.client = mock.Mock()
        instance.client.return_value.servers.get.return_value.status = 'foo'
        self.patchobject(nova.NovaClientPlugin, '_check_active',
                         return_value=False)

        exc = self.assertRaises(exception.Error, instance.handle_check)
        self.assertIn('foo', six.text_type(exc))

    def test_instance_create_unexpected_status(self):
        # checking via check_create_complete only so not to mock
        # all retry logic on resource creation
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create')

        creator = progress.ServerCreateProgress(instance.resource_id)
        self.m.StubOutWithMock(self.fc.servers, 'get')
        return_server.status = 'BOGUS'
        self.fc.servers.get(instance.resource_id).AndReturn(return_server)
        self.m.ReplayAll()
        e = self.assertRaises(exception.ResourceUnknownStatus,
                              instance.check_create_complete,
                              (creator, None))
        self.assertEqual('Instance is not active - Unknown status BOGUS '
                         'due to "Unknown"', six.text_type(e))
        self.m.VerifyAll()

    def test_instance_create_error_status(self):
        # checking via check_create_complete only so not to mock
        # all retry logic on resource creation
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'test_instance_create')
        creator = progress.ServerCreateProgress(instance.resource_id)
        return_server.status = 'ERROR'
        return_server.fault = {
            'message': 'NoValidHost',
            'code': 500,
            'created': '2013-08-14T03:12:10Z'
        }
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(instance.resource_id).AndReturn(return_server)
        self.m.ReplayAll()

        e = self.assertRaises(exception.ResourceInError,
                              instance.check_create_complete,
                              (creator, None))
        self.assertEqual(
            'Went to status ERROR due to "Message: NoValidHost, Code: 500"',
            six.text_type(e))

        self.m.VerifyAll()

    def test_instance_create_error_no_fault(self):
        # checking via check_create_complete only so not to mock
        # all retry logic on resource creation
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_create')
        creator = progress.ServerCreateProgress(instance.resource_id)
        return_server.status = 'ERROR'

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(instance.resource_id).AndReturn(return_server)
        self.m.ReplayAll()

        e = self.assertRaises(
            exception.ResourceInError, instance.check_create_complete,
            (creator, None))
        self.assertEqual(
            'Went to status ERROR due to "Message: Unknown, Code: Unknown"',
            six.text_type(e))

        self.m.VerifyAll()

    def test_instance_create_with_stack_scheduler_hints(self):
        return_server = self.fc.servers.list()[1]
        sh.cfg.CONF.set_override('stack_scheduler_hints', True)
        # Unroll _create_test_instance, to enable check
        # for addition of heat ids (stack id, resource name)
        stack_name = 'test_instance_create_with_stack_scheduler_hints'
        (t, stack) = self._get_test_template(stack_name)
        resource_defns = t.resource_definitions(stack)
        instance = instances.Instance('in_create_with_sched_hints',
                                      resource_defns['WebServer'], stack)
        bdm = {"vdb": "9ef5496e-7426-446a-bbc8-01f84d9c9972:snap::True"}
        self._mock_get_image_id_success('CentOS 5.2', 1)

        # instance.uuid is only available once the resource has been added.
        stack.add_resource(instance)
        self.assertIsNotNone(instance.uuid)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.stub_SnapshotConstraint_validate()

        self.m.StubOutWithMock(self.fc.servers, 'create')
        shm = sh.SchedulerHintsMixin
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(
                stack_name,
                instance.name,
                limit=instance.physical_resource_name_limit),
            security_groups=None,
            userdata=mox.IgnoreArg(),
            scheduler_hints={shm.HEAT_ROOT_STACK_ID: stack.root_stack_id(),
                             shm.HEAT_STACK_ID: stack.id,
                             shm.HEAT_STACK_NAME: stack.name,
                             shm.HEAT_PATH_IN_STACK: [(None, stack.name)],
                             shm.HEAT_RESOURCE_NAME: instance.name,
                             shm.HEAT_RESOURCE_UUID: instance.uuid,
                             'foo': ['spam', 'ham', 'baz'], 'bar': 'eggs'},
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=bdm).AndReturn(
                return_server)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.assertTrue(instance.id > 0)
        self.m.VerifyAll()

    def test_instance_validate(self):
        stack_name = 'test_instance_validate_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['ImageId'] = '1'
        resource_defns = tmpl.resource_definitions(stack)
        instance = instances.Instance('instance_create_image',
                                      resource_defns['WebServer'], stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)

        self._mock_get_image_id_success('1', 1)
        self.stub_VolumeConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.m.ReplayAll()

        self.assertIsNone(instance.validate())

        self.m.VerifyAll()

    def _test_instance_create_delete(self, vm_status='ACTIVE',
                                     vm_delete_status='NotFound'):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_cr_del')
        instance.resource_id = '1234'
        instance.status = vm_status

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d1['server']['status'] = vm_status

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))

        d2 = copy.deepcopy(d1)
        if vm_delete_status == 'DELETED':
            d2['server']['status'] = vm_delete_status
            get().AndReturn((200, d2))
        else:
            get().AndRaise(fakes_nova.fake_exception())

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.delete)()
        self.assertEqual((instance.DELETE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_create_delete_notfound(self):
        self._test_instance_create_delete()

    def test_instance_create_delete(self):
        self._test_instance_create_delete(vm_delete_status='DELETED')

    def test_instance_create_notfound_on_delete(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_cr_del')
        instance.resource_id = '1234'

        # this makes sure the auto increment worked on instance creation
        self.assertTrue(instance.id > 0)

        self.m.StubOutWithMock(self.fc.client, 'delete_servers_1234')
        self.fc.client.delete_servers_1234().AndRaise(
            fakes_nova.fake_exception())
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.delete)()
        self.assertEqual((instance.DELETE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_metadata(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'ud_md')

        self._stub_glance_for_update()
        ud_tmpl = self._get_test_template('update_stack')[0]
        ud_tmpl.t['Resources']['WebServer']['Metadata'] = {'test': 123}
        resource_defns = ud_tmpl.resource_definitions(instance.stack)
        scheduler.TaskRunner(instance.update, resource_defns['WebServer'])()
        self.assertEqual({'test': 123}, instance.metadata_get())

    def test_instance_update_instance_type(self):
        """Test case for updating InstanceType.

        Instance.handle_update supports changing the InstanceType, and makes
        the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_type')

        self._stub_glance_for_update()
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['InstanceType'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')

        def status_resize(*args):
            return_server.status = 'RESIZE'

        def status_verify_resize(*args):
            return_server.status = 'VERIFY_RESIZE'

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_verify_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_active).AndReturn(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.fc.client.post_servers_1234_action(
            body={'confirmResize': None}).AndReturn((202, None))
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_instance_type_failed(self):
        """Test case for raising exception due to resize call failed.

        If the status after a resize is not VERIFY_RESIZE, it means the resize
        call failed, so we raise an explicit error.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_type_f')

        self._stub_glance_for_update()
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['InstanceType'] = 'm1.small'

        self.m.StubOutWithMock(self.fc.servers, 'get')

        def status_resize(*args):
            return_server.status = 'RESIZE'

        def status_error(*args):
            return_server.status = 'ERROR'

        self.fc.servers.get('1234').AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_resize).AndReturn(return_server)
        self.fc.servers.get('1234').WithSideEffects(
            status_error).AndReturn(return_server)

        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 2}}).AndReturn((202, None))
        self.m.ReplayAll()

        updater = scheduler.TaskRunner(instance.update, update_template)
        error = self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual(
            "Error: resources.ud_type_f: "
            "Resizing to 'm1.small' failed, status 'ERROR'",
            six.text_type(error))
        self.assertEqual((instance.UPDATE, instance.FAILED), instance.state)
        self.m.VerifyAll()

    def create_fake_iface(self, port, net, ip):
        class fake_interface(object):
            def __init__(self, port_id, net_id, fixed_ip):
                self.port_id = port_id
                self.net_id = net_id
                self.fixed_ips = [{'ip_address': fixed_ip}]

        return fake_interface(port, net, ip)

    def test_instance_update_network_interfaces(self):
        """Test case for updating NetworkInterfaces.

        Instance.handle_update supports changing the NetworkInterfaces,
        and makes the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        # if new overlaps with old, detach the different ones in old, and
        # attach the different ones in new
        old_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'},
            {'NetworkInterfaceId': 'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
             'DeviceIndex': '1'}]
        new_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'},
            {'NetworkInterfaceId': '34b752ec-14de-416a-8722-9531015e04a5',
             'DeviceIndex': '3'}]

        instance.t['Properties']['NetworkInterfaces'] = old_interfaces
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = new_interfaces

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46').AndReturn(None)
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach('34b752ec-14de-416a-8722-9531015e04a5',
                                       None, None).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_network_interfaces_old_include_new(self):
        """Test case for updating NetworkInterfaces when old prop includes new.

        Instance.handle_update supports changing the NetworkInterfaces,
        and makes the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        # if old include new, just detach the different ones in old
        old_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'},
            {'NetworkInterfaceId': 'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
             'DeviceIndex': '1'}]
        new_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'}]

        instance.t['Properties']['NetworkInterfaces'] = old_interfaces
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = new_interfaces

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)

    def test_instance_update_network_interfaces_new_include_old(self):
        """Test case for updating NetworkInterfaces when new prop includes old.

        Instance.handle_update supports changing the NetworkInterfaces,
        and makes the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        # if new include old, just attach the different ones in new
        old_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'}]
        new_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'},
            {'NetworkInterfaceId': 'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
             'DeviceIndex': '1'}]

        instance.t['Properties']['NetworkInterfaces'] = old_interfaces
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = new_interfaces

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach('d1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
                                       None, None).AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)

    def test_instance_update_network_interfaces_new_old_all_different(self):
        """Tests updating NetworkInterfaces when new and old are different.

        Instance.handle_update supports changing the NetworkInterfaces,
        and makes the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        # if different, detach the old ones and attach the new ones
        old_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'}]
        new_interfaces = [
            {'NetworkInterfaceId': '34b752ec-14de-416a-8722-9531015e04a5',
             'DeviceIndex': '3'},
            {'NetworkInterfaceId': 'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
             'DeviceIndex': '1'}]

        instance.t['Properties']['NetworkInterfaces'] = old_interfaces
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = new_interfaces

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'ea29f957-cd35-4364-98fb-57ce9732c10d').AndReturn(None)
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach('d1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
                                       None, None).InAnyOrder().AndReturn(None)
        return_server.interface_attach('34b752ec-14de-416a-8722-9531015e04a5',
                                       None, None).InAnyOrder().AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)

    def test_instance_update_network_interfaces_no_old(self):
        """Test case for updating NetworkInterfaces when there's no old prop.

        Instance.handle_update supports changing the NetworkInterfaces,
        and makes the change making a resize API call against Nova.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        new_interfaces = [
            {'NetworkInterfaceId': 'ea29f957-cd35-4364-98fb-57ce9732c10d',
             'DeviceIndex': '2'},
            {'NetworkInterfaceId': '34b752ec-14de-416a-8722-9531015e04a5',
             'DeviceIndex': '3'}]
        iface = self.create_fake_iface('d1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
                                       'c4485ba1-283a-4f5f-8868-0cd46cdda52f',
                                       '10.0.0.4')

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = new_interfaces

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().AndReturn([iface])
        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46').AndReturn(None)
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach('ea29f957-cd35-4364-98fb-57ce9732c10d',
                                       None, None).AndReturn(None)
        return_server.interface_attach('34b752ec-14de-416a-8722-9531015e04a5',
                                       None, None).AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_network_interfaces_no_old_empty_new(self):
        """Test case for updating NetworkInterfaces when no old, no new prop.

        Instance.handle_update supports changing the NetworkInterfaces.
        """
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server,
                                              'ud_network_interfaces')
        self._stub_glance_for_update()
        iface = self.create_fake_iface('d1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
                                       'c4485ba1-283a-4f5f-8868-0cd46cdda52f',
                                       '10.0.0.4')

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['NetworkInterfaces'] = []

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get('1234').MultipleTimes().AndReturn(return_server)
        self.m.StubOutWithMock(return_server, 'interface_list')
        return_server.interface_list().AndReturn([iface])
        self.m.StubOutWithMock(return_server, 'interface_detach')
        return_server.interface_detach(
            'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46').AndReturn(None)
        self.m.StubOutWithMock(return_server, 'interface_attach')
        return_server.interface_attach(None, None, None).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def _test_instance_update_with_subnet(self, stack_name,
                                          new_interfaces=None,
                                          old_interfaces=None,
                                          need_update=True,
                                          multiple_get=True):
        return_server = self.fc.servers.list()[1]
        return_server.id = '1234'
        instance = self._create_test_instance(return_server, stack_name)
        self._stub_glance_for_update()
        iface = self.create_fake_iface('d1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
                                       'c4485ba1-283a-4f5f-8868-0cd46cdda52f',
                                       '10.0.0.4')
        subnet_id = '8c1aaddf-e49e-4f28-93ea-ca9f0b3c6240'
        nics = [{'port-id': 'ea29f957-cd35-4364-98fb-57ce9732c10d'}]
        if old_interfaces is not None:
            instance.t['Properties']['NetworkInterfaces'] = old_interfaces
        update_template = copy.deepcopy(instance.t)
        if new_interfaces is not None:
            update_template['Properties']['NetworkInterfaces'] = new_interfaces
        update_template['Properties']['SubnetId'] = subnet_id

        self.m.StubOutWithMock(self.fc.servers, 'get')

        if need_update:
            if multiple_get:
                self.fc.servers.get('1234').MultipleTimes().AndReturn(
                    return_server)
            else:
                self.fc.servers.get('1234').AndReturn(return_server)
            self.m.StubOutWithMock(return_server, 'interface_list')
            return_server.interface_list().AndReturn([iface])
            self.m.StubOutWithMock(return_server, 'interface_detach')
            return_server.interface_detach(
                'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46').AndReturn(None)
            self.m.StubOutWithMock(instance, '_build_nics')
            instance._build_nics(new_interfaces, security_groups=None,
                                 subnet_id=subnet_id).AndReturn(nics)
            self.m.StubOutWithMock(return_server, 'interface_attach')
            return_server.interface_attach(
                'ea29f957-cd35-4364-98fb-57ce9732c10d',
                None, None).AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_instance_update_network_interfaces_empty_new_with_subnet(self):
        """Test update NetworkInterfaces to empty, and update with subnet."""
        stack_name = 'ud_network_interfaces_empty_with_subnet'
        self._test_instance_update_with_subnet(
            stack_name, new_interfaces=[])

    def test_instance_update_no_old_no_new_with_subnet(self):
        stack_name = 'ud_only_with_subnet'
        self._test_instance_update_with_subnet(stack_name)

    def test_instance_update_old_no_change_with_subnet(self):
        # Test if there is old network interface and no change of
        # it, will do nothing when updating.
        old_interfaces = [
            {'NetworkInterfaceId': 'd1e9c73c-04fe-4e9e-983c-d5ef94cd1a46',
             'DeviceIndex': '2'}]
        stack_name = 'ud_old_no_change_only_with_subnet'
        self._test_instance_update_with_subnet(stack_name,
                                               old_interfaces=old_interfaces,
                                               need_update=False,
                                               multiple_get=False)

    def test_instance_update_properties(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_update2')

        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['ImageId'] = 'mustreplace'
        updater = scheduler.TaskRunner(instance.update, update_template)
        self.assertRaises(exception.UpdateReplace, updater)

        self.m.VerifyAll()

    def test_instance_status_build(self):
        return_server = self.fc.servers.list()[0]
        instance = self._setup_test_instance(return_server,
                                             'in_sts_build')
        instance.resource_id = '1234'

        self.m.StubOutWithMock(self.fc.servers, 'get')

        # Bind fake get method which Instance.check_create_complete will call
        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get(instance.resource_id).WithSideEffects(
            status_active).MultipleTimes().AndReturn(return_server)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def _test_instance_status_suspend(self, name,
                                      state=('CREATE', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server, name)

        instance.resource_id = '1234'
        instance.state_set(state[0], state[1])

        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'ACTIVE'
        d2['server']['status'] = 'SUSPENDED'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.suspend)()
        self.assertEqual((instance.SUSPEND, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_suspend_in_create_complete(self):
        self._test_instance_status_suspend(
            name='test_suspend_in_create_complete')

    def test_instance_suspend_in_suspend_failed(self):
        self._test_instance_status_suspend(
            name='test_suspend_in_suspend_failed',
            state=('SUSPEND', 'FAILED'))

    def test_instance_suspend_in_suspend_complete(self):
        self._test_instance_status_suspend(
            name='test_suspend_in_suspend_complete',
            state=('SUSPEND', 'COMPLETE'))

    def _test_instance_status_resume(self, name,
                                     state=('SUSPEND', 'COMPLETE')):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server, name)

        instance.resource_id = '1234'
        instance.state_set(state[0], state[1])

        d1 = {'server': self.fc.client.get_servers_detail()[1]['servers'][0]}
        d2 = copy.deepcopy(d1)
        d1['server']['status'] = 'SUSPENDED'
        d2['server']['status'] = 'ACTIVE'
        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndReturn((200, d1))
        get().AndReturn((200, d1))
        get().AndReturn((200, d2))
        self.m.ReplayAll()

        instance.state_set(instance.SUSPEND, instance.COMPLETE)

        scheduler.TaskRunner(instance.resume)()
        self.assertEqual((instance.RESUME, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_instance_resume_in_suspend_complete(self):
        self._test_instance_status_resume(
            name='test_resume_in_suspend_complete')

    def test_instance_resume_in_resume_failed(self):
        self._test_instance_status_resume(
            name='test_resume_in_resume_failed',
            state=('RESUME', 'FAILED'))

    def test_instance_resume_in_resume_complete(self):
        self._test_instance_status_resume(
            name='test_resume_in_resume_complete',
            state=('RESUME', 'COMPLETE'))

    def test_instance_resume_other_exception(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'in_resume_wait')

        instance.resource_id = '1234'
        self.m.ReplayAll()

        self.m.StubOutWithMock(self.fc.client, 'get_servers_1234')
        get = self.fc.client.get_servers_1234
        get().AndRaise(fakes_nova.fake_exception(status_code=500,
                                                 message='VIKINGS!'))
        self.m.ReplayAll()

        instance.state_set(instance.SUSPEND, instance.COMPLETE)

        resumer = scheduler.TaskRunner(instance.resume)
        ex = self.assertRaises(exception.ResourceFailure, resumer)
        self.assertIn('VIKINGS!', ex.message)

        self.m.VerifyAll()

    def test_instance_status_build_spawning(self):
        self._test_instance_status_not_build_active('BUILD(SPAWNING)')

    def test_instance_status_hard_reboot(self):
        self._test_instance_status_not_build_active('HARD_REBOOT')

    def test_instance_status_password(self):
        self._test_instance_status_not_build_active('PASSWORD')

    def test_instance_status_reboot(self):
        self._test_instance_status_not_build_active('REBOOT')

    def test_instance_status_rescue(self):
        self._test_instance_status_not_build_active('RESCUE')

    def test_instance_status_resize(self):
        self._test_instance_status_not_build_active('RESIZE')

    def test_instance_status_revert_resize(self):
        self._test_instance_status_not_build_active('REVERT_RESIZE')

    def test_instance_status_shutoff(self):
        self._test_instance_status_not_build_active('SHUTOFF')

    def test_instance_status_suspended(self):
        self._test_instance_status_not_build_active('SUSPENDED')

    def test_instance_status_verify_resize(self):
        self._test_instance_status_not_build_active('VERIFY_RESIZE')

    def _test_instance_status_not_build_active(self, uncommon_status):
        return_server = self.fc.servers.list()[0]
        instance = self._setup_test_instance(return_server,
                                             'in_sts_bld')
        instance.resource_id = '1234'

        self.m.StubOutWithMock(self.fc.servers, 'get')

        # Bind fake get method which Instance.check_create_complete will call
        def status_not_build(*args):
            return_server.status = uncommon_status

        def status_active(*args):
            return_server.status = 'ACTIVE'

        self.fc.servers.get(instance.resource_id).WithSideEffects(
            status_not_build).AndReturn(return_server)
        self.fc.servers.get(instance.resource_id).WithSideEffects(
            status_active).MultipleTimes().AndReturn(return_server)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)

        self.m.VerifyAll()

    def test_build_nics(self):
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'build_nics')

        self.assertIsNone(instance._build_nics([]))
        self.assertIsNone(instance._build_nics(None))
        self.assertEqual([
            {'port-id': 'id3'}, {'port-id': 'id1'}, {'port-id': 'id2'}],
            instance._build_nics([
                'id3', 'id1', 'id2']))
        self.assertEqual(
            [{'port-id': 'id1'},
             {'port-id': 'id2'},
             {'port-id': 'id3'}],
            instance._build_nics([
                {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
                {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
                {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
            ]))
        self.assertEqual(
            [{'port-id': 'id1'},
             {'port-id': 'id2'},
             {'port-id': 'id3'},
             {'port-id': 'id4'},
             {'port-id': 'id5'}],
            instance._build_nics([
                {'NetworkInterfaceId': 'id3', 'DeviceIndex': '3'},
                {'NetworkInterfaceId': 'id1', 'DeviceIndex': '1'},
                {'NetworkInterfaceId': 'id2', 'DeviceIndex': 2},
                'id4',
                'id5']
            ))

    def test_build_nics_with_security_groups(self):
        """Test the security groups can be associated to a new created port.

        Test the security groups defined in heat template can be associated to
        a new created port.
        """
        return_server = self.fc.servers.list()[1]
        instance = self._create_test_instance(return_server,
                                              'build_nics2')

        security_groups = ['security_group_1']
        self._test_security_groups(instance, security_groups)

        security_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        self._test_security_groups(instance, security_groups, all_uuids=True)

        security_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3',
                           '384ccd91-447c-4d83-832c-06974a7d3d05']
        self._test_security_groups(instance, security_groups,
                                   sg='two', all_uuids=True)

        security_groups = ['security_group_1',
                           '384ccd91-447c-4d83-832c-06974a7d3d05']
        self._test_security_groups(instance, security_groups, sg='two')

        security_groups = ['wrong_group_name']
        self._test_security_groups(
            instance,
            security_groups,
            sg='zero',
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['wrong_group_name',
                           '0389f747-7785-4757-b7bb-2ab07e4b09c3']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['wrong_group_name', 'security_group_1']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNotFound)

        security_groups = ['duplicate_group_name', 'security_group_1']
        self._test_security_groups(
            instance,
            security_groups,
            get_secgroup_raises=exception.PhysicalResourceNameAmbiguity)

    def _test_security_groups(self, instance, security_groups, sg='one',
                              all_uuids=False, get_secgroup_raises=None):
        fake_groups_list, props = self._get_fake_properties(sg)

        nclient = neutronclient.Client()
        self.m.StubOutWithMock(instance, 'neutron')
        instance.neutron().MultipleTimes().AndReturn(nclient)

        if not all_uuids:
            # list_security_groups only gets called when none of the requested
            # groups look like UUIDs.
            self.m.StubOutWithMock(
                neutronclient.Client, 'list_security_groups')
            neutronclient.Client.list_security_groups().AndReturn(
                fake_groups_list)
        self.m.StubOutWithMock(neutron.NeutronClientPlugin,
                               'network_id_from_subnet_id')
        neutron.NeutronClientPlugin.network_id_from_subnet_id(
            'fake_subnet_id').MultipleTimes().AndReturn('fake_network_id')

        if not get_secgroup_raises:
            self.m.StubOutWithMock(neutronclient.Client, 'create_port')
            neutronclient.Client.create_port(
                {'port': props}).MultipleTimes().AndReturn(
                    {'port': {'id': 'fake_port_id'}})
        self.stub_keystoneclient()
        self.m.ReplayAll()

        if get_secgroup_raises:
            self.assertRaises(get_secgroup_raises, instance._build_nics, None,
                              security_groups=security_groups,
                              subnet_id='fake_subnet_id')
        else:
            self.assertEqual(
                [{'port-id': 'fake_port_id'}],
                instance._build_nics(None,
                                     security_groups=security_groups,
                                     subnet_id='fake_subnet_id'))

        self.m.VerifyAll()
        self.m.UnsetStubs()

    def _get_fake_properties(self, sg='one'):
        fake_groups_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_2',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'test_tenant_id',
                    'id': 'e91a0007-06a6-4a4a-8edb-1d91315eb0ef',
                    'name': 'duplicate_group_name',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '8be37f3c-176d-4826-aa17-77d1d9df7b2e',
                    'name': 'duplicate_group_name',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }

        fixed_ip = {'subnet_id': 'fake_subnet_id'}
        props = {
            'admin_state_up': True,
            'network_id': 'fake_network_id',
            'fixed_ips': [fixed_ip],
            'security_groups': ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        }

        if sg == 'zero':
            props['security_groups'] = []
        elif sg == 'one':
            props['security_groups'] = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        elif sg == 'two':
            props['security_groups'] = ['0389f747-7785-4757-b7bb-2ab07e4b09c3',
                                        '384ccd91-447c-4d83-832c-06974a7d3d05']

        return fake_groups_list, props

    def test_instance_without_ip_address(self):
        return_server = self.fc.servers.list()[3]
        instance = self._create_test_instance(return_server,
                                              'wo_ipaddr')

        self.assertEqual('0.0.0.0', instance.FnGetAtt('PrivateIp'))

    def test_default_instance_user(self):
        """CFN instances automatically create the `ec2-user` admin user."""
        return_server = self.fc.servers.list()[1]
        instance = self._setup_test_instance(return_server, 'default_user')
        metadata = instance.metadata_get()
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'build_userdata')
        nova.NovaClientPlugin.build_userdata(
            metadata, 'wordpress', 'ec2-user')
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.m.VerifyAll()

    def test_instance_create_with_volumes(self):
        return_server = self.fc.servers.list()[1]
        self.stub_VolumeConstraint_validate()
        instance = self._setup_test_instance(return_server,
                                             'with_volumes',
                                             stub_complete=True,
                                             volumes=True)
        attach_mock = self.patchobject(nova.NovaClientPlugin, 'attach_volume',
                                       side_effect=['cccc', 'dddd'])
        check_attach_mock = self.patchobject(cinder.CinderClientPlugin,
                                             'check_attach_volume_complete',
                                             side_effect=[False, True,
                                                          False, True])
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.assertEqual(2, attach_mock.call_count)
        attach_mock.assert_has_calls([mock.call(instance.resource_id,
                                                'cccc', '/dev/vdc'),
                                      mock.call(instance.resource_id,
                                                'dddd', '/dev/vdd')])
        self.assertEqual(4, check_attach_mock.call_count)
        check_attach_mock.assert_has_calls([mock.call('cccc'),
                                            mock.call('cccc'),
                                            mock.call('dddd'),
                                            mock.call('dddd')])
        self.m.VerifyAll()
