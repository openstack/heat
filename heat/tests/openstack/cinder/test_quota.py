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
from heat.common import template_format
from heat.engine.clients.os import cinder as c_plugin
from heat.engine.clients.os import keystone as k_plugin
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

quota_template = '''
heat_template_version: newton

description: Sample cinder quota heat template

resources:
  my_quota:
    type: OS::Cinder::Quota
    properties:
      project: demo
      gigabytes: 5
      snapshots: 2
      volumes: 3
'''


class CinderQuotaTest(common.HeatTestCase):
    def setUp(self):
        super(CinderQuotaTest, self).setUp()

        self.ctx = utils.dummy_context()
        self.patchobject(c_plugin.CinderClientPlugin, 'has_extension',
                         return_value=True)
        self.patchobject(k_plugin.KeystoneClientPlugin, 'get_project_id',
                         return_value='some_project_id')
        tpl = template_format.parse(quota_template)
        self.stack = parser.Stack(
            self.ctx, 'cinder_quota_test_stack',
            template.Template(tpl)
        )

        self.my_quota = self.stack['my_quota']
        cinder = mock.MagicMock()
        self.cinderclient = mock.MagicMock()
        self.my_quota.client = cinder
        cinder.return_value = self.cinderclient
        self.quotas = self.cinderclient.quotas
        self.quota_set = mock.MagicMock()
        self.quotas.update.return_value = self.quota_set
        self.quotas.delete.return_value = self.quota_set

        class FakeVolumeOrSnapshot(object):
            def __init__(self, size=1):
                self.size = size
        self.fv = FakeVolumeOrSnapshot
        f_v = self.fv()
        self.volume_snapshots = self.cinderclient.volume_snapshots
        self.volume_snapshots.list.return_value = [f_v, f_v]
        self.volumes = self.cinderclient.volumes
        self.volumes.list.return_value = [f_v, f_v, f_v]
        self.err_msg = ("Invalid quota %(property)s value(s): %(value)s. "
                        "Can not be less than the current usage value(s): "
                        "%(total)s.")

    def _test_validate(self, resource, error_msg):
        exc = self.assertRaises(exception.StackValidationFailed,
                                resource.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def _test_invalid_property(self, prop_name):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        props[prop_name] = -2
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        error_msg = ('Property error: resources.my_quota.properties.%s:'
                     ' -2 is out of range (min: -1, max: None)' % prop_name)
        self._test_validate(my_quota, error_msg)

    def test_invalid_gigabytes(self):
        self._test_invalid_property('gigabytes')

    def test_invalid_snapshots(self):
        self._test_invalid_property('snapshots')

    def test_invalid_volumes(self):
        self._test_invalid_property('volumes')

    def test_miss_all_quotas(self):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        del props['gigabytes'], props['snapshots'], props['volumes']
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        msg = ('At least one of the following properties must be specified: '
               'gigabytes, snapshots, volumes.')
        self.assertRaisesRegex(exception.PropertyUnspecifiedError, msg,
                               my_quota.validate)

    def test_quota_handle_create(self):
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        self.my_quota.handle_create()
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            gigabytes=5,
            snapshots=2,
            volumes=3
        )
        self.assertEqual('some_resource_id', self.my_quota.resource_id)

    def test_quota_handle_update(self):
        tmpl_diff = mock.MagicMock()
        prop_diff = mock.MagicMock()
        props = {'project': 'some_project_id', 'gigabytes': 6,
                 'volumes': 4}
        json_snippet = rsrc_defn.ResourceDefinition(
            self.my_quota.name,
            'OS::Cinder::Quota',
            properties=props)
        self.my_quota.reparse()
        self.my_quota.handle_update(json_snippet, tmpl_diff, prop_diff)
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            gigabytes=6,
            volumes=4
        )

    def test_quota_handle_delete(self):
        self.my_quota.reparse()
        self.my_quota.handle_delete()
        self.quotas.delete.assert_called_once_with('some_project_id')

    def test_quota_with_invalid_gigabytes(self):
        fake_v = self.fv(2)
        self.volumes.list.return_value = [fake_v, fake_v]
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        err = self.assertRaises(ValueError, self.my_quota.handle_create)
        self.assertEqual(
            self.err_msg % {'property': 'gigabytes', 'value': 5, 'total': 6},
            six.text_type(err))

    def test_quota_with_invalid_volumes(self):
        fake_v = self.fv(0)
        self.volumes.list.return_value = [fake_v, fake_v, fake_v, fake_v]
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        err = self.assertRaises(ValueError, self.my_quota.handle_create)
        self.assertEqual(
            self.err_msg % {'property': 'volumes', 'value': 3, 'total': 4},
            six.text_type(err))

    def test_quota_with_invalid_snapshots(self):
        fake_v = self.fv(0)
        self.volume_snapshots.list.return_value = [fake_v, fake_v, fake_v,
                                                   fake_v]
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        err = self.assertRaises(ValueError, self.my_quota.handle_create)
        self.assertEqual(
            self.err_msg % {'property': 'snapshots', 'value': 2, 'total': 4},
            six.text_type(err))

    def _test_quota_with_unlimited_value(self, prop_name):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        props[prop_name] = -1
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        my_quota.handle_create()
        kwargs = {'gigabytes': 5, 'snapshots': 2, 'volumes': 3}
        kwargs[prop_name] = -1
        self.quotas.update.assert_called_once_with('some_project_id', **kwargs)

    def test_quota_with_unlimited_gigabytes(self):
        self._test_quota_with_unlimited_value('gigabytes')

    def test_quota_with_unlimited_snapshots(self):
        self._test_quota_with_unlimited_value('snapshots')

    def test_quota_with_unlimited_volumes(self):
        self._test_quota_with_unlimited_value('volumes')
