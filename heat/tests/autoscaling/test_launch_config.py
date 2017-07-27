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

import mock
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


class LaunchConfigurationTest(common.HeatTestCase):
    def validate_launch_config(self, stack, lc_name='LaunchConfig'):
        # create the launch configuration resource
        conf = stack[lc_name]
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)
        # check bdm in configuration
        self.assertIsNotNone(conf.properties['BlockDeviceMappings'])

    def test_launch_config_get_ref_by_id(self):
        t = template_format.parse(inline_templates.as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['LaunchConfig']
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # use physical_resource_name when rsrc.id is not None
        self.assertIsNotNone(rsrc.uuid)
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.uuid))
        self.assertEqual(expected, rsrc.FnGetRefId())

        # otherwise use parent method
        rsrc.id = None
        self.assertIsNone(rsrc.resource_id)
        self.assertEqual('LaunchConfig', rsrc.FnGetRefId())

    def test_launch_config_refid_convergence_cache_data(self):
        t = template_format.parse(inline_templates.as_template)
        cache_data = {'LaunchConfig': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, params=inline_templates.as_params,
                                  cache_data=cache_data)
        rsrc = stack.defn['LaunchConfig']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())

    def test_launch_config_create_with_instanceid(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        lcp['InstanceId'] = '5678'
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['LaunchConfig']
        # ImageId, InstanceType and BlockDeviceMappings keep the lc's values
        # KeyName and SecurityGroups are derived from the instance
        lc_props = {
            'ImageId': 'foo',
            'InstanceType': 'bar',
            'BlockDeviceMappings': lcp['BlockDeviceMappings'],
            'KeyName': 'hth_keypair',
            'SecurityGroups': ['hth_test']
        }
        rsrc.rebuild_lc_properties = mock.Mock(return_value=lc_props)
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()
        self.stub_ServerConstraint_validate()

        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_lc_validate_without_InstanceId_and_ImageId(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        lcp.pop('ImageId')
        stack = utils.parse_stack(t, inline_templates.as_params)
        rsrc = stack['LaunchConfig']
        self.stub_SnapshotConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              rsrc.validate)
        ex_msg = ('If without InstanceId, '
                  'ImageId and InstanceType are required.')
        self.assertIn(ex_msg, six.text_type(e))

    def test_lc_validate_without_InstanceId_and_InstanceType(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        lcp.pop('InstanceType')
        stack = utils.parse_stack(t, inline_templates.as_params)
        rsrc = stack['LaunchConfig']
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              rsrc.validate)
        ex_msg = ('If without InstanceId, '
                  'ImageId and InstanceType are required.')
        self.assertIn(ex_msg, six.text_type(e))

    def test_launch_config_create_with_instanceid_not_found(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        lcp['InstanceId'] = '5678'
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        rsrc = stack['LaunchConfig']
        self.stub_SnapshotConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        self.patchobject(nova.NovaClientPlugin, 'get_server',
                         side_effect=exception.EntityNotFound(
                             entity='Server', name='5678'))
        msg = ("Property error: "
               "Resources.LaunchConfig.Properties.InstanceId: "
               "Error validating value '5678': The Server (5678) "
               "could not be found.")

        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn(msg, six.text_type(exc))

    def test_validate_BlockDeviceMappings_without_Ebs_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb'}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, stack)

        self.assertIn("Ebs is missing, this is required",
                      six.text_type(e))

    def test_validate_BlockDeviceMappings_without_SnapshotId_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, stack)

        self.assertIn("SnapshotId is missing, this is required",
                      six.text_type(e))

    def test_validate_BlockDeviceMappings_without_DeviceName_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_SnapshotConstraint_validate()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, stack)

        excepted_error = (
            'Property error: '
            'Resources.LaunchConfig.Properties.BlockDeviceMappings[0]: '
            'Property DeviceName not assigned')
        self.assertIn(excepted_error, six.text_type(e))
