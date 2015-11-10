# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

import datetime
from oslo_utils import timeutils
import uuid

from heat.common import service_utils
from heat.db.sqlalchemy import models
from heat.tests import common


class TestServiceUtils(common.HeatTestCase):
    def test_status_check(self):
        service = models.Service()
        service.id = str(uuid.uuid4())
        service.engine_id = str(uuid.uuid4())
        service.binary = 'heat-engine'
        service.hostname = 'host.devstack.org'
        service.host = 'engine-1'
        service.report_interval = 60
        service.topic = 'engine'
        service.created_at = timeutils.utcnow()
        service.deleted_at = None
        service.updated_at = None

        service_dict = service_utils.format_service(service)
        self.assertEqual(service_dict['id'], service.id)
        self.assertEqual(service_dict['engine_id'], service.engine_id)
        self.assertEqual(service_dict['host'], service.host)
        self.assertEqual(service_dict['hostname'], service.hostname)
        self.assertEqual(service_dict['binary'], service.binary)
        self.assertEqual(service_dict['topic'], service.topic)
        self.assertEqual(service_dict['report_interval'],
                         service.report_interval)
        self.assertEqual(service_dict['created_at'], service.created_at)
        self.assertEqual(service_dict['updated_at'], service.updated_at)
        self.assertEqual(service_dict['deleted_at'], service.deleted_at)

        self.assertEqual(service_dict['status'], 'up')

        # check again within first report_interval time (60)
        service_dict = service_utils.format_service(service)
        self.assertEqual(service_dict['status'], 'up')

        # check update not happen within report_interval time (60+)
        service.created_at = (timeutils.utcnow() -
                              datetime.timedelta(0, 70))
        service_dict = service_utils.format_service(service)
        self.assertEqual(service_dict['status'], 'down')

        # check update happened after report_interval time (60+)
        service.updated_at = (timeutils.utcnow() -
                              datetime.timedelta(0, 70))
        service_dict = service_utils.format_service(service)
        self.assertEqual(service_dict['status'], 'down')

        # check update happened within report_interval time (60)
        service.updated_at = (timeutils.utcnow() -
                              datetime.timedelta(0, 50))
        service_dict = service_utils.format_service(service)
        self.assertEqual(service_dict['status'], 'up')
