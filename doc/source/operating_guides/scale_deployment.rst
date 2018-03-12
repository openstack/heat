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

====================
Scaling a Deployment
====================

When deploying in an environment where a large number of incoming requests need
to be handled, the API and engine services can be overloaded. In those
scenarios, in order to increase the system performance, it can be helpful to run
multiple load-balanced APIs and engines.

This guide details how to scale out the REST API, the CFN API, and the engine,
also known as the *heat-api*, *heat-api-cfn*, and *heat-engine* services,
respectively.

.. _scale_deployment_assumptions:

Assumptions
===========

This guide, using a devstack installation of OpenStack, assumes that:

    1. You have configured devstack from `Single Machine Installation Guide
       <https://docs.openstack.org/devstack/latest/guides/single-machine.html>`_;
    2. You have set up heat on devstack, as defined at :doc:`heat and DevStack
       <../getting_started/on_devstack>`;
    3. You have installed HAProxy_ on the devstack
       server.

Architecture
============

This section shows the basic heat architecture, the load balancing mechanism
used and the target scaled out architecture.

Basic Architecture
------------------

The heat architecture is as defined at :doc:`heat architecture
<../developing_guides/architecture>` and shown in the diagram below,
where we have a CLI that sends HTTP requests to the REST and CFN APIs, which in
turn make calls using AMQP to the heat-engine::

                   |- [REST API] -|
 [CLI] -- <HTTP> --                -- <AMQP> -- [ENGINE]
                   |- [CFN API]  -|

Load Balancing
--------------

As there is a need to use a load balancer mechanism between the multiple APIs
and the CLI, a proxy has to be deployed.

Because the heat CLI and APIs communicate by exchanging HTTP requests and
responses, a HAProxy_ HTTP load balancer server will
be deployed between them.

This way, the proxy will take the CLIs requests to the APIs and act on their
behalf. Once the proxy receives a response, it will be redirected to the caller
CLI.

A round-robin distribution of messages from the AMQP queue will act as the load
balancer for multiple engines. Check that your AMQP service is configured to
distribute messages round-robin (RabbitMQ does this by default).

Target Architecture
-------------------

A scaled out heat architecture is represented in the diagram below:
::

                              |- [REST-API] -|
                              |-    ...     -|
                              |- [REST-API] -|             |- [ENGINE] -|
 [CLI] -- <HTTP> -- [PROXY] --                -- <AMQP> -- |-    ...   -|
                              |- [API-CFN]  -|             |- [ENGINE] -|
                              |-    ...     -|
                              |- [API-CFN]  -|


Thus, a request sent from the CLI looks like:

    1. CLI contacts the proxy;
    2. The HAProxy server, acting as a load balancer, redirects the call to an
       API instance;
    3. The API server sends messages to the AMQP queue, and the engines pick up
       messages in round-robin fashion.

Deploying Multiple APIs
=======================

In order to run a heat component separately, you have to execute one of the
python scripts located at the *bin* directory of your heat repository.

These scripts take as argument a configuration file. When using devstack, the
configuration file is located at */etc/heat/heat.conf*. For instance, to start
new REST and CFN API services, you must run:
::

    python bin/heat-api --config-file=/etc/heat/heat.conf
    python bin/heat-api-cfn --config-file=/etc/heat/heat.conf

Each API service must have a unique address to listen. This address have to be
defined in the configuration file. For REST and CFN APIs, modify the
*[heat_api]* and *[heat_api_cfn]* blocks, respectively.
::

    [heat_api]
    bind_port = {API_PORT}
    bind_host = {API_HOST}

    ...

    [heat_api_cfn]
    bind_port = {API_CFN_PORT}
    bind_host = {API_CFN_HOST}

If you wish to run multiple API processes on the same machine, you must create
multiple copies of the heat.conf file, each containing a unique port number.

In addition, if you want to run some API services in different machines than
the devstack server, you have to update the loopback addresses found at the
*sql_connection* and *rabbit_host* properties to the devstack server's IP,
which must be reachable from the remote machine.

Deploying Multiple Engines
==========================

All engines must be configured to use the same AMQP service.  Ensure that all of
the *rabbit_*\* and *kombu_*\* configuration options in the *[DEFAULT]* section
of */etc/heat/heat.conf* match across each machine that will be running an
engine.  By using the same AMQP configuration, each engine will subscribe to the
same AMQP *engine* queue and pick up work in round-robin fashion with the other
engines.

One or more engines can be deployed per host.  Depending on the host's CPU
architecture, it may be beneficial to deploy several engines on a single
machine.

To start multiple engines on the same machine, simply start multiple
*heat-engine* processes:
::

    python bin/heat-engine --config-file=/etc/heat/heat.conf &
    python bin/heat-engine --config-file=/etc/heat/heat.conf &

Deploying the Proxy
===================

In order to simplify the deployment of the HAProxy server, we will replace
the REST and CFN APIs deployed when installing devstack by the HAProxy server.
This way, there is no need to update, on the CLI, the addresses where it should
look for the APIs. In this case, when it makes a call to any API, it will find
the proxy, acting on their behalf.

Note that the addresses that the HAProxy will be listening to are the pairs
*API_HOST:API-PORT* and *API_CFN_HOST:API_CFN_PORT*, found at the *[heat_api]*
and *[heat_api_cfn]* blocks on the devstack server's configuration file. In
addition, the original *heat-api* and *heat-api-cfn* processes running in these
ports have to be killed, because these addresses must be free to be used by the
proxy.

To deploy the HAProxy server on the devstack server, run
*haproxy -f apis-proxy.conf*, where this configuration file looks like:
::

    global
        daemon
        maxconn 4000

    defaults
        log  global
        maxconn  8000
        option  redispatch
        retries  3
        timeout  http-request 10s
        timeout  queue 1m
        timeout  connect 10s
        timeout  client 1m
        timeout  server 1m
        timeout  check 10s

    listen rest_api_proxy
        # The values required below are the original ones that were in
        # /etc/heat/heat.conf on the devstack server.
        bind {API_HOST}:{API_PORT}
        balance  source
        option  tcpka
        option  httpchk
        # The values required below are the different addresses supplied when
        # running the REST API instances.
        server SERVER_1 {HOST_1}:{PORT_1}
        ...
        server SERVER_N {HOST_N}:{PORT_N}

    listen cfn_api_proxy
        # The values required below are the original ones that were in
        # /etc/heat/heat.conf on the devstack server.
        bind {API_CFN_HOST}:{API_CFN_PORT}
        balance  source
        option  tcpka
        option  httpchk
        # The values required below are the different addresses supplied when
        # running the CFN API instances.
        server SERVER_1 {HOST_1}:{PORT_1}
        ...
        server SERVER_N {HOST_N}:{PORT_N}

Sample
======

This section aims to clarify some aspects of the scaling out solution, as well
as to show more details of the configuration by describing a concrete sample.

Architecture
------------

This section shows a basic OpenStack architecture and the target one
that will be used for testing of the scaled-out heat services.

Basic Architecture
^^^^^^^^^^^^^^^^^^

For this sample, consider that:

    1. We have an architecture composed by 3 machines configured in a LAN, with
       the addresses A: 10.0.0.1; B: 10.0.0.2; and C: 10.0.0.3;
    2. The OpenStack devstack installation, including the heat module, has been
       done in the machine A, as shown in the
       :ref:`scale_deployment_assumptions` section.

Target Architecture
^^^^^^^^^^^^^^^^^^^

At this moment, everything is running in a single devstack server. The next
subsections show how to deploy a scaling out heat architecture by:

    1. Running one REST and one CFN API on the machines B and C;
    2. Setting up the HAProxy server on the machine A.

Running the API and Engine Services
-----------------------------------

For each machine, B and C, you must do the following steps:

    1. Clone the heat repository https://git.openstack.org/cgit/openstack/heat, run:

    ::
        git clone https://git.openstack.org/openstack/heat

    2. Create a local copy of the configuration file */etc/heat/heat.conf* from
       the machine A;
    3. Make required changes on the configuration file;
    4. Enter the heat local repository and run:

    ::

        python bin/heat-api --config-file=/etc/heat/heat.conf
        python bin/heat-api-cfn --config-file=/etc/heat/heat.conf

    5. Start as many *heat-engine* processes as you want running on that
       machine:

    ::

        python bin/heat-engine --config-file=/etc/heat/heat.conf &
        python bin/heat-engine --config-file=/etc/heat/heat.conf &
        ...

Changes On Configuration
^^^^^^^^^^^^^^^^^^^^^^^^

The original file from A looks like:
::

    [DEFAULT]
    ...
    sql_connection = mysql+pymysql://root:admin@127.0.0.1/heat?charset=utf8
    rabbit_host = localhost
    ...
    [heat_api]
    bind_port = 8004
    bind_host = 10.0.0.1
    ...
    [heat_api_cfn]
    bind_port = 8000
    bind_host = 10.0.0.1

After the changes for B, it looks like:
::

    [DEFAULT]
    ...
    sql_connection = mysql+pymysql://root:admin@10.0.0.1/heat?charset=utf8
    rabbit_host = 10.0.0.1
    ...
    [heat_api]
    bind_port = 8004
    bind_host = 10.0.0.2
    ...
    [heat_api_cfn]
    bind_port = 8000
    bind_host = 10.0.0.2

Setting Up HAProxy
------------------

On the machine A, kill the *heat-api* and *heat-api-cfn* processes by running
*pkill heat-api* and *pkill heat-api-cfn*. After, run
*haproxy -f apis-proxy.conf* with the following configuration:
::

     global
        daemon
        maxconn 4000

    defaults
        log  global
        maxconn  8000
        option  redispatch
        retries  3
        timeout  http-request 10s
        timeout  queue 1m
        timeout  connect 10s
        timeout  client 1m
        timeout  server 1m
        timeout  check 10s

    listen rest_api_proxy
        bind 10.0.0.1:8004
        balance  source
        option  tcpka
        option  httpchk
        server rest-server-1 10.0.0.2:8004
        server rest-server-2 10.0.0.3:8004

    listen cfn_api_proxy
        bind 10.0.0.1:8000
        balance  source
        option  tcpka
        option  httpchk
        server cfn-server-1 10.0.0.2:8000
        server cfn-server-2 10.0.0.3:8000

.. _HAProxy: https://www.haproxy.org/
