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

==================
Upgrades Guideline
==================

This document outlines several steps and notes for operators to reference when
upgrading their heat from previous versions of OpenStack.

.. note::

  This document is only tested in the case of upgrading between sequential
  releases.


Plan to upgrade
===============

* Read and ensure you understand the `release notes
  <https://docs.openstack.org/releasenotes/heat/>`_ for the next release.

* Make a backup of your database.

* Upgrades are only supported one series at a time, or within a series.

Cold Upgrades
=============

Heat already supports "`cold-upgrades`_", where the heat services have to be
down during the upgrade. For time-consuming upgrades, it may be unacceptable
for the services to be unavailable for a long period of time. This type of
upgrade is quite simple, follow the bellow steps:

1. Stop all heat-api and heat-engine services.

2. Uninstall old code.

3. Install new code.

4. Update configurations.

5. Do Database sync (most time-consuming step)

6. Start all heat-api and heat-engine services.

Rolling Upgrades
================

.. note::

  Rolling Upgrade is supported since Pike, which means operators can rolling
  upgrade Heat services from Ocata to Pike release with minimal downtime.

A rolling upgrade would provide a better experience for the users and
operators of the cloud. A rolling upgrade would allow individual heat-api and
heat-engine services to be upgraded one at a time, with the rest of the
services still available. This upgrade would have minimal downtime. Please
check `spec about rolling upgrades`_.

Prerequisites
-------------

* Multiple Heat nodes.

* A load balancer or some other type of redirection device is being used in
  front of nodes that run heat-api services in such a way that a node can be
  dropped out of rotation. That node continues running the Heat services
  (heat-api or heat-engine) but is no longer having requests routed to it.

Procedure
---------

These following steps are the process to upgrade Heat with minimal downtime:

1. Install the code for the next version of Heat either in a virtual
   environment or a separate control plane node, including all the python
   dependencies.

2. Using the newly installed heat code, run the following command to sync the
   database up to the most recent version. These schema change operations
   should have minimal or no effect on performance, and should not cause any
   operations to fail.

    .. code-block:: bash

      heat-manage db_sync

3. At this point, new columns and tables may exist in the database. These DB
   schema changes are done in a way that both the N and N+1 release can
   perform operations against the same schema.

4. Create a new rabbitmq vhost for the new release and change the
   transport_url configuration in heat.conf file to be:

   ``transport_url = rabbit://<user>:<password>@<host>:5672/<new_vhost>``

   for all upgrade services.

5. Stop heat-engine gracefully, Heat has supported graceful shutdown features
   (see the `spec about rolling upgrades`_). Then start new heat-engine with
   new code (and corresponding configuration).

   .. note::

      Remember to do Step 4, this would ensure that the existing engines
      would not communicate with the new engine.

6. A heat-api service is then upgraded and started with the new rabbitmq
   vhost.

   .. note::

      The second way to do this step is switch heat-api service to use new
      vhost first (but remember not to shut down heat-api) and upgrade it.

7. The above process can be followed till all heat-api and heat-engine
   services are upgraded.

   .. note::

      Make sure that all heat-api services has been upgraded before you
      start to upgrade the last heat-engine service.

   .. warning::

      With the convergence architecture, whenever a resource completes the
      engine will send RPC messages to another (or the same) engine to start
      work on the next resource(s) to be processed. If the last engine is
      going to be shut down gracefully, it will finish what it is working on,
      which may post more messages to queues. It means the graceful shutdown
      does not wait for queues to drain. The shutdown leaves some messages
      unprocessed and any IN_PROGRESS stacks would get stuck without any
      forward progress. The operator must be careful when shutting down the
      last engine, make sure queues have no unprocessed messages before
      doing it. The operator can check the queues directly with `RabbitMQ`_'s
      management plugin.

8. Once all services are upgraded, double check the DB and services

References
==========

.. _cold-upgrades: https://governance.openstack.org/tc/reference/tags/assert_supports-upgrade.html

.. _spec about rolling upgrades: https://review.openstack.org/#/c/407989/

.. _RabbitMQ: http://www.rabbitmq.com/management.html
