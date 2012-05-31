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

    def __init__(self, name, json_snippet, stack):
        self.t = json_snippet
        self.depends_on = []
        self.references = []
        self.stack = stack
        self.name = name
        self.properties = checkeddict.Properties(name, self.properties_schema)
        if not 'Properties' in self.t:
            # make a dummy entry to prevent having to check all over the
            # place for it.
            self.t['Properties'] = {}

        resource = db_api.resource_get_by_name_and_stack(None, name, stack.id)
        if resource:
            self.instance_id = resource.nova_instance
            self.state = resource.state
            self.id = resource.id
        else:
            self.instance_id = None
            self.state = None
            self.id = None
        self._nova = {}

        stack.resolve_static_refs(self.t)
        stack.resolve_find_in_map(self.t)

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

    def create(self):
        logger.info('creating %s name:%s' % (self.t['Type'], self.name))

        self.stack.resolve_attributes(self.t)
        self.stack.resolve_joins(self.t)
        self.stack.resolve_base64(self.t)
        for p in self.t['Properties']:
            self.properties[p] = self.t['Properties'][p]
        self.properties.validate()

    def validate(self):
        logger.info('validating %s name:%s' % (self.t['Type'], self.name))

        self.stack.resolve_attributes(self.t)
        self.stack.resolve_joins(self.t)
        self.stack.resolve_base64(self.t)

        try:
            for p in self.t['Properties']:
                self.properties[p] = self.t['Properties'][p]
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
                new_rs = db_api.resource_create(None, rs)
                self.id = new_rs.id
                if new_rs.stack:
                    new_rs.stack.update_and_save({'updated_at':
                        datetime.utcnow()})

            except Exception as ex:
                logger.warn('db error %s' % str(ex))
        elif new_state is not self.CREATE_IN_PROGRESS:
            rs = db_api.resource_get(None, self.id)
            rs.update_and_save({'state': new_state})
            if rs.stack:
                rs.stack.update_and_save({'updated_at': datetime.utcnow()})

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
            ev['resource_properties'] = self.t['Properties']
            try:
                db_api.event_create(None, ev)
            except Exception as ex:
                logger.warn('db error %s' % str(ex))
            self.state = new_state

    def delete(self):
        self.reload()
        logger.info('deleting %s name:%s inst:%s db_id:%s' %
                    (self.t['Type'], self.name,
                     self.instance_id, str(self.id)))

    def reload(self):
        '''
        The point of this function is to get the Resource instance back
        into the state that it was just after it was created. So we
        need to retrieve things like ipaddresses and other variables
        used by FnGetAtt and FnGetRefId. classes inheriting from Resource
        might need to override this, but still call it.
        This is currently used by stack.get_outputs()
        '''
        logger.info('reloading %s name:%s instance_id:%s' %
                    (self.t['Type'], self.name, self.instance_id))
        self.stack.resolve_attributes(self.t)

    def FnGetRefId(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/ \
            intrinsic-function-reference-ref.html
        '''
        if self.instance_id != None:
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
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        super(GenericResource, self).create()
        logger.info('creating GenericResource %s' % self.name)
        self.state_set(self.CREATE_COMPLETE)
