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

import uuid

from oslo_utils import timeutils

from heat.rpc import listener_client

SERVICE_KEYS = (
    SERVICE_ID,
    SERVICE_HOST,
    SERVICE_HOSTNAME,
    SERVICE_BINARY,
    SERVICE_TOPIC,
    SERVICE_ENGINE_ID,
    SERVICE_REPORT_INTERVAL,
    SERVICE_CREATED_AT,
    SERVICE_UPDATED_AT,
    SERVICE_DELETED_AT,
    SERVICE_STATUS
) = (
    'id',
    'host',
    'hostname',
    'binary',
    'topic',
    'engine_id',
    'report_interval',
    'created_at',
    'updated_at',
    'deleted_at',
    'status'
)


def format_service(service):
    if service is None:
        return

    status = 'down'
    if service.updated_at is not None:
        if ((timeutils.utcnow() - service.updated_at).total_seconds()
                <= service.report_interval):
            status = 'up'
    else:
        if ((timeutils.utcnow() - service.created_at).total_seconds()
                <= service.report_interval):
            status = 'up'

    result = {
        SERVICE_ID: service.id,
        SERVICE_BINARY: service.binary,
        SERVICE_ENGINE_ID: service.engine_id,
        SERVICE_HOST: service.host,
        SERVICE_HOSTNAME: service.hostname,
        SERVICE_TOPIC: service.topic,
        SERVICE_REPORT_INTERVAL: service.report_interval,
        SERVICE_CREATED_AT: service.created_at,
        SERVICE_UPDATED_AT: service.updated_at,
        SERVICE_DELETED_AT: service.deleted_at,
        SERVICE_STATUS: status
    }
    return result


def engine_alive(context, engine_id):
    return listener_client.EngineListenerClient(
        engine_id).is_alive(context)


def generate_engine_id():
    return str(uuid.uuid4())
