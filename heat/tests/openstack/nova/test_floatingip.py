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

import mock
import six

from heat.common import exception as heat_ex
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine.resources.openstack.nova import floatingip
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


floating_ip_template = '''
{
    "heat_template_version": "2013-05-23",
    "resources": {
        "MyFloatingIP": {
            "type": "OS::Nova::FloatingIP",
            "properties": {
                "pool": "public"
            }
        }
    }
}
'''

floating_ip_template_with_assoc = '''
{
    "heat_template_version": "2013-05-23",
    "resources": {
        "MyFloatingIPAssociation": {
            "type": "OS::Nova::FloatingIPAssociation",
            "properties": {
                "server_id": "67dc62f9-efde-4c8b-94af-013e00f5dc57",
                "floating_ip": "1"
            }
        }
    }
}
'''


class NovaFloatingIPTest(common.HeatTestCase):
    def setUp(self):
        super(NovaFloatingIPTest, self).setUp()

        self.novaclient = mock.Mock()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        self.m.StubOutWithMock(self.novaclient.floating_ips, 'create')
        self.m.StubOutWithMock(self.novaclient.floating_ips, 'get')
        self.m.StubOutWithMock(self.novaclient.floating_ips, 'delete')
        self.m.StubOutWithMock(self.novaclient.servers, 'get')
        self.m.StubOutWithMock(self.novaclient.servers, 'add_floating_ip')
        self.m.StubOutWithMock(self.novaclient.servers, 'remove_floating_ip')
        self.patchobject(nova.NovaClientPlugin, 'get_server',
                         return_value=mock.MagicMock())
        self.patchobject(nova.NovaClientPlugin, 'has_extension',
                         return_value=True)

    def _make_obj(self, **kwargs):
        mock = self.m.CreateMockAnything()
        for k, v in six.iteritems(kwargs):
            setattr(mock, k, v)
        return mock

    def prepare_floating_ip(self):
        nova.NovaClientPlugin._create().AndReturn(self.novaclient)
        self.novaclient.floating_ips.create(pool='public').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )

        template = template_format.parse(floating_ip_template)
        self.stack = utils.parse_stack(template)
        defns = self.stack.t.resource_definitions(self.stack)

        return floatingip.NovaFloatingIp('MyFloatingIP',
                                         defns['MyFloatingIP'],
                                         self.stack)

    def prepare_floating_ip_assoc(self):
        nova.NovaClientPlugin._create().AndReturn(
            self.novaclient)
        self.novaclient.servers.get('67dc62f9-efde-4c8b-94af-013e00f5dc57')
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )

        template = template_format.parse(floating_ip_template_with_assoc)
        self.stack = utils.parse_stack(template)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        floating_ip_assoc = resource_defns['MyFloatingIPAssociation']

        return floatingip.NovaFloatingIpAssociation(
            'MyFloatingIPAssociation', floating_ip_assoc, self.stack)

    def test_floating_ip_create(self):
        rsrc = self.prepare_floating_ip()

        fip = mock.MagicMock()
        fip.to_dict.return_value = {'fip': 'info'}
        self.novaclient.floating_ips.get('1').AndReturn(fip)
        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('1', rsrc.FnGetRefId())
        self.assertEqual('11.0.0.1', rsrc.FnGetAtt('ip'))
        self.assertEqual('public', rsrc.FnGetAtt('pool'))

        self.assertEqual({'fip': 'info'}, rsrc.FnGetAtt('show'))

        self.m.VerifyAll()

    def test_floating_ip_delete(self):
        rsrc = self.prepare_floating_ip()
        rsrc.validate()

        self.novaclient.floating_ips.delete('1')

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_delete_floating_ip_assoc_successful_if_create_failed(self):
        rsrc = self.prepare_floating_ip_assoc()
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1').AndRaise(
            fakes_nova.fake_exception(400))

        self.m.ReplayAll()

        rsrc.validate()

        self.assertRaises(heat_ex.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_floating_ip_assoc_create(self):
        rsrc = self.prepare_floating_ip_assoc()
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.assertIsNotNone(rsrc.id)
        self.assertEqual(rsrc.id, rsrc.resource_id)

        self.m.VerifyAll()

    def test_floating_ip_assoc_delete(self):
        rsrc = self.prepare_floating_ip_assoc()
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        self.novaclient.servers.get(
            '67dc62f9-efde-4c8b-94af-013e00f5dc57').AndReturn('server')
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )
        self.novaclient.servers.remove_floating_ip('server', '11.0.0.1')

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def create_delete_assoc_with_exc(self, exc_code):
        rsrc = self.prepare_floating_ip_assoc()
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        self.novaclient.servers.get(
            "67dc62f9-efde-4c8b-94af-013e00f5dc57").AndReturn("server")
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                "id": "1",
                "ip": "11.0.0.1",
                "pool": "public"
            })
        )
        self.novaclient.servers.remove_floating_ip("server",
                                                   "11.0.0.1").AndRaise(
            fakes_nova.fake_exception(exc_code))

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_floating_ip_assoc_delete_conflict(self):
        self.create_delete_assoc_with_exc(exc_code=409)

    def test_floating_ip_assoc_delete_not_found(self):
        self.create_delete_assoc_with_exc(exc_code=404)

    def test_floating_ip_assoc_update_server_id(self):
        rsrc = self.prepare_floating_ip_assoc()
        # for create
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        # for update
        self.novaclient.servers.get(
            '2146dfbf-ba77-4083-8e86-d052f671ece5').AndReturn('server')
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )
        self.novaclient.servers.add_floating_ip('server', '11.0.0.1')

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # update with the new server_id
        props = copy.deepcopy(rsrc.properties.data)
        update_server_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['server_id'] = update_server_id
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_floating_ip_assoc_update_fl_ip(self):
        rsrc = self.prepare_floating_ip_assoc()
        # for create
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        # mock for delete the old association
        self.novaclient.servers.get(
            '67dc62f9-efde-4c8b-94af-013e00f5dc57').AndReturn('server')
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )
        self.novaclient.servers.remove_floating_ip('server', '11.0.0.1')
        # mock for new association
        self.novaclient.servers.get(
            '67dc62f9-efde-4c8b-94af-013e00f5dc57').AndReturn('server')
        self.novaclient.floating_ips.get('2').AndReturn(
            self._make_obj(**{
                'id': '2',
                'ip': '11.0.0.2',
                'pool': 'public'
            })
        )
        self.novaclient.servers.add_floating_ip('server', '11.0.0.2')

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # update with the new floatingip
        props = copy.deepcopy(rsrc.properties.data)
        props['floating_ip'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_floating_ip_assoc_update_both(self):
        rsrc = self.prepare_floating_ip_assoc()
        # for create
        self.novaclient.servers.add_floating_ip(None, '11.0.0.1')
        # mock for delete the old association
        self.novaclient.servers.get(
            '67dc62f9-efde-4c8b-94af-013e00f5dc57').AndReturn('server')
        self.novaclient.floating_ips.get('1').AndReturn(
            self._make_obj(**{
                'id': '1',
                'ip': '11.0.0.1',
                'pool': 'public'
            })
        )
        self.novaclient.servers.remove_floating_ip('server', '11.0.0.1')
        # mock for new association
        self.novaclient.servers.get(
            '2146dfbf-ba77-4083-8e86-d052f671ece5').AndReturn('new_server')
        self.novaclient.floating_ips.get('2').AndReturn(
            self._make_obj(**{
                'id': '2',
                'ip': '11.0.0.2',
                'pool': 'public'
            })
        )
        self.novaclient.servers.add_floating_ip('new_server', '11.0.0.2')

        self.m.ReplayAll()

        rsrc.validate()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        # update with the new floatingip
        props = copy.deepcopy(rsrc.properties.data)
        update_server_id = '2146dfbf-ba77-4083-8e86-d052f671ece5'
        props['server_id'] = update_server_id
        props['floating_ip'] = '2'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_floating_ip_assoc_refid_rsrc_name(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        stack = utils.parse_stack(t)
        rsrc = stack['MyFloatingIPAssociation']
        rsrc.id = '123'
        rsrc.uuid = '9bfb9456-3fe8-41f4-b318-9dba18eeef74'
        rsrc.action = 'CREATE'
        expected = '%s-%s-%s' % (rsrc.stack.name,
                                 rsrc.name,
                                 short_id.get_id(rsrc.uuid))
        self.assertEqual(expected, rsrc.FnGetRefId())

    def test_floating_ip_assoc_refid_rsrc_id(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        stack = utils.parse_stack(t)
        rsrc = stack['MyFloatingIPAssociation']
        rsrc.resource_id = 'phy-rsrc-id'
        self.assertEqual('phy-rsrc-id', rsrc.FnGetRefId())

    def test_floating_ip_assoc_refid_convg_cache_data(self):
        t = template_format.parse(floating_ip_template_with_assoc)
        cache_data = {'MyFloatingIPAssociation': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack['MyFloatingIPAssociation']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
