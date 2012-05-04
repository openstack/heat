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
import os

from heat.common import exception
from heat.engine.resources import Resource

logger = logging.getLogger(__file__)


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

        # generate a unique url
        self.instance_id = '%s?%s&%s' % (self.stack.metadata_server,
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
        Wait Condition Signal URL
        example: https://cloudformation-waitcondition-us-east-1.s3.amazonaws.com/arn%3Aaws%3Acloudformation%3Aus-east-1%3A803981987763%3Astack%2Fwaittest%2F054a33d0-bdee-11e0-8816-5081c490a786%2FmyWaitHandle?Expires=1312475488&AWSAccessKeyId=AKIAIOSFODNN7EXAMPLE&Signature=tUsrW3WvWVT46K69zMmgbEkwVGo%3D
        so we need:
        - stackname
        - region
        - self.name (WaitCondition name)
        - Expires
        - AWSAccessKeyId
        - Signature

        '''
        return unicode(self.instance_id)


class WaitCondition(Resource):

    def __init__(self, name, json_snippet, stack):
        super(WaitCondition, self).__init__(name, json_snippet, stack)
        self.instance_id = ''

        self.handle_url = self.t['Properties']['Handle']
        self.timeout = self.t['Properties']['Timeout']

    def create(self):
        if self.state != None:
            return
        self.state_set(self.CREATE_IN_PROGRESS)
        Resource.create(self)

        eventlet.sleep(int(self.timeout) / 2)
#        timeout = Timeout(seconds, exception)
#        try:
            # keep polling the url of the Handle and get the success/failure
            # state of it
            # execution here is limited by timeout
#        except Timeout, t:
#            if t is not timeout:
#                raise # not my timeout
#            else:
#                self.state_set(self.CREATE_FAILED,
#                               '%s Timed out waiting for instance' % \
#                               self.name)
#        finally:
#            timeout.cancel()

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
