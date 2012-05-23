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

import eventlet
import logging
import json
import os

from heat.common import exception
from heat.db import api as db_api
from heat.engine.resources import Resource

logger = logging.getLogger('heat.engine.escalation_policy')


class EscalationPolicy(Resource):
    properties_schema = {
            'Instance': {'Type': 'String'},
            }

    def __init__(self, name, json_snippet, stack):
        super(EscalationPolicy, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

    def validate(self):
        '''
        Validate the Properties
        '''
        return Resource.validate(self)

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)
        self.state_set(self.CREATE_COMPLETE)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)

        Resource.delete(self)
        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

    def strict_dependency(self):
        return False
