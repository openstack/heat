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

==========
 Glossary
==========

.. glossary::
   :sorted:

   API server
     HTTP REST API service for heat.

   CFN
     An abbreviated form of "AWS CloudFormation".

   Constraint
     Defines valid input :term:`parameters` for a :term:`template`.

   Dependency
     When a :term:`resource` must wait for another resource to finish
     creation before being created itself. Heat adds an implicit
     dependency when a resource references another resource or one of
     its :term:`attributes <resource attribute>`. An explicit
     dependency can also be created by the user in the template
     definition.

   Environment
     Used to affect the run-time behavior of the template. Provides a
     way to override the default resource implementation and
     parameters passed to Heat. See :ref:`Environments`.

   Heat Orchestration Template
     A particular :term:`template` format that is native to Heat.
     Heat Orchestration Templates are expressed in YAML and are not
     backwards-compatible with CloudFormation templates.

   HOT
     An acronym for ":term:`Heat Orchestration Template`".

   Input parameters
     See :term:`Parameters`.

   Metadata
     May refer to :term:`Resource Metadata`, :term:`Nova Instance
     metadata`, or the :term:`Metadata service`.

   Metadata service
     A Compute service that enables virtual machine instances to
     retrieve instance-specific data. See `Metadata
     service (OpenStack Administrator Guide)`_.

     .. _Metadata service (OpenStack Administrator Guide): https://docs.openstack.org/nova/latest/admin/networking-nova.html#metadata-service

   Multi-region
     A feature of Heat that supports deployment to multiple regions.

   Nested resource
     A :term:`resource` instantiated as part of a :term:`nested
     stack`.

   Nested stack
     A :term:`template` referenced by URL inside of another template.
     Used to reduce redundant resource definitions and group complex
     architectures into logical groups.

   Nova Instance metadata
     User-provided *key:value* pairs associated with a Compute
     Instance. See `Instance-specific data (OpenStack Operations Guide)`_.

     .. _Instance-specific data (OpenStack Operations Guide): https://wiki.openstack.org/wiki/OpsGuide/User-Facing_Operations#using-instance-specific-data

   OpenStack
     Open source software for building private and public clouds.

   Orchestrate
     Arrange or direct the elements of a situation to produce a
     desired effect.

   Outputs
     A top-level block in a :term:`template` that defines what data
     will be returned by a stack after instantiation.

   Parameters
     A top-level block in a :term:`template` that defines what data
     can be passed to customise a template when it is used to create
     or update a :term:`stack`.

   Provider resource
     A :term:`resource` implemented by a :term:`provider
     template`. The parent resource's properties become the
     :term:`nested stack's <nested stack>` parameters.

   Provider template
     Allows user-definable :term:`resource providers <resource
     provider>` to be specified via :term:`nested stacks <nested
     stack>`. The nested stack's :term:`outputs` become the parent
     stack's :term:`attributes <resource attribute>`.

   Resource
     An element of OpenStack infrastructure instantiated from a
     particular :term:`resource provider`. See also :term:`Nested
     resource`.

   Resource attribute
     Data that can be obtained from a :term:`resource`, e.g. a
     server's public IP or name. Usually passed to another resource's
     :term:`properties <resource property>` or added to the stack's
     :term:`outputs`.

   Resource group
     A :term:`resource provider` that creates one or more identically
     configured :term:`resources <resource>` or :term:`nested
     resources <nested resource>`.

   Resource Metadata
     A :term:`resource property` that contains CFN-style template
     metadata. See `AWS::CloudFormation::Init (AWS CloudFormation User Guide)`_

     .. _AWS::CloudFormation::Init (AWS CloudFormation User Guide): https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-init.html

   Resource plugin
     Python code that understands how to instantiate and manage a
     :term:`resource`. See `Heat Resource Plugins (OpenStack wiki)`_.

     .. _Heat Resource Plugins (OpenStack wiki): https://wiki.openstack.org/wiki/Heat/Plugins#Heat_Resource_Plugins

   Resource property
     Data utilized for the instantiation of a :term:`resource`. Can be
     defined statically in a :term:`template` or passed in as
     :term:`input parameters <parameters>`.

   Resource provider
     The implementation of a particular resource type. May be a
     :term:`Resource plugin` or a :term:`Provider template`.

   Stack
     A collection of instantiated :term:`resources <resource>` that
     are defined in a single :term:`template`.

   Stack resource
     A :term:`resource provider` that allows the management of a
     :term:`nested stack` as a :term:`resource` in a parent stack.

   Template
     An orchestration document that details everything needed to carry
     out an :term:`orchestration <orchestrate>`.

   Template resource
     See :term:`Provider resource`.

   User data
     A :term:`resource property` that contains a user-provided data
     blob. User data gets passed to `cloud-init`_ to automatically
     configure instances at boot time. See also `User data (OpenStack
     End User Guide)`_.

     .. _User data (OpenStack End User Guide): https://docs.openstack.org/nova/latest/user/user-data.html
     .. _cloud-init: https://cloudinit.readthedocs.io/

   Wait condition
     A :term:`resource provider` that provides a way to communicate
     data or events from servers back to the orchestration
     engine. Most commonly used to pause the creation of the
     :term:`stack` while the server is being configured.
