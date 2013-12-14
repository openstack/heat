# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from webob import exc

from heat.api.openstack.v1 import util
from heat.common import context
from heat.common.wsgi import Request
from heat.tests.common import HeatTestCase


class TestTenantLocal(HeatTestCase):
    def setUp(self):
        super(TestTenantLocal, self).setUp()
        self.req = Request({})
        self.req.context = context.RequestContext(tenant_id='foo')

    def test_tenant_local(self):
        @util.tenant_local
        def an_action(controller, req):
            return 'woot'

        self.assertEqual('woot',
                         an_action(None, self.req, tenant_id='foo'))

        self.assertRaises(exc.HTTPForbidden,
                          an_action, None, self.req, tenant_id='bar')
