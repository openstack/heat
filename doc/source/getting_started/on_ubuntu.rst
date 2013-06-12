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

Getting Started With Heat on Ubuntu
===================================

This guide will help to get the current git master of Heat to run on Ubuntu. It makes the following assumptions:

- The host is running Ubuntu 12.04 or 12.10
- There is a working OpenStack installation based on Folsom, Grizzly or Havana, or that one will be installed via the tools/openstack_ubuntu script described below
- Heat will be installed on the controller host of the existing OpenStack installation (or if doing a single-host evaluation, on the same host as all other OpenStack services)

Get Heat
--------

Clone the heat repository_ from GitHub at ``git://github.com/openstack/heat.git``. Note that OpenStack must be installed before heat.

.. _repository: https://github.com/openstack/heat

Install OpenStack
-----------------

Note, this section may be skipped if you already have a working OpenStack installation

Installing OpenStack on Ubuntu 12.04/12.10
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A script called openstack_ubuntu in the tools directory of the Heat repository will install and start OpenStack for you on Ubuntu:
''Note currently only tested on 12.04, if it works for you on 12.10, please let us know''
::

    ./tools/openstack_ubuntu install -r ${MYSQL_ROOT_PASSWORD}

If you use this method, you will need to manually create a guest network.  How this is done depends on your environment.  An example network create operation:

..
    SUBNET=10.0.0.0/24

::

    sudo nova-manage network create --label=demonet --fixed_range_v4=${SUBNET} --bridge=demonetbr0 --bridge_interface=eth0

Where ''${SUBNET}'' is of the form ''10.0.0.0/24''. The network range here, must *not* be one used on your existing physical network. It should be a range dedicated for the network that OpenStack will configure. So if ''10.0.0.0/24'' clashes with your local network, pick another subnet.

The example above assumes you want to bridge with physical device ''eth0''

Currently, the bridge is not created immediately upon running this command, but is actually added when Nova first requires it.

Load keystone authentication into your environment and verify everything is ok.
-------------------------------------------------------------------------------

::

    . ~/.openstack/keystonerc
    keystone user-list
    glance index
    nova list

Note ''~/.openstack/keystonerc'' is created by tools/openstack_ubuntu, replace this step with your own credentials file for an admin user if OpenStack was installed by some other method

Install prerequisites
---------------------

::

    sudo apt-get install python-pip gcc python2.7-dev
    sudo apt-get install git
    sudo apt-get install build-essential devscripts debhelper python-all gdebi-core
    sudo apt-get install python-setuptools python-prettytable python-lxml
    sudo apt-get install libguestfs*

Install python-heatclient (optional)
------------------------------------
*NOTE* If running 12.04 LTS with the packaged Openstack Essex release, do not install python-heatclient, as it will break your OpenStack installation, because it explicitly requires a version of the prettytable library (>0.6) which causes problems with the Essex cli tools (keystone/nova/glance) in 12.04 : https://bugs.launchpad.net/keystone/+bug/995976  The packaged python-prettytable (0.5 version) works OK

::

    sudo pip install python-heatclient

Install Heat from master
------------------------

::

    git clone git://github.com/openstack/heat.git
    cd heat
    sudo ./install.sh

Modify configuration for admin password
---------------------------------------
Later a keystone user called '''heat''' will be created. At this point a password for that user needs to be chosen.
The following files will need editing:

- /etc/heat/heat-api-cfn.conf
- /etc/heat/heat-api-cloudwatch.conf
- /etc/heat/heat-api.conf

::

    [keystone_authtoken]
    admin_password=<heat admin password>


Create the MySQL Heat database:
-------------------------------
::

    sudo heat-db-setup deb -r <mysql password>

Create the keystone authentication parameters
---------------------------------------------
::

    sudo -E ./bin/heat-keystone-setup

Download or alternatively generate a JEOS image
------------------------------------------------

It is possible to either use an image-building tool to create an image or download a prebuilt image of a desired distribution.

Download a prebuilt image and copy to libvirt images location
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download a prebuilt image from ``http://fedorapeople.org/groups/heat/prebuilt-jeos-images/``.

Note: This example assumes U10-x86_64-cfntools qcow2 was downloaded.

::

  sudo cp Downloads/U10-x86_64-cfntools.qcow2 /var/lib/libvirt/images

Register with glance:

::

  glance image-create --name=U10-x86_64-cfntools --disk-format=qcow2 --container-format=bare < /var/lib/libvirt/images/U10-x86_64-cfntools.qcow2

Alternatively see JEOS image-building documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you wish to create your own JEOS image from scratch, there are a number of approaches which can be used.

One approach is using the Oz image-building tool, which is documented in the `jeos building documentation`_.

.. _jeos building documentation: http://docs.openstack.org/developer/heat/getting_started/jeos_building.html

Configure your host to work with Heat
-------------------------------------

Create SSH key and add it to the Nova sshkey list
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    ssh-keygen -t rsa
    nova keypair-add --pub_key ~/.ssh/id_rsa.pub ${USER}_key

Note: If running in a VM, modify /etc/libvirt/qemu/networks/default.xml:
change network to not conflict with host (default 192.168.122.x)
::

    sudo service libvirt-bin restart

If dnsmasq is not running on the default network
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    sudo virsh net-destroy default
    sudo virsh net-start default

Experiment with Heat
--------------------

Execute the heat api services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    sudo heat-engine &
    sudo heat-api &
    sudo heat-api-cfn &
    sudo heat-api-cloudwatch &

Run the debian wordpress example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    heat stack-create wordpress --template-url=https://raw.github.com/openstack/heat-templates/master/cfn/WordPress_Single_Instance_deb.template --parameters="InstanceType=m1.xlarge;DBUsername=${USER};DBPassword=verybadpassword;KeyName=${USER}_key;LinuxDistribution=U10"

List stacks
~~~~~~~~~~~
::

    heat stack-list

List stack events
~~~~~~~~~~~~~~~~~
::

    heat event-list wordpress

Describe the wordpress stack
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    heat stack-show wordpress

Note: After a few seconds, the Status should change from IN_PROGRESS to CREATE_COMPLETE.

Verify instance creation
~~~~~~~~~~~~~~~~~~~~~~~~
Because the software takes some time to install from the repository, it may be a few minutes before the Wordpress intance is in a running state.

Point a web browser at the location given by the WebsiteURL Output as shown by heat show-stack wordpress::
::

    wget ${WebsiteURL}

Delete the instance when done
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    heat stack-delete wordpress
    heat stack-list

Note: This operation will show no running stack.
