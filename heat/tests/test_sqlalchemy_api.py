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

import unittest

import mox
from nose.plugins.attrib import attr

from heat.common import context
from heat.db.sqlalchemy import api as db_api


@attr(tag=['unit', 'sqlalchemy'])
@attr(speed='fast')
class SqlAlchemyTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_user_creds_password(self):
        ctx = context.RequestContext.from_dict({
            'tenant_id': 'test_tenant_id',
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'service_password': 'service_password',
            'aws_creds': 'aws_creds_123',
            'roles': [],
            'auth_url': 'http://server.test:5000/v2.0',
        })

        db_creds = db_api.user_creds_create(ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertEqual(load_creds.get('username'), 'test_username')
        self.assertEqual(load_creds.get('password'), 'password')
        self.assertEqual(load_creds.get('service_password'),
                         'service_password')
        self.assertEqual(load_creds.get('aws_creds'), 'aws_creds_123')
        self.assertEqual(load_creds.get('tenant'), 'test_tenant')
        self.assertEqual(load_creds.get('tenant_id'), 'test_tenant_id')
        self.assertNotEqual(None, load_creds.get('created_at'))
        self.assertEqual(None, load_creds.get('updated_at'))
        self.assertEqual(load_creds.get('auth_url'),
                         'http://server.test:5000/v2.0')

    def test_user_creds_none(self):
        ctx = context.RequestContext()
        db_creds = db_api.user_creds_create(ctx)
        load_creds = db_api.user_creds_get(db_creds.id)

        self.assertEqual(None, load_creds.get('username'))
        self.assertEqual(None, load_creds.get('password'))
        self.assertEqual(None, load_creds.get('service_password'))
        self.assertEqual(None, load_creds.get('aws_creds'))
