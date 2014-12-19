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
import six

import mock

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources import instance_group as instgrp
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.autoscaling import inline_templates
from heat.tests import common
from heat.tests import utils


class TestInstanceGroup(common.HeatTestCase):
    def setUp(self):
        super(TestInstanceGroup, self).setUp()
        t = template_format.parse(inline_templates.as_template)
        stack = utils.parse_stack(t, params=inline_templates.as_params)
        defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2, 'AvailabilityZones': ['zoneb'],
             'LaunchConfigurationName': 'config'})
        self.instance_group = instgrp.InstanceGroup('asg',
                                                    defn, stack)

    def test_child_template(self):
        self.instance_group._create_template = mock.Mock(return_value='tpl')
        self.assertEqual('tpl', self.instance_group.child_template())
        self.instance_group._create_template.assert_called_once_with(2)

    def test_child_params(self):
        expected = {'parameters': {},
                    'resource_registry': {
                        'OS::Heat::ScaledResource': 'AWS::EC2::Instance'}}
        self.assertEqual(expected, self.instance_group.child_params())
        self.assertEqual(expected, self.instance_group._environment())

    def test_tags_default(self):
        expected = [{'Value': u'asg',
                     'Key': 'metering.groupname'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_tags_with_extra(self):
        self.instance_group.properties.data['Tags'] = [
            {'Key': 'fee', 'Value': 'foo'}]
        expected = [{'Key': 'fee', 'Value': 'foo'},
                    {'Value': u'asg',
                     'Key': 'metering.groupname'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_tags_with_metering(self):
        self.instance_group.properties.data['Tags'] = [
            {'Key': 'metering.fee', 'Value': 'foo'}]
        expected = [{'Key': 'metering.fee', 'Value': 'foo'}]
        self.assertEqual(expected, self.instance_group._tags())

    def test_validate_launch_conf(self):
        props = self.instance_group.properties.data
        props['LaunchConfigurationName'] = 'urg_i_cant_spell'
        creator = scheduler.TaskRunner(self.instance_group.create)
        error = self.assertRaises(exception.ResourceFailure, creator)

        self.assertIn('(urg_i_cant_spell) reference can not be found.',
                      six.text_type(error))

    def test_validate_launch_conf_no_ref(self):
        props = self.instance_group.properties.data
        props['LaunchConfigurationName'] = 'JobServerConfig'
        creator = scheduler.TaskRunner(self.instance_group.create)
        error = self.assertRaises(exception.ResourceFailure, creator)
        self.assertIn('(JobServerConfig) reference can not be',
                      six.text_type(error))

    def test_handle_delete(self):
        self.instance_group.delete_nested = mock.Mock(return_value=None)
        self.instance_group.handle_delete()
        self.instance_group.delete_nested.assert_called_once_with()

    def test_attributes(self):
        mock_members = self.patchobject(grouputils, 'get_members')
        instances = []
        for ip_ex in six.moves.range(1, 4):
            inst = mock.Mock()
            inst.FnGetAtt.return_value = '2.1.3.%d' % ip_ex
            instances.append(inst)
        mock_members.return_value = instances
        res = self.instance_group._resolve_attribute('InstanceList')
        self.assertEqual('2.1.3.1,2.1.3.2,2.1.3.3', res)


class TestLaunchConfig(common.HeatTestCase):
    def create_resource(self, t, stack, resource_name):
        # subsequent resources may need to reference previous created resources
        # use the stack's resource objects instead of instantiating new ones
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_update_metadata_replace(self):
        """Updating the config's metadata causes a config replacement."""
        lc_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Resources": {
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Metadata": {"foo": "bar"},
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.large",
        "KeyName"           : "test",
      }
    }
  }
}
'''
        self.stub_ImageConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.m.ReplayAll()

        t = template_format.parse(lc_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'JobServerConfig')
        props = copy.copy(rsrc.properties.data)
        metadata = copy.copy(rsrc.metadata_get())
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props,
                                                      metadata)
        # Change nothing in the first update
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual('bar', metadata['foo'])
        metadata['foo'] = 'wibble'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props,
                                                      metadata)
        # Changing metadata in the second update triggers UpdateReplace
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)
        self.m.VerifyAll()
