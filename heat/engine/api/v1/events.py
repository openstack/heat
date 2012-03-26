# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Implementation of the stacks server WSGI controller.
"""
import json
import logging

import webob
from webob.exc import (HTTPNotFound,
                       HTTPConflict,
                       HTTPBadRequest)

from heat.common import exception
from heat.common import wsgi

from heat.engine import parser
from heat.engine import simpledb

logger = logging.getLogger('heat.engine.api.v1.events')


class EventsController(object):
    '''
    The controller for the events child "resource"
    stacks/events
    '''

    def __init__(self, conf):
        self.conf = conf

    def index(self, req, stack_id):
        return simpledb.events_get(stack_id)

def create_resource(conf):
    """Events resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = wsgi.JSONResponseSerializer()
    return wsgi.Resource(EventsController(conf), deserializer, serializer)
