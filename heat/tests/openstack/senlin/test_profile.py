# Copyright 2015 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from heat.common import template_format
from heat.engine.clients.os import senlin
from heat.engine.resources.openstack.senlin import profile as sp
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


profile_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Profile Template
resources:
  senlin-profile:
    type: OS::Senlin::Profile
    properties:
      name: SenlinProfile
      type: os.heat.stack-1.0
      properties:
        template:
          heat_template_version: 2014-10-16
          resources:
            random:
              type: OS::Heat::RandomString
"""

profile_spec = {
    'type': 'os.heat.stack',
    'version': '1.0',
    'properties': {
        'template': {
            'heat_template_version': '2014-10-16',
            'resources': {
                'random': {
                    'type': 'OS::Heat::RandomString'
                }
            }
        }
    }
}


class FakeProfile(object):
    def __init__(self, id='some_id', spec=None):
        self.id = id
        self.name = "SenlinProfile"
        self.metadata = {}
        self.spec = spec or profile_spec


class SenlinProfileTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinProfileTest, self).setUp()
        self.senlin_mock = mock.MagicMock()
        self.patchobject(sp.Profile, 'client', return_value=self.senlin_mock)
        self.patchobject(senlin.ProfileTypeConstraint, 'validate',
                         return_value=True)
        self.fake_p = FakeProfile()
        self.t = template_format.parse(profile_stack_template)

    def _init_profile(self, template):
        self.stack = utils.parse_stack(template)
        profile = self.stack['senlin-profile']
        return profile

    def _create_profile(self, template):
        profile = self._init_profile(template)
        self.senlin_mock.create_profile.return_value = self.fake_p
        scheduler.TaskRunner(profile.create)()
        self.assertEqual((profile.CREATE, profile.COMPLETE),
                         profile.state)
        self.assertEqual(self.fake_p.id, profile.resource_id)
        return profile

    def test_profile_create(self):
        self._create_profile(self.t)
        expect_kwargs = {
            'name': 'SenlinProfile',
            'metadata': None,
            'spec': profile_spec
        }
        self.senlin_mock.create_profile.assert_called_once_with(
            **expect_kwargs)

    def test_profile_delete(self):
        self.senlin_mock.delete_profile.return_value = None
        profile = self._create_profile(self.t)
        scheduler.TaskRunner(profile.delete)()
        self.senlin_mock.delete_profile.assert_called_once_with(
            profile.resource_id)

    def test_profile_update(self):
        profile = self._create_profile(self.t)
        prop_diff = {'metadata': {'foo': 'bar'}}
        self.senlin_mock.get_profile.return_value = self.fake_p
        profile.handle_update(json_snippet=None,
                              tmpl_diff=None,
                              prop_diff=prop_diff)
        self.senlin_mock.update_profile.assert_called_once_with(
            self.fake_p, **prop_diff)
