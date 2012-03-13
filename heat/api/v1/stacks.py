# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
# All Rights Reserved.
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
/stack endpoint for heat v1 API
"""

import httplib
import json
import logging
import sys

import webob
from webob.exc import (HTTPNotFound,
                       HTTPConflict,
                       HTTPBadRequest)

from heat.common import exception
from heat.common import wsgi

logger = logging.getLogger('heat.api.v1.stacks')

class StackController(object):

    """
    WSGI controller for stacks resource in heat v1 API

    """

    def __init__(self, options):
        self.options = options

    def list(self, req):
        """
        Returns the following information for all stacks:
        """
        return {'ListStacksResponse': [
            {'ListStacksResult': [
                {'StackSummaries': [
                    {'member': [
                        {'StackId': 'arn:aws:cloudformation:us-east-1:1234567:stack/TestCreate1/aaaaa',
                            'StackStatus': 'CREATE_IN_PROGRESS',
                            'StackName': 'vpc1',
                            'CreationTime': '2011-05-23T15:47:44Z',
                            'TemplateDescription': 'Creates one EC2 instance and a load balancer.',
                        }]
                    },
                    {'member': [
                        {'StackId': 'arn:aws:cloudformation:us-east-1:1234567:stack/TestDelete2/bbbbb',
                            'StackStatus': 'DELETE_COMPLETE',
                            'StackName': 'WP1',
                            'CreationTime': '2011-03-05T19:57:58Z',
                            'TemplateDescription': 'A simple basic Cloudformation Template.',
                        }]
                    }
                    ]}]}]}

 
    def describe(self, req):

        return {'stack': [
                {'id': 'id',
                 'name': '<stack NAME',
                 'disk_format': '<DISK_FORMAT>',
                 'container_format': '<CONTAINER_FORMAT>' } ] }
 

    def create(self, req):
        for p in req.params:
            print 'create %s=%s' % (p, req.params[p])

        return {'CreateStackResult': [{'StackId': '007'}]}

    def update(self, req, id, image_meta, image_data):
        """
        Updates an existing image with the registry.

        :param request: The WSGI/Webob Request object
        :param id: The opaque image identifier

        :retval Returns the updated image information as a mapping
        """

        return {'image_meta': 'bla'}


    def delete(self, req, id):
        """
        Deletes the image and all its chunks from heat

        :param req: The WSGI/Webob Request object
        :param id: The opaque image identifier

        :raises HttpBadRequest if image registry is invalid
        :raises HttpNotFound if image or any chunk is not available
        :raises HttpNotAuthorized if image or any chunk is not
                deleteable by the requesting user
        """
    

class StackDeserializer(wsgi.JSONRequestDeserializer):
    """Handles deserialization of specific controller method requests."""

    def _deserialize(self, request):
        result = {}
        return result

    def create(self, request):
        return self._deserialize(request)

    def update(self, request):
        return self._deserialize(request)


class StackSerializer(wsgi.JSONResponseSerializer):
    """Handles serialization of specific controller method responses."""

    def _inject_location_header(self, response, image_meta):
        response.headers['Location'] = 'location'

    def _inject_checksum_header(self, response, image_meta):
        response.headers['ETag'] = 'checksum'

    def update(self, response, result):
        return

    def create(self, response, result):
        """ Create """
        response.status = 201
        response.headers['Content-Type'] = 'application/json'
        response.body = self.to_json(dict(CreateStackResult=result))
        self._inject_location_header(response, result)
        self._inject_checksum_header(response, result)
        return response

def handle_stack(self, req, id):
    return {'got-stack-id': id}

def create_resource(options):
    """Stacks resource factory method"""
    deserializer = StackDeserializer()
    serializer = StackSerializer()
    return wsgi.Resource(StackController(options), deserializer, serializer)
