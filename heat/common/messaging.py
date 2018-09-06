# -*- coding: utf-8 -*-
# Copyright 2013 eNovance <licensing@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import eventlet
from oslo_config import cfg
import oslo_messaging
from oslo_messaging.rpc import dispatcher
from osprofiler import profiler

from heat.common import context


TRANSPORT = None
NOTIFICATIONS_TRANSPORT = None
NOTIFIER = None


class RequestContextSerializer(oslo_messaging.Serializer):
    def __init__(self, base):
        self._base = base

    def serialize_entity(self, ctxt, entity):
        if not self._base:
            return entity
        return self._base.serialize_entity(ctxt, entity)

    def deserialize_entity(self, ctxt, entity):
        if not self._base:
            return entity
        return self._base.deserialize_entity(ctxt, entity)

    @staticmethod
    def serialize_context(ctxt):
        _context = ctxt.to_dict()
        prof = profiler.get()
        if prof:
            trace_info = {
                "hmac_key": prof.hmac_key,
                "base_id": prof.get_base_id(),
                "parent_id": prof.get_id()
            }
            _context.update({"trace_info": trace_info})
        return _context

    @staticmethod
    def deserialize_context(ctxt):
        trace_info = ctxt.pop("trace_info", None)
        if trace_info:
            profiler.init(**trace_info)
        return context.RequestContext.from_dict(ctxt)


def get_specific_transport(url, optional, exmods, is_for_notifications=False):
    try:
        if is_for_notifications:
            return oslo_messaging.get_notification_transport(
                cfg.CONF, url, allowed_remote_exmods=exmods)
        else:
            return oslo_messaging.get_rpc_transport(
                cfg.CONF, url, allowed_remote_exmods=exmods)
    except oslo_messaging.InvalidTransportURL as e:
        if not optional or e.url:
            # NOTE(sileht): oslo_messaging is configured but unloadable
            # so reraise the exception
            raise
        else:
            return None


def setup_transports(url, optional):
    global TRANSPORT, NOTIFICATIONS_TRANSPORT
    oslo_messaging.set_transport_defaults('heat')
    exmods = ['heat.common.exception']
    TRANSPORT = get_specific_transport(url, optional, exmods)
    NOTIFICATIONS_TRANSPORT = get_specific_transport(url, optional, exmods,
                                                     is_for_notifications=True)


def setup(url=None, optional=False):
    """Initialise the oslo_messaging layer."""
    global NOTIFIER

    if url and url.startswith("fake://"):
        # NOTE(sileht): oslo_messaging fake driver uses time.sleep
        # for task switch, so we need to monkey_patch it
        eventlet.monkey_patch(time=True)
    if not TRANSPORT or not NOTIFICATIONS_TRANSPORT:
        setup_transports(url, optional)
        # In the fake driver, make the dict of exchanges local to each exchange
        # manager, instead of using the shared class attribute. Doing otherwise
        # breaks the unit tests.
        if url and url.startswith("fake://"):
            TRANSPORT._driver._exchange_manager._exchanges = {}

    if not NOTIFIER and NOTIFICATIONS_TRANSPORT:
        serializer = RequestContextSerializer(
            oslo_messaging.JsonPayloadSerializer())
        NOTIFIER = oslo_messaging.Notifier(NOTIFICATIONS_TRANSPORT,
                                           serializer=serializer)


def cleanup():
    """Cleanup the oslo_messaging layer."""
    global TRANSPORT, NOTIFICATIONS_TRANSPORT, NOTIFIER
    if TRANSPORT:
        TRANSPORT.cleanup()
        NOTIFICATIONS_TRANSPORT.cleanup()
        TRANSPORT = NOTIFICATIONS_TRANSPORT = NOTIFIER = None


def get_rpc_server(target, endpoint):
    """Return a configured oslo_messaging rpc server."""
    serializer = RequestContextSerializer(
        oslo_messaging.JsonPayloadSerializer())
    access_policy = dispatcher.DefaultRPCAccessPolicy
    return oslo_messaging.get_rpc_server(TRANSPORT, target, [endpoint],
                                         executor='eventlet',
                                         serializer=serializer,
                                         access_policy=access_policy)


def get_rpc_client(**kwargs):
    """Return a configured oslo_messaging RPCClient."""
    target = oslo_messaging.Target(**kwargs)
    serializer = RequestContextSerializer(
        oslo_messaging.JsonPayloadSerializer())
    return oslo_messaging.RPCClient(TRANSPORT, target,
                                    serializer=serializer)


def get_notifier(publisher_id):
    """Return a configured oslo_messaging notifier."""
    return NOTIFIER.prepare(publisher_id=publisher_id)
