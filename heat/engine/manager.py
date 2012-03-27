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

LOG = logging.getLogger(__name__)


class EngineManager(manager.Manager):
    """Manages the running instances from creation to destruction."""

    def __init__(self, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""

    def create(self, template, stack_id):
        pass

