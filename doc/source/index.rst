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

==================================
Welcome to the Heat documentation!
==================================
Heat is a service to orchestrate composite cloud applications
using a declarative template format through an OpenStack-native REST API.

Heat's purpose and vision
=========================

* Heat provides a template based orchestration for describing a cloud
  application by executing appropriate :term:`OpenStack` API calls to generate
  running cloud applications.
* A Heat template describes the infrastructure for a cloud application in text
  files which are readable and writable by humans, and can be managed by
  version control tools.
* Templates specify the relationships between resources (e.g. this
  volume is connected to this server). This enables Heat to call out to the
  OpenStack APIs to create all of your infrastructure in the correct order to
  completely launch your application.
* The software integrates other components of OpenStack. The templates allow
  creation of most OpenStack resource types (such as instances, floating ips,
  volumes, security groups, users, etc), as well as some more advanced
  functionality such as instance high availability, instance autoscaling, and
  nested stacks.
* Heat primarily manages infrastructure, but the templates
  integrate well with software configuration management tools such as Puppet
  and Ansible.
* Operators can customise the capabilities of Heat by installing plugins.

This documentation offers information aimed at end-users, operators and
developers of Heat.


Operating Heat
==============

.. toctree::
    :maxdepth: 1

    install/index
    operating_guides/httpd
    configuration/index
    admin/index
    operating_guides/scale_deployment
    operating_guides/upgrades_guide
    man/index

Using Heat
==========

.. toctree::
    :maxdepth: 1

    getting_started/create_a_stack
    glossary

Working with Templates
----------------------

.. toctree::
    :maxdepth: 1

    template_guide/index
    templates/index

Using the Heat Service
----------------------

- `OpenStack Orchestration API v1 Reference`_
- :python-heatclient-doc:`Python and CLI client <>`

.. _`OpenStack Orchestration API v1 Reference`: https://developer.openstack.org/api-ref/orchestration/v1/

Developing Heat
===============

.. toctree::
    :maxdepth: 2

    developing_guides/index

.. toctree::
    :maxdepth: 1

    api/index

For Contributors
================

* If you are a new contributor to Heat please refer: :doc:`contributor/contributing`

  .. toctree::
    :maxdepth: 2

    contributor/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
