# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Handles all processes relating to instances (guest vms).

The :py:class:`ComputeManager` class is a :py:class:`heat.manager.Manager` that
handles RPC calls relating to creating instances.  It is responsible for
building a disk image, launching it via the underlying virtualization driver,
responding to calls to check its state, attaching persistent storage, and
terminating it.

**Related Flags**

:instances_path:  Where instances are kept on disk
:compute_driver:  Name of class that is used to handle virtualization, loaded
                  by :func:`heat.utils.import_object`

"""

import contextlib
import functools
import os
import socket
import sys
import tempfile
import time
import traceback
import logging

from eventlet import greenthread

import heat.context
from heat.common import exception
from heat import manager
from heat.openstack.common import cfg
from heat import rpc
from heat.engine import parser
from heat.engine import simpledb

logger = logging.getLogger('heat.engine.api.manager')
stack_db = {}


class EngineManager(manager.Manager):
    """Manages the running instances from creation to destruction."""

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""

    def list_stacks(self, context):
        logger.info('context is %s' % context)
        res = {'stacks': [] }
        for s in stack_db:
            mem = {}
            mem['StackId'] = stack_db[s]['StackId']
            mem['StackName'] = s
            mem['CreationTime'] = 'now'
            try:
                mem['TemplateDescription'] = stack_db[s]['Description']
                mem['StackStatus'] = stack_db[s]['StackStatus']
            except:
                mem['TemplateDescription'] = 'No description'
                mem['StackStatus'] = 'unknown'
            res['stacks'].append(mem)

        return res

    def show_stack(self, context, stack_name):

        res = {'stacks': [] }
        if stack_db.has_key(stack_name):
            mem = {}
            mem['StackId'] = stack_db[stack_name]['StackId']
            mem['StackName'] = stack_name
            mem['CreationTime'] = 'TODO'
            mem['LastUpdatedTime'] = 'TODO'
            mem['NotificationARNs'] = 'TODO'
            mem['Outputs'] = [{'Description': 'TODO', 'OutputKey': 'TODO', 'OutputValue': 'TODO' }]
            mem['Parameters'] = stack_db[stack_name]['Parameters']
            mem['StackStatusReason'] = 'TODO'
            mem['TimeoutInMinutes'] = 'TODO'
            try:
                mem['TemplateDescription'] = stack_db[stack_name]['Description']
                mem['StackStatus'] = stack_db[stack_name]['StackStatus']
            except:
                mem['TemplateDescription'] = 'No description'
                mem['StackStatus'] = 'unknown'
            res['stacks'].append(mem)
        else:
            # XXX: Not sure how to handle this case here.. original returned NOT FOUND error.
            return {'Error': 'No stack by that name'}

        return res

    def create_stack(self, context, stack_name, template):
        if stack_db.has_key(stack_name):
            return {'Error': 'Stack already exists with that name.'}

        stack_db[stack_name] = template
        stack_db[stack_name].start()

        return {'stack': {'id': stack_name}}

    def delete_stack(self, req, stack_name):
        if not stack_db.has_key(stack_name):
            return {'Error': 'No stack by that name'}

        logger.info('deleting stack %s' % stack_name)
        del stack_db[stack_name]
        return None

    def list_events(self, context, stack_name):
        return simpledb.events_get(stack_name)

