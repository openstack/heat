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


from heat.common import identifier
from heat.tests import common


class IdentifierTest(common.HeatTestCase):
    url_prefix = 'http://1.2.3.4/foo/'

    def test_attrs(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_path_default(self):
        hi = identifier.HeatIdentifier('t', 's', 'i')
        self.assertEqual('', hi.path)

    def test_items(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('t', hi['tenant'])
        self.assertEqual('s', hi['stack_name'])
        self.assertEqual('i', hi['stack_id'])
        self.assertEqual('/p', hi['path'])

    def test_invalid_attr(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hi.identity['foo'] = 'bar'
        self.assertRaises(AttributeError, getattr, hi, 'foo')

    def test_invalid_item(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hi.identity['foo'] = 'bar'
        self.assertRaises(KeyError, lambda o, k: o[k], hi, 'foo')

    def test_stack_path(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('s/i', hi.stack_path())

    def test_arn(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('arn:openstack:heat::t:stacks/s/i/p', hi.arn())

    def test_arn_url(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('/arn%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i/p',
                         hi.arn_url_path())

    def test_arn_id_int(self):
        hi = identifier.HeatIdentifier('t', 's', 42, 'p')
        self.assertEqual('arn:openstack:heat::t:stacks/s/42/p', hi.arn())

    def test_arn_parse(self):
        arn = 'arn:openstack:heat::t:stacks/s/i/p'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_arn_url_parse(self):
        url = self.url_prefix + 'arn%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i/p'
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_arn_parse_path_default(self):
        arn = 'arn:openstack:heat::t:stacks/s/i'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('', hi.path)

    def test_arn_url_parse_default(self):
        url = self.url_prefix + 'arn%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i'
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('', hi.path)

    def test_arn_parse_upper(self):
        arn = 'ARN:openstack:heat::t:stacks/s/i/p'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_arn_url_parse_upper(self):
        url = self.url_prefix + 'ARN%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i/p'
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_arn_url_parse_qs(self):
        url = (self.url_prefix +
               'arn%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i/p?foo=bar')
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual('t', hi.tenant)
        self.assertEqual('s', hi.stack_name)
        self.assertEqual('i', hi.stack_id)
        self.assertEqual('/p', hi.path)

    def test_arn_parse_arn_invalid(self):
        arn = 'urn:openstack:heat::t:stacks/s/i'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_arn_invalid(self):
        url = self.url_prefix + 'urn:openstack:heat::t:stacks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_parse_os_invalid(self):
        arn = 'arn:aws:heat::t:stacks/s/i'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_os_invalid(self):
        url = self.url_prefix + 'arn:aws:heat::t:stacks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_parse_heat_invalid(self):
        arn = 'arn:openstack:cool::t:stacks/s/i'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_heat_invalid(self):
        url = self.url_prefix + 'arn:openstack:cool::t:stacks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_parse_stacks_invalid(self):
        arn = 'arn:openstack:heat::t:sticks/s/i'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_stacks_invalid(self):
        url = self.url_prefix + 'arn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_parse_missing_field(self):
        arn = 'arn:openstack:heat::t:stacks/s'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_missing_field(self):
        url = self.url_prefix + 'arn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_parse_empty_field(self):
        arn = 'arn:openstack:heat::t:stacks//i'
        self.assertRaises(ValueError, identifier.HeatIdentifier.from_arn, arn)

    def test_arn_url_parse_empty_field(self):
        url = self.url_prefix + 'arn%3Aopenstack%3Aheat%3A%3At%3Asticks//i'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_url_parse_leading_char(self):
        url = self.url_prefix + 'Aarn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_url_parse_leading_space(self):
        url = self.url_prefix + ' arn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_url_parse_badurl_proto(self):
        url = 'htt://1.2.3.4/foo/arn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_url_parse_badurl_host(self):
        url = 'http:///foo/arn%3Aopenstack%3Aheat%3A%3At%3Asticks/s/i/p'
        self.assertRaises(ValueError,
                          identifier.HeatIdentifier.from_arn_url, url)

    def test_arn_round_trip(self):
        hii = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hio = identifier.HeatIdentifier.from_arn(hii.arn())
        self.assertEqual(hii.tenant, hio.tenant)
        self.assertEqual(hii.stack_name, hio.stack_name)
        self.assertEqual(hii.stack_id, hio.stack_id)
        self.assertEqual(hii.path, hio.path)

    def test_arn_parse_round_trip(self):
        arn = 'arn:openstack:heat::t:stacks/s/i/p'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual(arn, hi.arn())

    def test_arn_url_parse_round_trip(self):
        arn = '/arn%3Aopenstack%3Aheat%3A%3At%3Astacks/s/i/p'
        url = 'http://1.2.3.4/foo' + arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual(arn, hi.arn_url_path())

    def test_dict_round_trip(self):
        hii = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hio = identifier.HeatIdentifier(**dict(hii))
        self.assertEqual(hii.tenant, hio.tenant)
        self.assertEqual(hii.stack_name, hio.stack_name)
        self.assertEqual(hii.stack_id, hio.stack_id)
        self.assertEqual(hii.path, hio.path)

    def test_url_path(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertEqual('t/stacks/s/i/p', hi.url_path())

    def test_url_path_default(self):
        hi = identifier.HeatIdentifier('t', 's', 'i')
        self.assertEqual('t/stacks/s/i', hi.url_path())

    def test_url_path_with_unicode_path(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', u'\u5de5')
        self.assertEqual('t/stacks/s/i/%E5%B7%A5', hi.url_path())

    def test_tenant_escape(self):
        hi = identifier.HeatIdentifier(':/', 's', 'i')
        self.assertEqual(':/', hi.tenant)
        self.assertEqual('%3A%2F/stacks/s/i', hi.url_path())
        self.assertEqual('arn:openstack:heat::%3A%2F:stacks/s/i', hi.arn())

    def test_name_escape(self):
        hi = identifier.HeatIdentifier('t', ':%', 'i')
        self.assertEqual(':%', hi.stack_name)
        self.assertEqual('t/stacks/%3A%25/i', hi.url_path())
        self.assertEqual('arn:openstack:heat::t:stacks/%3A%25/i', hi.arn())

    def test_id_escape(self):
        hi = identifier.HeatIdentifier('t', 's', ':/')
        self.assertEqual(':/', hi.stack_id)
        self.assertEqual('t/stacks/s/%3A%2F', hi.url_path())
        self.assertEqual('arn:openstack:heat::t:stacks/s/%3A%2F', hi.arn())

    def test_id_contains(self):
        hi = identifier.HeatIdentifier('t', 's', ':/')
        self.assertNotIn("t", hi)
        self.assertIn("stack_id", hi)

    def test_path_escape(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', ':/')
        self.assertEqual('/:/', hi.path)
        self.assertEqual('t/stacks/s/i/%3A/', hi.url_path())
        self.assertEqual('arn:openstack:heat::t:stacks/s/i/%3A/', hi.arn())

    def test_tenant_decode(self):
        arn = 'arn:openstack:heat::%3A%2F:stacks/s/i'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual(':/', hi.tenant)

    def test_url_tenant_decode(self):
        enc_arn = 'arn%3Aopenstack%3Aheat%3A%3A%253A%252F%3Astacks%2Fs%2Fi'
        url = self.url_prefix + enc_arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual(':/', hi.tenant)

    def test_name_decode(self):
        arn = 'arn:openstack:heat::t:stacks/%3A%25/i'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual(':%', hi.stack_name)

    def test_url_name_decode(self):
        enc_arn = 'arn%3Aopenstack%3Aheat%3A%3At%3Astacks%2F%253A%2525%2Fi'
        url = self.url_prefix + enc_arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual(':%', hi.stack_name)

    def test_id_decode(self):
        arn = 'arn:openstack:heat::t:stacks/s/%3A%2F'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual(':/', hi.stack_id)

    def test_url_id_decode(self):
        enc_arn = 'arn%3Aopenstack%3Aheat%3A%3At%3Astacks%2Fs%2F%253A%252F'
        url = self.url_prefix + enc_arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual(':/', hi.stack_id)

    def test_path_decode(self):
        arn = 'arn:openstack:heat::t:stacks/s/i/%3A%2F'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual('/:/', hi.path)

    def test_url_path_decode(self):
        enc_arn = 'arn%3Aopenstack%3Aheat%3A%3At%3Astacks%2Fs%2Fi%2F%253A%252F'
        url = self.url_prefix + enc_arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        self.assertEqual('/:/', hi.path)

    def test_arn_escape_decode_round_trip(self):
        hii = identifier.HeatIdentifier(':/', ':%', ':/', ':/')
        hio = identifier.HeatIdentifier.from_arn(hii.arn())
        self.assertEqual(hii.tenant, hio.tenant)
        self.assertEqual(hii.stack_name, hio.stack_name)
        self.assertEqual(hii.stack_id, hio.stack_id)
        self.assertEqual(hii.path, hio.path)

    def test_arn_decode_escape_round_trip(self):
        arn = 'arn:openstack:heat::%3A%2F:stacks/%3A%25/%3A%2F/%3A/'
        hi = identifier.HeatIdentifier.from_arn(arn)
        self.assertEqual(arn, hi.arn())

    def test_arn_url_decode_escape_round_trip(self):
        enc_arn = "".join(['arn%3Aopenstack%3Aheat%3A%3A%253A%252F%3A',
                           'stacks%2F%253A%2525%2F%253A%252F%2F%253A'])
        url = self.url_prefix + enc_arn
        hi = identifier.HeatIdentifier.from_arn_url(url)
        hi2 = identifier.HeatIdentifier.from_arn_url(self.url_prefix +
                                                     hi.arn_url_path())
        self.assertEqual(hi, hi2)

    def test_stack_name_slash(self):
        self.assertRaises(ValueError, identifier.HeatIdentifier,
                          't', 's/s', 'i', 'p')

    def test_equal(self):
        hi1 = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hi2 = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertTrue(hi1 == hi2)

    def test_equal_dict(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p')
        self.assertTrue(hi == dict(hi))
        self.assertTrue(dict(hi) == hi)

    def test_not_equal(self):
        hi1 = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hi2 = identifier.HeatIdentifier('t', 's', 'i', 'q')
        self.assertFalse(hi1 == hi2)
        self.assertFalse(hi2 == hi1)

    def test_not_equal_dict(self):
        hi1 = identifier.HeatIdentifier('t', 's', 'i', 'p')
        hi2 = identifier.HeatIdentifier('t', 's', 'i', 'q')
        self.assertFalse(hi1 == dict(hi2))
        self.assertFalse(dict(hi1) == hi2)
        self.assertFalse(hi1 == {'tenant': 't',
                                 'stack_name': 's',
                                 'stack_id': 'i'})
        self.assertFalse({'tenant': 't',
                          'stack_name': 's',
                          'stack_id': 'i'} == hi1)

    def test_path_components(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', 'p1/p2/p3')
        self.assertEqual(['p1', 'p2', 'p3'], hi._path_components())


class ResourceIdentifierTest(common.HeatTestCase):
    def test_resource_init_no_path(self):
        si = identifier.HeatIdentifier('t', 's', 'i')
        ri = identifier.ResourceIdentifier(resource_name='r', **si)
        self.assertEqual('/resources/r', ri.path)

    def test_resource_init_path(self):
        si = identifier.HeatIdentifier('t', 's', 'i')
        pi = identifier.ResourceIdentifier(resource_name='p', **si)
        ri = identifier.ResourceIdentifier(resource_name='r', **pi)
        self.assertEqual('/resources/p/resources/r', ri.path)

    def test_resource_init_from_dict(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', '/resources/r')
        ri = identifier.ResourceIdentifier(**hi)
        self.assertEqual(hi, ri)

    def test_resource_stack(self):
        si = identifier.HeatIdentifier('t', 's', 'i')
        ri = identifier.ResourceIdentifier(resource_name='r', **si)
        self.assertEqual(si, ri.stack())

    def test_resource_id(self):
        ri = identifier.ResourceIdentifier('t', 's', 'i', '', 'r')
        self.assertEqual('r', ri.resource_name)

    def test_resource_name_slash(self):
        self.assertRaises(ValueError, identifier.ResourceIdentifier,
                          't', 's', 'i', 'p', 'r/r')


class EventIdentifierTest(common.HeatTestCase):
    def test_event_init_integer_id(self):
        self._test_event_init('42')

    def test_event_init_uuid_id(self):
        self._test_event_init('a3455d8c-9f88-404d-a85b-5315293e67de')

    def _test_event_init(self, event_id):
        si = identifier.HeatIdentifier('t', 's', 'i')
        pi = identifier.ResourceIdentifier(resource_name='p', **si)
        ei = identifier.EventIdentifier(event_id=event_id, **pi)
        self.assertEqual('/resources/p/events/{0}'.format(event_id), ei.path)

    def test_event_init_from_dict(self):
        hi = identifier.HeatIdentifier('t', 's', 'i', '/resources/p/events/42')
        ei = identifier.EventIdentifier(**hi)
        self.assertEqual(hi, ei)

    def test_event_stack(self):
        si = identifier.HeatIdentifier('t', 's', 'i')
        pi = identifier.ResourceIdentifier(resource_name='r', **si)
        ei = identifier.EventIdentifier(event_id='e', **pi)
        self.assertEqual(si, ei.stack())

    def test_event_resource(self):
        si = identifier.HeatIdentifier('t', 's', 'i')
        pi = identifier.ResourceIdentifier(resource_name='r', **si)
        ei = identifier.EventIdentifier(event_id='e', **pi)
        self.assertEqual(pi, ei.resource())

    def test_resource_name(self):
        ei = identifier.EventIdentifier('t', 's', 'i', '/resources/p', 'e')
        self.assertEqual('p', ei.resource_name)

    def test_event_id_integer(self):
        self._test_event_id('42')

    def test_event_id_uuid(self):
        self._test_event_id('a3455d8c-9f88-404d-a85b-5315293e67de')

    def _test_event_id(self, event_id):
        ei = identifier.EventIdentifier('t', 's', 'i', '/resources/p',
                                        event_id)
        self.assertEqual(event_id, ei.event_id)
