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

import base64
from datetime import datetime
import logging

from novaclient.v1_1 import client
from novaclient.exceptions import BadRequest
from novaclient.exceptions import NotFound

from heat.common import exception
from heat.common.config import HeatEngineConfigOpts
from heat.db import api as db_api
from heat.engine import checkeddict

logger = logging.getLogger(__file__)


class Resource(object):
    CREATE_IN_PROGRESS = 'CREATE_IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'
    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'
    UPDATE_IN_PROGRESS = 'UPDATE_IN_PROGRESS'
    UPDATE_FAILED = 'UPDATE_FAILED'
    UPDATE_COMPLETE = 'UPDATE_COMPLETE'

    def __new__(cls, name, json, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            return super(Resource, cls).__new__(cls, name, json, stack)

        # Select the correct subclass to instantiate
        import resource_types
        ResourceClass = resource_types.getClass(json['Type'])
        return ResourceClass(name, json, stack)

    def __init__(self, name, json_snippet, stack):
        self.depends_on = []
        self.references = []
        self.stack = stack
        self.name = name
        self.t = stack.resolve_static_data(json_snippet)
        self.properties = checkeddict.Properties(name, self.properties_schema)
        if 'Properties' not in self.t:
            # make a dummy entry to prevent having to check all over the
            # place for it.
            self.t['Properties'] = {}

        resource = db_api.resource_get_by_name_and_stack(self.stack.context,
                                                         name, stack.id)
        if resource:
            self.instance_id = resource.nova_instance
            self.state = resource.state
            self.id = resource.id
        else:
            self.instance_id = None
            self.state = None
            self.id = None
        self._nova = {}

    def nova(self, service_type='compute'):
        if service_type in self._nova:
            return self._nova[service_type]

        if service_type == 'compute':
            service_name = 'nova'
        else:
            service_name = None

        con = self.stack.context
        self._nova[service_type] = client.Client(con.username,
                                                 con.password,
                                                 con.tenant,
                                                 con.auth_url,
                                                 proxy_token=con.auth_token,
                                                 proxy_tenant_id=con.tenant_id,
                                                 service_type=service_type,
                                                 service_name=service_name)
        return self._nova[service_type]

    def calculate_properties(self):
        template = self.stack.resolve_runtime_data(self.t)

        for p, v in template['Properties'].items():
            self.properties[p] = v

    def create(self):
        logger.info('creating %s name:%s' % (self.t['Type'], self.name))
        self.calculate_properties()
        self.properties.validate()

    def validate(self):
        logger.info('validating %s name:%s' % (self.t['Type'], self.name))

        try:
            self.calculate_properties()
        except ValueError as ex:
                return {'Error': '%s' % str(ex)}
        self.properties.validate()

    def instance_id_set(self, inst):
        self.instance_id = inst

    def state_set(self, new_state, reason="state changed"):
        if new_state is self.CREATE_COMPLETE or \
           new_state is self.CREATE_FAILED:
            try:
                rs = {}
                rs['state'] = new_state
                rs['stack_id'] = self.stack.id
                rs['parsed_template_id'] = self.stack.parsed_template_id
                rs['nova_instance'] = self.instance_id
                rs['name'] = self.name
                rs['stack_name'] = self.stack.name
                new_rs = db_api.resource_create(self.stack.context, rs)
                self.id = new_rs.id
                if new_rs.stack:
                    new_rs.stack.update_and_save({'updated_at':
                        datetime.utcnow()})

            except Exception as ex:
                logger.warn('db error %s' % str(ex))
        elif self.id is not None:
            try:
                rs = db_api.resource_get(self.stack.context, self.id)
                rs.update_and_save({'state': new_state})
                if rs.stack:
                    rs.stack.update_and_save({'updated_at': datetime.utcnow()})
            except Exception as ex:
                logger.warn('db error %s' % str(ex))

        if new_state != self.state:
            ev = {}
            ev['logical_resource_id'] = self.name
            ev['physical_resource_id'] = self.instance_id
            ev['stack_id'] = self.stack.id
            ev['stack_name'] = self.stack.name
            ev['resource_status'] = new_state
            ev['name'] = new_state
            ev['resource_status_reason'] = reason
            ev['resource_type'] = self.t['Type']
            self.calculate_properties()
            ev['resource_properties'] = dict(self.properties)
            try:
                db_api.event_create(self.stack.context, ev)
            except Exception as ex:
                logger.warn('db error %s' % str(ex))
            self.state = new_state

    def delete(self):
        logger.info('deleting %s name:%s inst:%s db_id:%s' %
                    (self.t['Type'], self.name,
                     self.instance_id, str(self.id)))

    def FnGetRefId(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/ \
            intrinsic-function-reference-ref.html
        '''
        if self.instance_id is not None:
            return unicode(self.instance_id)
        else:
            return unicode(self.name)

    def FnGetAtt(self, key):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/ \
        intrinsic-function-reference-getatt.html
        '''
        return unicode(self.name)

    def FnBase64(self, data):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/ \
            intrinsic-function-reference-base64.html
        '''
        return base64.b64encode(data)

    def strict_dependency(self):
        '''
        If True, this resource must be created before it can be referenced.
        '''
        return True


class GenericResource(Resource):
    properties_schema = {}

    def __init__(self, name, json_snippet, stack):
        super(GenericResource, self).__init__(name, json_snippet, stack)

    def create(self):
        if self.state is not None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(GenericResource, self).create()
        logger.info('creating GenericResource %s' % self.name)
        self.state_set(self.CREATE_COMPLETE)
