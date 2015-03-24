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

==================================================
Welcome to the Heat developer documentation!
==================================================
Heat is a service to :term:`orchestrate` multiple composite cloud
applications using the AWS CloudFormation template format, through
both an OpenStack-native ReST API and a CloudFormation-compatible Query API.

What is the purpose of the project and vision for it?
=====================================================

* Heat provides a template based orchestration for describing a cloud application by executing appropriate :term:`OpenStack` API calls to generate running cloud applications.
* The software integrates other core components of OpenStack into a one-file template system. The templates allow creation of most OpenStack resource types (such as instances, floating ips, volumes, security groups, users, etc), as well as some more advanced functionality such as instance high availability, instance autoscaling, and nested stacks. By providing very tight integration with other OpenStack core projects, all OpenStack core projects could receive a larger user base.
* Allow deployers to integrate with Heat directly or by adding custom plugins.

This documentation offers information on how heat works and how to contribute to the project.

Getting Started
===============

.. toctree::
    :maxdepth: 1

    getting_started/index
    templates/index
    template_guide/index
    glossary

Man Pages
=========

.. toctree::
    :maxdepth: 2

    man/index

Developers Documentation
========================
.. toctree::
   :maxdepth: 1

   architecture
   pluginguide
   schedulerhints

API Documentation
========================

-  `Heat REST API Reference (OpenStack API Complete Reference - Orchestration)`_

   .. _`Heat REST API Reference (OpenStack API Complete Reference - Orchestration)`: http://api.openstack.org/api-ref-orchestration-v1.html

Operations Documentation
========================
.. toctree::
   :maxdepth: 1

   scale_deployment

Code Documentation
==================
.. toctree::
   :maxdepth: 3

   sourcecode/autoindex

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
