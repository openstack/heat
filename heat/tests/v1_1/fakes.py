# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2011 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import httplib2
import mock

from novaclient import client as base_client
from novaclient import exceptions as nova_exceptions
from novaclient.v1_1 import client

from heat.openstack.common.py3kcompat import urlutils
from heat.tests import fakes


def fake_exception(status_code=404, message=None, details=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = None
    body = {'error': {'message': message, 'details': details}}
    return nova_exceptions.from_response(resp, body, None)


class FakeClient(fakes.FakeClient, client.Client):

    def __init__(self, *args, **kwargs):
        client.Client.__init__(self, 'username', 'password',
                               'project_id', 'auth_url')
        self.client = FakeHTTPClient(**kwargs)


class FakeHTTPClient(base_client.HTTPClient):

    def __init__(self, **kwargs):
        self.username = 'username'
        self.password = 'password'
        self.auth_url = 'auth_url'
        self.callstack = []

    def _cs_request(self, url, method, **kwargs):
        # Check that certain things are called correctly
        if method in ['GET', 'DELETE']:
            assert 'body' not in kwargs
        elif method == 'PUT':
            assert 'body' in kwargs

        # Call the method
        args = urlutils.parse_qsl(urlutils.urlparse(url)[4])
        kwargs.update(args)
        munged_url = url.rsplit('?', 1)[0]
        munged_url = munged_url.strip('/').replace('/', '_').replace('.', '_')
        munged_url = munged_url.replace('-', '_')

        callback = "%s_%s" % (method.lower(), munged_url)

        if not hasattr(self, callback):
            raise AssertionError('Called unknown API method: %s %s, '
                                 'expected fakes method name: %s' %
                                 (method, url, callback))

        # Note the call
        self.callstack.append((method, url, kwargs.get('body')))

        status, body = getattr(self, callback)(**kwargs)
        if hasattr(status, 'items'):
            return httplib2.Response(status), body
        else:
            return httplib2.Response({"status": status}), body

    #
    # Servers
    #
    def get_servers_detail(self, **kw):
        return (
            200,
            {"servers": [{"id": 1234,
                          "name": "sample-server",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "sample-server",
                          "image": {"id": 2, "name": "sample image"},
                          "flavor": {"id": 1, "name": "256 MB Server"},
                          "hostId": "e4d909c290d0fb1ca068ffaddf22cbd0",
                          "status": "BUILD",
                          "progress": 60,
                          "addresses": {"public": [{"version": 4,
                                                    "addr": "1.2.3.4"},
                                                   {"version": 4,
                                                    "addr": "5.6.7.8"}],
                                        "private": [{"version": 4,
                                                     "addr": "10.11.12.13"}]},
                          "accessIPv4": "",
                          "accessIPv6": "",
                          "metadata": {"Server Label": "Web Head 1",
                                       "Image Version": "2.1"}},
                         {"id": 5678,
                          "name": "sample-server2",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "sample-server2",
                          "image": {"id": 2, "name": "sample image"},
                          "flavor": {"id": 1, "name": "256 MB Server"},
                          "hostId": "9e107d9d372bb6826bd81d3542a419d6",
                          "status": "ACTIVE",
                          "accessIPv4": "192.0.2.0",
                          "accessIPv6": "::babe:4317:0A83",
                          "addresses": {"public": [{"version": 4,
                                                    "addr": "4.5.6.7",
                                                    "OS-EXT-IPS-MAC:mac_addr":
                                                    "fa:16:3e:8c:22:aa"},
                                                   {"version": 4,
                                                    "addr": "5.6.9.8",
                                                    "OS-EXT-IPS-MAC:mac_addr":
                                                    "fa:16:3e:8c:33:bb"}],
                                        "private": [{"version": 4,
                                                     "addr": "10.13.12.13",
                                                    "OS-EXT-IPS-MAC:mac_addr":
                                                    "fa:16:3e:8c:44:cc"}]},
                          "metadata": {}},
                         {"id": 9101,
                          "name": "hard-reboot",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "hard-reboot",
                          "image": {"id": 2, "name": "sample image"},
                          "flavor": {"id": 1, "name": "256 MB Server"},
                          "hostId": "9e44d8d435c43dd8d96bb63ed995605f",
                          "status": "HARD_REBOOT",
                          "accessIPv4": "",
                          "accessIPv6": "",
                          "addresses": {"public": [{"version": 4,
                                                    "addr": "172.17.1.2"},
                                                   {"version": 4,
                                                    "addr": "10.20.30.40"}],
                                        "private": [{"version": 4,
                                                     "addr": "10.13.12.13"}]},
                          "metadata": {"Server Label": "DB 1"}},
                         {"id": 9102,
                          "name": "server-with-no-ip",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "server-with-no-ip",
                          "image": {"id": 2, "name": "sample image"},
                          "flavor": {"id": 1, "name": "256 MB Server"},
                          "hostId": "c1365ba78c624df9b2ff446515a682f5",
                          "status": "ACTIVE",
                          "accessIPv4": "",
                          "accessIPv6": "",
                          "addresses": {"empty_net": []},
                          "metadata": {"Server Label": "DB 1"}},
                         {"id": 9999,
                          "name": "sample-server3",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "sample-server3",
                          "image": {"id": 3, "name": "sample image"},
                          "flavor": {"id": 3, "name": "m1.large"},
                          "hostId": "9e107d9d372bb6826bd81d3542a419d6",
                          "status": "ACTIVE",
                          "accessIPv4": "",
                          "accessIPv6": "",
                          "addresses": {
                              "public": [{"version": 4, "addr": "4.5.6.7"},
                                         {"version": 4, "addr": "5.6.9.8"}],
                              "private": [{"version": 4,
                                           "addr": "10.13.12.13"}]},
                          "metadata": {"Server Label": "DB 1"}},
                         {"id": 56789,
                          "name": "server-with-metadata",
                          "OS-EXT-SRV-ATTR:instance_name":
                          "sample-server2",
                          "image": {"id": 2, "name": "sample image"},
                          "flavor": {"id": 1, "name": "256 MB Server"},
                          "hostId": "9e107d9d372bb6826bd81d3542a419d6",
                          "status": "ACTIVE",
                          "accessIPv4": "192.0.2.0",
                          "accessIPv6": "::babe:4317:0A83",
                          "addresses": {"public": [{"version": 4,
                                                    "addr": "4.5.6.7"},
                                                   {"version": 4,
                                                    "addr": "5.6.9.8"}],
                                        "private": [{"version": 4,
                                                     "addr": "10.13.12.13"}]},
                          "metadata": {'test': '123', 'this': 'that'}}]})

    def get_servers_1234(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][0]}
        return (200, r)

    def get_servers_56789(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][5]}
        return (200, r)

    def get_servers_WikiServerOne(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][0]}
        return (200, r)

    def get_servers_WikiServerOne1(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][0]}
        return (200, r)

    def get_servers_WikiServerOne2(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][3]}
        return (200, r)

    def get_servers_5678(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][1]}
        return (200, r)

    def delete_servers_1234(self, **kw):
        return (202, None)

    def get_servers_9999(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][0]}
        return (200, r)

    def get_servers_9102(self, **kw):
        r = {'server': self.get_servers_detail()[1]['servers'][3]}
        return (200, r)

    #
    # Server actions
    #

    def post_servers_1234_action(self, body, **kw):
        _body = None
        resp = 202
        assert len(body.keys()) == 1
        action = body.keys()[0]
        if action == 'reboot':
            assert body[action].keys() == ['type']
            assert body[action]['type'] in ['HARD', 'SOFT']
        elif action == 'rebuild':
            keys = body[action].keys()
            if 'adminPass' in keys:
                keys.remove('adminPass')
            assert keys == ['imageRef']
            _body = self.get_servers_1234()[1]
        elif action == 'resize':
            assert body[action].keys() == ['flavorRef']
        elif action == 'confirmResize':
            assert body[action] is None
            # This one method returns a different response code
            return (204, None)
        elif action == 'revertResize':
            assert body[action] is None
        elif action == 'migrate':
            assert body[action] is None
        elif action == 'rescue':
            assert body[action] is None
        elif action == 'unrescue':
            assert body[action] is None
        elif action == 'lock':
            assert body[action] is None
        elif action == 'unlock':
            assert body[action] is None
        elif action == 'suspend':
            assert body[action] is None
        elif action == 'resume':
            assert body[action] is None
        elif action == 'addFixedIp':
            assert body[action].keys() == ['networkId']
        elif action == 'removeFixedIp':
            assert body[action].keys() == ['address']
        elif action == 'addFloatingIp':
            assert body[action].keys() == ['address']
        elif action == 'removeFloatingIp':
            assert body[action].keys() == ['address']
        elif action == 'createImage':
            assert set(body[action].keys()) == set(['name', 'metadata'])
            resp = dict(status=202, location="http://blah/images/456")
        elif action == 'changePassword':
            assert body[action].keys() == ['adminPass']
        elif action == 'os-getConsoleOutput':
            assert body[action].keys() == ['length']
            return (202, {'output': 'foo'})
        elif action == 'os-getVNCConsole':
            assert body[action].keys() == ['type']
        elif action == 'os-migrateLive':
            assert set(body[action].keys()) == set(['host',
                                                    'block_migration',
                                                    'disk_over_commit'])
        else:
            raise AssertionError("Unexpected server action: %s" % action)
        return (resp, _body)

    #
    # Flavors
    #

    def get_flavors_detail(self, **kw):
        return (200, {'flavors': [
            {'id': 1, 'name': '256 MB Server', 'ram': 256, 'disk': 10,
             'OS-FLV-EXT-DATA:ephemeral': 10},
            {'id': 2, 'name': 'm1.small', 'ram': 512, 'disk': 20,
             'OS-FLV-EXT-DATA:ephemeral': 20},
            {'id': 3, 'name': 'm1.large', 'ram': 512, 'disk': 20,
             'OS-FLV-EXT-DATA:ephemeral': 30}
        ]})

    #
    # Floating ips
    #

    def get_os_floating_ips_1(self, **kw):
        return (200, {'floating_ip': {'id': 1,
                                      'fixed_ip': '10.0.0.1',
                                      'ip': '11.0.0.1'}})

    def post_os_floating_ips(self, body, **kw):
        return (202, self.get_os_floating_ips_1()[1])

    def delete_os_floating_ips_1(self, **kw):
        return (204, None)

    #
    # Images
    #
    def get_images_detail(self, **kw):
        return (200, {'images': [{'id': 1,
                                  'name': 'CentOS 5.2',
                                  "updated": "2010-10-10T12:00:00Z",
                                  "created": "2010-08-10T12:00:00Z",
                                  "status": "ACTIVE",
                                  "metadata": {"test_key": "test_value"},
                                  "links": {}},
                                 {"id": 743,
                                  "name": "My Server Backup",
                                  "serverId": 1234,
                                  "updated": "2010-10-10T12:00:00Z",
                                  "created": "2010-08-10T12:00:00Z",
                                  "status": "SAVING",
                                  "progress": 80,
                                  "links": {}},
                                 {"id": 744,
                                  "name": "F17-x86_64-gold",
                                  "serverId": 9999,
                                  "updated": "2010-10-10T12:00:00Z",
                                  "created": "2010-08-10T12:00:00Z",
                                  "status": "SAVING",
                                  "progress": 80,
                                  "links": {}},
                                 {"id": 745,
                                  "name": "F17-x86_64-cfntools",
                                  "serverId": 9998,
                                  "updated": "2010-10-10T12:00:00Z",
                                  "created": "2010-08-10T12:00:00Z",
                                  "status": "SAVING",
                                  "progress": 80,
                                  "links": {}},
                                 {"id": 746,
                                  "name": "F20-x86_64-cfntools",
                                  "serverId": 9998,
                                  "updated": "2010-10-10T12:00:00Z",
                                  "created": "2010-08-10T12:00:00Z",
                                  "status": "SAVING",
                                  "progress": 80,
                                  "links": {}}]})

    def get_images_1(self, **kw):
        return (200, {'image': self.get_images_detail()[1]['images'][0]})

    #
    # Keypairs
    #
    def get_os_keypairs(self, *kw):
        return (200, {"keypairs": [{'fingerprint': 'FAKE_KEYPAIR',
                                    'name': 'test',
                                    'public_key': 'foo'}]})

    def get_os_availability_zone(self, *kw):
        return (200, {"availabilityZoneInfo": [{'zoneName': 'nova1'}]})

    def get_os_networks(self, **kw):
        return (200, {'networks':
                [{'label': 'public',
                  'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
                 {'label': 'foo',
                  'id': '42'},
                 {'label': 'foo',
                  'id': '42'}]})

    #
    # Limits
    #
    def get_limits(self, *kw):
        return (200, {'limits': {'absolute': {'maxServerMeta': 3,
                                              'maxPersonalitySize': 10240,
                                              'maxPersonality': 5}}})
