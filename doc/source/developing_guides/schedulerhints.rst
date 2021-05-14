..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

====================================
Heat Stack Lifecycle Scheduler Hints
====================================
This is a mechanism whereby when heat processes a stack with Server or Volume
resources, the stack id, root stack id, stack resource uuid, stack resource
name and the path in the stack can be passed by heat to nova and cinder as
scheduler hints.


Enabling the scheduler hints
----------------------------
By default, passing the lifecycle scheduler hints is disabled. To enable it,
set stack_scheduler_hints to True in heat.conf.

The hints
---------
When heat processes a stack, and the feature is enabled, the stack id, root
stack id, stack resource uuid, stack resource name, and the path in the stack
(as a list of comma delimited strings of stackresourcename and stackname) will
be passed by heat to nova and cinder as scheduler hints.

Purpose
-------
A heat provider may have a need for custom code to examine stack requests
prior to performing the operations to create or update a stack. After the
custom code completes, the provider may want to provide hints to the nova
or cinder schedulers with stack related identifiers, for processing by
any custom scheduler plug-ins configured for nova or cinder.
