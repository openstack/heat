.. _install-debian:

Install and configure for Debian
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to install and configure the Orchestration service
for Debian.

Install and configure components
--------------------------------


#. Run the following commands to install the packages:

   .. code-block:: console

      # apt-get install heat-api heat-api-cfn heat-engine python-heat-client

#. Respond to prompts for debconf.

   .. :doc:`database management <debconf/debconf-dbconfig-common>`,
      :doc:`Identity service credentials <debconf/debconf-keystone-authtoken>`,
      :doc:`service endpoint registration <debconf/debconf-api-endpoints>`,
      and :doc:`message broker credentials <debconf/debconf-rabbitmq>`.

#. Edit the ``/etc/heat/heat.conf`` file and complete the following
   actions:

   * In the ``[ec2authtoken]`` section, configure Identity service access:

     .. code-block:: none

        [ec2authtoken]
        ...
        auth_uri = http://controller:5000/v2.0

Finalize installation
---------------------

1. Restart the Orchestration services:

   .. code-block:: console

      # service heat-api restart
      # service heat-api-cfn restart
      # service heat-engine restart
