# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from heat.common import template_format
from heat.engine.clients.os import keystone
from heat.engine import environment
from heat.engine import stack as parser
from heat.engine import template as templatem
from heat.tests import fakes as test_fakes

wp_template = '''
heat_template_version: 2014-10-16
description: WordPress
parameters:
  KeyName:
    description: KeyName
    type: string
    default: test
resources:
  WebServer:
    type: AWS::EC2::Instance
    properties:
      ImageId: F17-x86_64-gold
      InstanceType: m1.large
      KeyName: test
      UserData: wordpress
'''


def get_stack(stack_name, ctx, template=None, with_params=True,
              convergence=False):
    if template is None:
        t = template_format.parse(wp_template)
        if with_params:
            env = environment.Environment({'KeyName': 'test'})
            tmpl = templatem.Template(t, env=env)
        else:
            tmpl = templatem.Template(t)
    else:
        t = template_format.parse(template)
        tmpl = templatem.Template(t)
    stack = parser.Stack(ctx, stack_name, tmpl, convergence=convergence)
    return stack


def setup_keystone_mocks(mocks, stack):
    fkc = test_fakes.FakeKeystoneClient()

    mocks.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
    keystone.KeystoneClientPlugin._create().AndReturn(fkc)
