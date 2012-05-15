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

logger = logging.getLogger('heat.engine.wait_condition')


class WaitConditionHandle(Resource):
    '''
    the main point of this class is to :
    have no dependancies (so the instance can reference it)
    generate a unique url (to be returned in the refernce)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    '''

    def __init__(self, name, json_snippet, stack):
        super(WaitConditionHandle, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        self.instance_id = '%s/stacks/%s/resources/%s' % \
                           (self.stack.metadata_server,
                            self.stack.name,
                            self.name)

        self.state_set(self.CREATE_COMPLETE)

    def validate(self):
        '''
        Validate the wait condition
        '''
        return None

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)
        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        '''
        Return the Wait Condition Signal URL
        '''
        return unicode(self.instance_id)


class WaitCondition(Resource):

    def __init__(self, name, json_snippet, stack):
        super(WaitCondition, self).__init__(name, json_snippet, stack)
        self.instance_id = ''
        self.resource_id = None

        self.timeout = int(self.t['Properties']['Timeout'])
        self.count = int(self.t['Properties'].get('Count', '1'))

    def validate(self):
        '''
        Validate the wait condition
        '''
        if not 'Handle' in self.t['Properties']:
            return {'Error': \
                    'Handle Property must be provided'}
        if self.count < 1:
            return {'Error': \
                    'Count must be greater than 0'}
        if self.timeout < 1:
            return {'Error': \
                    'Timeout must be greater than 0'}

    def _get_handle_resource_id(self):
        if self.resource_id == None:
            self.handle_url = self.t['Properties'].get('Handle', None)
            self.resource_id = self.handle_url.split('/')[-1]
            return self.resource_id

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        self._get_handle_resource_id()

        # keep polling our Metadata to see if the cfn-signal has written
        # it yet. The execution here is limited by timeout.
        print 'timeout %d' % self.timeout
        tmo = eventlet.Timeout(self.timeout)
        status = 'WAITING'
        reason = ''
        try:
            while status == 'WAITING':
                pt = None
                if self.stack.parsed_template_id:
                    try:
                        pt = db_api.parsed_template_get(None,
                                             self.stack.parsed_template_id)
                    except Exception as ex:
                        if 'not found' in ex:
                            # entry deleted
                            return
                        else:
                            pass

                if pt:
                    res = pt.template['Resources'][self.resource_id]
                    metadata = res.get('Metadata', {})
                    status = metadata.get('Status', 'WAITING')
                    reason = metadata.get('Reason', 'Reason not provided')
                    logger.debug('got %s' % json.dumps(metadata))
                if status == 'WAITING':
                    logger.debug('Waiting some more for the Metadata[Status]')
                    eventlet.sleep(30)
        except eventlet.Timeout, t:
            if t is not tmo:
                # not my timeout
                raise
            else:
                status = 'TIMEDOUT'
                reason = 'Timed out waiting for instance'
        finally:
            tmo.cancel()

        if status == 'SUCCESS':
            self.state_set(self.CREATE_COMPLETE,
                           '%s: %s' % (self.name, reason))
        else:
            raise exception.Error(reason)

    def delete(self):
        if self.state == self.DELETE_IN_PROGRESS or \
           self.state == self.DELETE_COMPLETE:
            return

        self.state_set(self.DELETE_IN_PROGRESS)
        Resource.delete(self)
        self.state_set(self.DELETE_COMPLETE)

    def FnGetRefId(self):
        return unicode(self.name)

    def FnGetAtt(self, key):
        res = None
        self._get_handle_resource_id()
        if key == 'Data':
            resource = self.stack.t['Resources'][self.resource_id]
            res = resource['Metadata']['Data']
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.debug('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)
