# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from oslo_serialization import jsonutils

from heat.common import identifier
from heat.common import template_format
from heat.engine import environment
from heat.engine.resources.aws.cfn.wait_condition_handle import (
    WaitConditionHandle)
from heat.engine.resources.aws.ec2 import instance
from heat.engine.resources.openstack.nova.server import Server
from heat.engine.scheduler import TaskRunner
from heat.engine import service
from heat.engine import stack as stk
from heat.engine import template as tmpl
from heat.tests import common
from heat.tests import utils


TEST_TEMPLATE_METADATA = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "",
  "Parameters" : {
    "KeyName" : {"Type" : "String", "Default": "mine" },
  },
  "Resources" : {
    "S1": {
      "Type": "AWS::EC2::Instance",
      "Metadata" : {
        "AWS::CloudFormation::Init" : {
          "config" : {
            "files" : {
              "/tmp/random_file" : {
                "content" : { "Fn::Join" : ["", [
                  "s2-ip=", {"Fn::GetAtt": ["S2", "PublicIp"]}
                ]]},
                "mode"    : "000400",
                "owner"   : "root",
                "group"   : "root"
              }
            }
          }
        }
      },
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    },
    "S2": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    }
  }
}
'''

TEST_TEMPLATE_WAIT_CONDITION = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a WaitCondition.",
  "Parameters" : {
    "KeyName" : {"Type" : "String", "Default": "mine" },
  },
  "Resources" : {
    "WH" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },
    "S1": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : { "Fn::Join" : [ "", [ "#!/bin/bash -v\n",
                                                "echo ",
                                                { "Ref" : "WH" },
                                                "\n" ] ] }
      }
    },
    "WC" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "DependsOn": "S1",
      "Properties" : {
        "Handle" : {"Ref" : "WH"},
        "Timeout" : "5"
      }
    },
    "S2": {
      "Type": "AWS::EC2::Instance",
      "Metadata" : {
        "test" : {"Fn::GetAtt": ["WC", "Data"]}
      },
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    }
  }
}
'''


TEST_TEMPLATE_SERVER = '''
heat_template_version: 2013-05-23
resources:
  instance1:
    type: OS::Nova::Server
    metadata: {"template_data": {get_attr: [instance2, networks]}}
    properties:
      image: cirros-0.3.2-x86_64-disk
      flavor: m1.small
      key_name: stack_key
  instance2:
    type: OS::Nova::Server
    metadata: {'apples': 'pears'}
    properties:
      image: cirros-0.3.2-x86_64-disk
      flavor: m1.small
      key_name: stack_key
'''


class MetadataRefreshTests(common.HeatTestCase):

    @mock.patch.object(instance.Instance, 'handle_create')
    @mock.patch.object(instance.Instance, 'check_create_complete')
    @mock.patch.object(instance.Instance, 'FnGetAtt')
    def test_FnGetAtt_metadata_updated(self, mock_get,
                                       mock_check, mock_handle):
        """Tests that metadata gets updated when FnGetAtt return changes."""
        # Setup
        temp = template_format.parse(TEST_TEMPLATE_METADATA)
        template = tmpl.Template(temp,
                                 env=environment.Environment({}))
        ctx = utils.dummy_context()
        stack = stk.Stack(ctx, 'test_stack', template, disable_rollback=True)
        stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()

        # Configure FnGetAtt to return different values on subsequent calls
        mock_get.side_effect = [
            '10.0.0.1',
            '10.0.0.2',
        ]

        # Initial resolution of the metadata
        stack.create()

        # Sanity check on S2
        s2 = stack['S2']
        self.assertEqual((s2.CREATE, s2.COMPLETE), s2.state)

        # Verify S1 is using the initial value from S2
        s1 = stack['S1']
        content = self._get_metadata_content(s1.metadata_get())
        self.assertEqual('s2-ip=10.0.0.1', content)

        # Run metadata update to pick up the new value from S2
        s1.metadata_update()
        s2.metadata_update()

        # Verify the updated value is correct in S1
        content = self._get_metadata_content(s1.metadata_get())
        self.assertEqual('s2-ip=10.0.0.2', content)

        # Verify outgoing calls
        mock_get.assert_has_calls([
            mock.call('PublicIp'),
            mock.call('PublicIp')])
        self.assertEqual(2, mock_handle.call_count)
        self.assertEqual(2, mock_check.call_count)

    @staticmethod
    def _get_metadata_content(m):
        tmp = m['AWS::CloudFormation::Init']['config']['files']
        return tmp['/tmp/random_file']['content']


class WaitConditionMetadataUpdateTests(common.HeatTestCase):

    def setUp(self):
        super(WaitConditionMetadataUpdateTests, self).setUp()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.create_periodic_tasks()

    @mock.patch.object(instance.Instance, 'handle_create')
    @mock.patch.object(instance.Instance, 'check_create_complete')
    @mock.patch.object(instance.Instance, 'is_service_available')
    @mock.patch.object(TaskRunner, '_sleep')
    @mock.patch.object(WaitConditionHandle, 'identifier')
    def test_wait_metadata(self, mock_identifier, mock_sleep, mock_available,
                           mock_check, mock_handle):
        """Tests a wait condition metadata update after a signal call."""

        # Setup Stack
        temp = template_format.parse(TEST_TEMPLATE_WAIT_CONDITION)
        template = tmpl.Template(temp)
        ctx = utils.dummy_context()
        stack = stk.Stack(ctx, 'test-stack', template, disable_rollback=True)
        stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()

        res_id = identifier.ResourceIdentifier('test_tenant_id', stack.name,
                                               stack.id, '', 'WH')
        mock_identifier.return_value = res_id

        watch = stack['WC']
        inst = stack['S2']

        # Setup Sleep Behavior
        self.run_empty = True

        def check_empty(sleep_time):
            self.assertEqual('{}', watch.FnGetAtt('Data'))
            self.assertIsNone(inst.metadata_get()['test'])

        def update_metadata(unique_id, data, reason):
            self.man.resource_signal(ctx,
                                     dict(stack.identifier()),
                                     'WH',
                                     {'Data': data, 'Reason': reason,
                                      'Status': 'SUCCESS',
                                      'UniqueId': unique_id},
                                     sync_call=True)

        def post_success(sleep_time):
            update_metadata('123', 'foo', 'bar')

        def side_effect_popper(sleep_time):
            if self.run_empty:
                self.run_empty = False
                check_empty(sleep_time)
            else:
                post_success(sleep_time)

        mock_sleep.side_effect = side_effect_popper

        # Test Initial Creation
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        self.assertEqual('{"123": "foo"}', watch.FnGetAtt('Data'))
        self.assertEqual('{"123": "foo"}', inst.metadata_get()['test'])

        # Test Update
        update_metadata('456', 'blarg', 'wibble')

        self.assertEqual({'123': 'foo', '456': 'blarg'},
                         jsonutils.loads(watch.FnGetAtt('Data')))
        self.assertEqual('{"123": "foo"}',
                         inst.metadata_get()['test'])
        self.assertEqual(
            {'123': 'foo', '456': 'blarg'},
            jsonutils.loads(inst.metadata_get(refresh=True)['test']))

        # Verify outgoing calls
        self.assertTrue(mock_available.call_count > 0)
        self.assertEqual(2, mock_handle.call_count)
        self.assertEqual(2, mock_check.call_count)


class MetadataRefreshServerTests(common.HeatTestCase):

    @mock.patch.object(Server, 'handle_create')
    @mock.patch.object(Server, 'check_create_complete')
    @mock.patch.object(Server, 'FnGetAtt')
    def test_FnGetAtt_metadata_update(self, mock_get, mock_check, mock_handle):
        temp = template_format.parse(TEST_TEMPLATE_SERVER)
        template = tmpl.Template(temp,
                                 env=environment.Environment({}))
        ctx = utils.dummy_context()
        stack = stk.Stack(ctx, 'test-stack', template, disable_rollback=True)
        stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()

        # Note dummy addresses are from TEST-NET-1 ref rfc5737
        mock_get.side_effect = ['192.0.2.1', '192.0.2.2', '192.0.2.2']

        # Test
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

        s1 = stack['instance1']
        md = s1.metadata_get()
        self.assertEqual({u'template_data': '192.0.2.1'}, md)

        # Now set some metadata via the resource, like is done by
        # _populate_deployments_metadata. This should be persisted over
        # calls to metadata_update()
        new_md = {u'template_data': '192.0.2.2', 'set_by_rsrc': 'orange'}
        s1.metadata_set(new_md)
        md = s1.metadata_get(refresh=True)
        self.assertEqual(new_md, md)
        s1.metadata_update()
        md = s1.metadata_get(refresh=True)
        self.assertEqual(new_md, md)

        # Verify outgoing calls
        mock_get.assert_has_calls([
            mock.call('networks'),
            mock.call('networks')])
        self.assertEqual(2, mock_handle.call_count)
        self.assertEqual(2, mock_check.call_count)
