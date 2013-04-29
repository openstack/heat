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

Getting Started With Heat on Fedora
===================================

..
  This file is a ReStructuredText document, but can be converted to a script
  using the accompanying rst2script.sed script. Any blocks that are indented by
  4 spaces (including comment blocks) will appear in the script. To document
  code that should not appear in the script, use an indent of less than 4
  spaces. (Using a Quoted instead of Indented Literal block also works.)
  To include code in the script that should not appear in the output, make it
  a comment block.

..
    #!/bin/bash
    
    # Exit on error
    set -e

Get Heat
--------

Clone the heat repository_ from GitHub at ``git://github.com/openstack/heat.git``. Note that OpenStack must be installed before heat.
Optionally, one may wish to install Heat via RPM. Creation instructions are in the readme in the heat-rpms_ repository at ``git://github.com/heat-api/heat-rpms.git``.

.. _repository: https://github.com/openstack/heat
.. _heat-rpms: https://github.com/heat-api/heat-rpms

Install OpenStack
-----------------

Installing OpenStack on Fedora 17/18
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Note:
    - On Fedora 17 using the `Preview Repository`_ to install the OpenStack Folsom release is recommended
    - On Fedora 18 you can use the included OpenStack Folsom release or the Grizzly `Preview Repository`_

A script called "``openstack``" in the tools directory of the repository will install and start OpenStack for you on Fedora::

    ./tools/openstack install -y -r ${MYSQL_ROOT_PASSWORD}

If you use this method, you will need to manually create a guest network.  How this is done depends on your environment.  An example network create operation:

..
    SUBNET=10.0.0.0/24

::

    sudo nova-manage network create demonet ${SUBNET} 1 256 --bridge=demonetbr0

Where ``${SUBNET}`` is of the form ``10.0.0.0/24``. The network range here, must *not* be one used on your existing physical network. It should be a range dedicated for the network that OpenStack will configure. So if ``10.0.0.0/24`` clashes with your local network, pick another subnet.

Currently, the bridge is not created immediately upon running this command, but is actually added when Nova first requires it.

If you wish to set up OpenStack manually on Fedora, read `Getting Started With OpenStack On Fedora`_.

.. _Getting Started With OpenStack on Fedora: http://fedoraproject.org/wiki/Getting_started_with_OpenStack_on_Fedora_17
.. _Preview Repository: http://fedoraproject.org/wiki/OpenStack#Preview_repository

Download or alternatively generate a JEOS image
-----------------------------------------------
It is possible to either use an image-building tool to create an image or download a prebuilt image of a desired distribution.

Download a prebuilt image and copy to libvirt images location
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download a prebuilt image from ``http://fedorapeople.org/groups/heat/prebuilt-jeos-images/``.

Note: This example assumes F17-x86_64-cfntools qcow2 was downloaded.

::

  sudo cp Downloads/F17-x86_64-cfntools.qcow2 /var/lib/libvirt/images

Register with glance:

::

  glance image-create --name=F17-x86_64-cfntools --disk-format=qcow2 --container-format=bare < /var/lib/libvirt/images/F17-x86_64-cfntools.qcow2

Alternatively see JEOS image-building documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you wish to create your own JEOS image from scratch, there are a number of approaches which can be used.

One approach is using the Oz image-building tool, which is documented in the `jeos building documentation`_.

.. _jeos building documentation: http://docs.openstack.org/developer/heat/getting_started/jeos_building.html

Install and Configure Heat
~~~~~~~~~~~~~~~~~~~~~~~~~~

Install heat from source
------------------------

In the heat directory, run the install script::

    sudo ./install.sh

If running OpenStack grizzly installed via tools/openstack, it is necessary to modify the default service user password::

    sudo sed -i "s/verybadpass/secrete/" /etc/heat/heat-api-cfn.conf
    sudo sed -i "s/verybadpass/secrete/" /etc/heat/heat-api-cloudwatch.conf
    sudo sed -i "s/verybadpass/secrete/" /etc/heat/heat-api.conf

Source the keystone credentials created with tools/openstack
------------------------------------------------------------

::

    source ~/.openstack/keystonerc

Note: these credentials will be required for all future steps.

Allocate Floating IP Addresses to OpenStack
-------------------------------------------

If you want to use templates that depend on ``AWS::EC2::EIP`` or ``AWS::EC2::EIPAssociation`` (multi-instance stacks often do, single-instance less often but it's still possible), see the wiki page on `Configuring Floating IPs`_.

.. _Configuring Floating IPs: http://wiki.openstack.org/Heat/Configuring-Floating-IPs

Setup the MySQL database for Heat
---------------------------------

::

    heat-db-setup rpm -y -r ${MYSQL_ROOT_PASSWORD}

Note: the first argument is either ``rpm`` for RPM-based distros (such as Fedora) or ``deb`` for Debian-based distros (such as Ubuntu). To prompt for confirmation when e.g. installing MySQL Server, omit the ``-y`` option. Run ``heat-db-setup --help`` for detailed documentation.

Register heat with keystone
---------------------------

::

    sudo -E ./bin/heat-keystone-setup

Note: The ``-E`` option to ``sudo`` preserves the environment, specifically the keystone credentials, when ``heat-keystone-setup`` is run as root. This script needs to run as root in order to read the admin password.

Register a SSH key-pair with OpenStack Nova
-------------------------------------------

This is for Heat to associate with the virtual machines.

::

    nova keypair-add --pub_key ~/.ssh/id_rsa.pub ${USER}_key


Verify JEOS registration
~~~~~~~~~~~~~~~~~~~~~~~~

Check that there is a ``F17-x86_64-cfntools`` JEOS in glance:

..
    GLANCE_INDEX=$(cat <<EOF

::

    glance index

..
    EOF
    )
    $GLANCE_INDEX | grep -q "F17-x86_64-cfntools"

Update heat engine configuration file
-------------------------------------

The heat engine configuration file should be updated with the address of the bridge device (demonetbr0), however this device is not created by nova-network until the first instance is launched, so we assume that $BRIDGE_IP is 10.0.0.1 if $SUBNET is 10.0.0.0/24 as in the instructions above:

..
    BRIDGE_IP=`echo $SUBNET | awk -F'[./]' '{printf "%d.%d.%d.%d", $1, $2, $3, or($4, 1)}'`

::

    sudo sed -i -e "/heat_metadata_server_url/ s/127\.0\.0\.1/${BRIDGE_IP}/" /etc/heat/heat-engine.conf
    sudo sed -i -e "/heat_waitcondition_server_url/ s/127\.0\.0\.1/${BRIDGE_IP}/" /etc/heat/heat-engine.conf
    sudo sed -i -e "/heat_watch_server_url/ s/127\.0\.0\.1/${BRIDGE_IP}/" /etc/heat/heat-engine.conf

Launch the Heat services
------------------------

::

    sudo -E bash -c 'heat-api-cfn & heat-engine &'

..
    sleep 5

Launch a Wordpress instance
---------------------------

::

    heat-cfn create wordpress --template-file=templates/WordPress_Single_Instance.template --parameters="InstanceType=m1.xlarge;DBUsername=${USER};DBPassword=verybadpass;KeyName=${USER}_key"

List stacks
-----------

::

    heat-cfn list

List stack events
-----------------

::

    heat-cfn event-list wordpress

Describe the ``wordpress`` stack
--------------------------------

..
    HEAT_DESCRIBE=$(cat <<EOF

::

    heat-cfn describe wordpress

..
    EOF
    )

After a few seconds, the ``StackStatus`` should change from ``CREATE_IN_PROGRESS`` to ``CREATE_COMPLETE``.

..
    # Wait for Stack creation
    CREATING="<StackStatus>CREATE_IN_PROGRESS</StackStatus>"
    retries=24
    while $HEAT_DESCRIBE | grep -q $CREATING && ((retries-- > 0))
    do
        echo "Waiting for Stack creation to complete..." >&2
        sleep 5
    done
    
    $HEAT_DESCRIBE | grep -q "<StackStatus>CREATE_COMPLETE</StackStatus>"


Verify instance creation
------------------------

Because the software takes some time to install from the repository, it may be a few minutes before the Wordpress intance is in a running state.  One way to check is to login via ssh and ``tail -f /var/log/yum.log``.  Once ``mysql-server`` installs, the instance should be ready to go.

..
    WebsiteURL=$($HEAT_DESCRIBE | sed                             \
        -e '/<OutputKey>WebsiteURL<\/OutputKey>/,/<\/member>/ {'  \
        -e '/<OutputValue>/ {'                                    \
        -e 's/<OutputValue>\([^<]*\)<\/OutputValue>/\1/'          \
        -e p                                                      \
        -e '}' -e '}'                                             \
        -e d                                                      \
    )
    HOST=`echo $WebsiteURL | sed -r -e 's#http://([^/]+)/.*#\1#'`
    
    retries=9
    while ! ping -q -c 1 $HOST >/dev/null && ((retries-- > 0)); do
        echo "Waiting for host networking..." >&2
        sleep 2
    done
    test $retries -ge 0
    
    sleep 10
    
    retries=49
    while ! ssh -o PasswordAuthentication=no -o StrictHostKeyChecking=no  \
                -q -t -l ec2-user $HOST                                   \
                sudo grep -q mysql-server /var/log/yum.log &&             \
          ((retries-- > 0))
    do
        echo "Waiting for package installation..." >&2
        sleep 5
    done
    test $retries -ge 0
    
    echo "Pausing to wait for application startup..." >&2
    sleep 60

Point a web browser at the location given by the ``WebsiteURL`` Output as shown by ``heat-cfn describe``::

    wget ${WebsiteURL}

Delete the instance when done
-----------------------------

::

    heat-cfn delete wordpress
    heat-cfn list

Note: This operation will show no running stack.

Other Templates
---------------
Check out the ``Wordpress_2_Instances_with_EBS_EIP.template``.  This uses a few different APIs in OpenStack nova, such as the Volume API, the Floating IP API and the Security Groups API, as well as the general nova launching and monitoring APIs.

IPtables rules
--------------

Some templates require the instances to be able to connect to the heat CFN API (for metadata update via cfn-hup and waitcondition notification via cfn-signal):

Open up port 8000 so that the guests can communicate with the heat-api-cfn server::

    sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT -i demonetbr0

Open up port 8003 so that the guests can communicate with the heat-api-cloudwatch server::

    sudo iptables -I INPUT -p tcp --dport 8003 -j ACCEPT -i demonetbr0

Note the above rules will not persist across reboot, so you may wish to add them to /etc/sysconfig/iptables

Start the Heat Cloudwatch server
--------------------------------

If you wish to try any of the HA or autoscaling templates (which collect stats from instances via the CloudWatch API), it is neccessary to start the heat-api-cloudwatch server::

    sudo -E bash -c 'heat-api-cloudwatch &'

Further information on using the heat cloudwatch features is available in the Using-Cloudwatch_ wiki page

.. _Using-Cloudwatch: http://wiki.openstack.org/Heat/Using-CloudWatch

Using the OpenStack Heat API
----------------------------

CloudFormation (heat-api-cfn) and a native OpenStack Heat API (heat-api) are provided.  To use the recommended Heat API, a python client library is necessary.  To use this library, clone the python-heatclient repository_ from GitHub at ``git://github.com/openstack/python-heatclient.git``.

Install python-heatclient from source
-------------------------------------

In the python-heatclient directory, run the install script::

    sudo ./setup.py install

Note that python-heatclient may be installed on a different server than heat itself.
Note that pip can be used to install python-heatclient, but the instructions vary for each distribution.  Read your distribution documentation if you wish to install with pip.

Start the OpenStack specific Heat API
-------------------------------------

When using heat-pythonclient, the OpenStack API service provided by heat must be started::

    sudo bash -c 'heat-api &'

List stacks
-----------

::

    heat stack-list

..
    echo; echo 'Success!'
