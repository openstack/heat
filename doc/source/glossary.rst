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

   constraint
     Defines valid input :term:`parameters` for a :term:`template`.

   dependency
     When a :term:`resource` must wait for another resource to finish
     creation before being created itself. Heat adds an implicit
     dependency when a resource references another resource or one of
     its :term:`attributes <resource attribute>`. An explicit
     dependency can also be created by the user in the template
     definition.

   environment
     Used to affect the run-time behavior of the template. Provides a
     way to override the default resource implementation and
     parameters passed to Heat. See :ref:`Environments`.

   Heat Orchestration Template
     A particular :term:`template` format that is native to Heat.
     Heat Orchestration Templates are expressed in YAML and are not
     backwards-compatible with CloudFormation templates.

   HOT
     An acronym for ":term:`Heat Orchestration Template`".

   input parameters
     See :term:`parameters`.

   Metadata
     May refer to :term:`Resource Metadata`, :term:`Nova Instance
     metadata`, or the :term:`Metadata service`.

   Metadata service
     A Compute service that enables virtual machine instances to
     retrieve instance-specific data. See :nova-doc:`Nova Metadata
     service documentation <user/metadata.html#metadata-service>`.

   multi-region
     A feature of Heat that supports deployment to multiple regions.

   nested resource
     A :term:`resource` instantiated as part of a :term:`nested
     stack`.

   nested stack
     A :term:`template` referenced by URL inside of another template.
     Used to reduce redundant resource definitions and group complex
     architectures into logical groups.

   Nova Instance metadata
     User-provided *key:value* pairs associated with a Compute
     Instance. See `Instance-specific data (OpenStack Operations Guide)`_.

     .. _Instance-specific data (OpenStack Operations Guide): https://wiki.openstack.org/wiki/OpsGuide/User-Facing_Operations#using-instance-specific-data

   OpenStack
     Open source software for building private and public clouds.

   orchestrate
     Arrange or direct the elements of a situation to produce a
     desired effect.

   outputs
     A top-level block in a :term:`template` that defines what data
     will be returned by a stack after instantiation.

   parameters
     A top-level block in a :term:`template` that defines what data
     can be passed to customise a template when it is used to create
     or update a :term:`stack`.

   provider resource
     A :term:`resource` implemented by a :term:`provider
     template`. The parent resource's properties become the
     :term:`nested stack's <nested stack>` parameters.

   provider template
     Allows user-definable :term:`resource providers <resource
     provider>` to be specified via :term:`nested stacks <nested
     stack>`. The nested stack's :term:`outputs` become the parent
     stack's :term:`attributes <resource attribute>`.

   resource
     An element of OpenStack infrastructure instantiated from a
     particular :term:`resource provider`. See also :term:`nested
     resource`.

   resource attribute
     Data that can be obtained from a :term:`resource`, e.g. a
     server's public IP or name. Usually passed to another resource's
     :term:`properties <resource property>` or added to the stack's
     :term:`outputs`.

   resource group
     A :term:`resource provider` that creates one or more identically
     configured :term:`resources <resource>` or :term:`nested
     resources <nested resource>`.

   Resource Metadata
     A :term:`resource property` that contains CFN-style template
     metadata. See `AWS::CloudFormation::Init (AWS CloudFormation User Guide)`_

     .. _AWS::CloudFormation::Init (AWS CloudFormation User Guide): https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-init.html

   resource plugin
     Python code that understands how to instantiate and manage a
     :term:`resource`. See `Heat Resource Plugins (OpenStack wiki)`_.

     .. _Heat Resource Plugins (OpenStack wiki): https://wiki.openstack.org/wiki/Heat/Plugins#Heat_Resource_Plugins

   resource property
     Data utilized for the instantiation of a :term:`resource`. Can be
     defined statically in a :term:`template` or passed in as
     :term:`input parameters <parameters>`.

   resource provider
     The implementation of a particular resource type. May be a
     :term:`resource plugin` or a :term:`provider template`.

   stack
     A collection of instantiated :term:`resources <resource>` that
     are defined in a single :term:`template`.

   stack resource
     A :term:`resource provider` that allows the management of a
     :term:`nested stack` as a :term:`resource` in a parent stack.

   template
     An orchestration document that details everything needed to carry
     out an :term:`orchestration <orchestrate>`.

   template resource
     See :term:`provider resource`.

   user data
     A :term:`resource property` that contains a user-provided data
     blob. User data gets passed to `cloud-init`_ to automatically
     configure instances at boot time. See also :nova-doc:`Nova User data
     documentation <user/metadata.html#user-provided-data>`.

     .. _cloud-init: https://cloudinit.readthedocs.io/

   wait condition
     A :term:`resource provider` that provides a way to communicate
     data or events from servers back to the orchestration
     engine. Most commonly used to pause the creation of the
     :term:`stack` while the server is being configured.
