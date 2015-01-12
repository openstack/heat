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

from oslo.config import cfg
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


class LaunchConfigurationTest(common.HeatTestCase):
    def setUp(self):
        super(LaunchConfigurationTest, self).setUp()
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()

    def validate_launch_config(self, t, stack, resource_name):
        # create the launch configuration resource
        conf = stack['LaunchConfig']
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
        self.assertIsNotNone(rsrc.id)
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.id))
        self.assertEqual(expected, rsrc.FnGetRefId())

        # otherwise use parent method
        rsrc.id = None
        self.assertIsNone(rsrc.resource_id)
        self.assertEqual('LaunchConfig', rsrc.FnGetRefId())

    def test_validate_BlockDeviceMappings_without_Ebs_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb'}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, t,
                              stack, 'LaunchConfig')

        self.assertIn("Ebs is missing, this is required",
                      six.text_type(e))

        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_SnapshotId_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'DeviceName': 'vdb',
                'Ebs': {'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)

        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, t,
                              stack, 'LaunchConfig')

        self.assertIn("SnapshotId is missing, this is required",
                      six.text_type(e))
        self.m.VerifyAll()

    def test_validate_BlockDeviceMappings_without_DeviceName_property(self):
        t = template_format.parse(inline_templates.as_template)
        lcp = t['Resources']['LaunchConfig']['Properties']
        bdm = [{'Ebs': {'SnapshotId': '1234',
                        'VolumeSize': '1'}}]
        lcp['BlockDeviceMappings'] = bdm
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        self.stub_ImageConstraint_validate()
        self.m.ReplayAll()

        e = self.assertRaises(exception.StackValidationFailed,
                              self.validate_launch_config, t,
                              stack, 'LaunchConfig')

        excepted_error = ('Property error : LaunchConfig: BlockDeviceMappings '
                          'Property error : BlockDeviceMappings: 0 Property '
                          'error : 0: Property DeviceName not assigned')
        self.assertIn(excepted_error, six.text_type(e))

        self.m.VerifyAll()
