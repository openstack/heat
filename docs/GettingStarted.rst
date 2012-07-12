Getting Started With Heat
=========================

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

Clone the heat repository_ from GitHub at ``git://github.com/heat-api/heat.git``. Note that OpenStack must be installed before heat.

.. _repository: https://github.com/heat-api/heat

Install OpenStack
-----------------

Installing OpenStack on Fedora 16 and 17
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Note: on Fedora 16 you have to enable the `Preview Repository`_ to install the required OpenStack Essex release.
A script called "``openstack``" in the tools directory of the repository will install and start OpenStack for you on Fedora 16/17::

    ./tools/openstack install -y -r ${MYSQL_ROOT_PASSWORD}

If you use this method, you will need to manually create a guest network.  How this is done depends on your environment.  An example network create operation:

..
    SUBNET=10.0.0.0/24

::

    sudo nova-manage network create demonet ${SUBNET} 1 256 --bridge=demonetbr0

Where ``${SUBNET}`` is of the form ``10.0.0.0/24``. The network range here, must *not* be one used on your existing physical network. It should be a range dedicated for the network that OpenStack will configure. So if ``10.0.0.0/24`` clashes with your local network, pick another subnet.

If you wish to set up OpenStack manually on Fedora, read `Getting Started With OpenStack On Fedora`_.

.. _Getting Started With OpenStack on Fedora: http://fedoraproject.org/wiki/Getting_started_with_OpenStack_on_Fedora_17
.. _Preview Repository: http://fedoraproject.org/wiki/OpenStack#Preview_repository

Installing OpenStack on other Distributions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* There is a `Debian packaging team for OpenStack`_.
* There are instructions for `installing OpenStack on Ubuntu`_.
* Various other distributions may have packaging teams or Getting Started guides available.

.. _Debian packaging team for OpenStack: http://wiki.openstack.org/Packaging/Debian
.. _installing OpenStack on Ubuntu: http://docs.openstack.org/bexar/openstack-compute/admin/content/ch03s02.html


Install OZ
----------

It is recommended to install the latest upstream oz, as this supports Fedora 17 (and Ubuntu U10/U12) guests::

    git clone https://github.com/clalancette/oz.git
    cd oz
    rm -f ~/rpmbuild/RPMS/noarch/oz-*
    make rpm
    sudo yum localinstall -y ~/rpmbuild/RPMS/noarch/oz-*
    cd -

Note: In the steps above, it's only necessary to be root for the yum localinstall, it's recommended not to be root while building the rpm.

If you do not require F17/U10/U12 support, oz can be installed directly via yum::

  yum install oz

Install heat from source
------------------------

In the heat directory, run the install script::

    sudo python setup.py install
    sudo install -d /etc/heat
    sudo install etc/*.conf etc/*.ini /etc/heat
    sudo install etc/bash_completion.d/heat /etc/bash_completion.d/heat
    sudo install -d /var/log/heat

Download Fedora 16 DVD and copy it to libvirt images location
-------------------------------------------------------------

::

  sudo cp Downloads/Fedora-16-x86_64-DVD.iso /var/lib/libvirt/images

Source the keystone credentials created with tools/openstack
------------------------------------------------------------

::

    source ~/.openstack/keystonerc

Note: these credentials will be required for all future steps.

Allocate Floating IP Addresses to OpenStack
-------------------------------------------

If you want to use templates that depend on ``AWS::EC2::EIP`` or ``AWS::EC2::EIPAssociation`` (multi-instance stacks often do, single-instance less often but it's still possible), see the wiki page on `Configuring Floating IPs`_.

.. _Configuring Floating IPs: https://github.com/heat-api/heat/wiki/Configuring-Floating-IPs

Setup the MySQL database for Heat
---------------------------------

::

    heat-db-setup rpm -y -r ${MYSQL_ROOT_PASSWORD}

Note: the first argument is either ``rpm`` for RPM-based distros (such as Fedora) or ``deb`` for Debian-based distros (such as Ubuntu). To prompt for confirmation when e.g. installing MySQL Server, omit the ``-y`` option. Run ``heat-db-setup --help`` for detailed documentation.

Register heat with keystone
---------------------------

::

    sudo -E ./tools/heat-keystone-service

Note: The ``-E`` option to ``sudo`` preserves the environment, specifically the keystone credentials, when ``heat-keystone-service`` is run as root. This script needs to run as root in order to read the admin password.

Register a SSH key-pair with OpenStack Nova
-------------------------------------------

This is for Heat to associate with the virtual machines.

::

    nova keypair-add --pub_key ~/.ssh/id_rsa.pub ${USER}_key


Download and install heat_jeos via git
--------------------------------------
Download heat_jeos via git

::

    git clone git://github.com/heat-api/heat-jeos.git
    cd heat-jeos
    sudo python setup.py install

Create a JEOS with heat_jeos tools
----------------------------------
::

    sudo -E heat-jeos -y create F16-x86_64-cfntools-jeos --register-with-glance

Note: The ``-E`` option to ``sudo`` preserves the environment, specifically the keystone credentials, when ``heat-jeos`` is run as root.

Note: ``heat-jeos`` must be run as root in order to create the cfntools disk image.

Note: If you want to enable debugging output from Oz, add '``-d``' (debugging) to the ``heat-jeos`` command.

You can run ``heat-jeos list`` to pick a different JEOS image.

Verify JEOS registration
~~~~~~~~~~~~~~~~~~~~~~~~

Check that there is a ``F16-x86_64-cfntools`` JEOS in glance:

..
    GLANCE_INDEX=$(cat <<EOF

::

    glance index

..
    EOF
    )
    $GLANCE_INDEX | grep -q "F16-x86_64-cfntools"

Launch the Heat services
------------------------

::

    sudo -E bash -c 'heat-api & heat-engine &'

..
    sleep 5

Launch a Wordpress instance
---------------------------

::

    heat -d create wordpress --template-file=templates/WordPress_Single_Instance.template --parameters="InstanceType=m1.xlarge;DBUsername=${USER};DBPassword=verybadpass;KeyName=${USER}_key"

List stacks
-----------

::

    heat list

List stack events
-----------------

::

    heat event-list wordpress

Describe the ``wordpress`` stack
--------------------------------

..
    HEAT_DESCRIBE=$(cat <<EOF

::

    heat describe wordpress

..
    EOF
    )

After a few seconds, the ``StackStatus`` should change from ``IN_PROGRESS`` to ``CREATE_COMPLETE``.

..
    # Wait for Stack creation
    CREATING='"StackStatus": "IN_PROGRESS"'
    retries=24
    while $HEAT_DESCRIBE | grep -q '"StackStatus": "IN_PROGRESS"' &&          \
          ((retries-- > 0))
    do
        echo "Waiting for Stack creation to complete..." >&2
        sleep 5
    done
    
    $HEAT_DESCRIBE | grep -q '"StackStatus": "CREATE_COMPLETE"'
    

Verify instance creation
------------------------

Because the software takes some time to install from the repository, it may be a few minutes before the Wordpress intance is in a running state.  One way to check is to login via ssh and ``tail -f /var/log/yum.log``.  Once ``mysql-server`` installs, the instance should be ready to go.

..
    WebsiteURL=$($HEAT_DESCRIBE | sed -e '/"OutputKey": "WebsiteURL"/,/}/ {'  \
                                      -e '/"OutputValue":/ {'                 \
                                      -e 's/[^:]*": "//'                      \
                                      -e 's/",\?[[:space:]]*$//'              \
                                      -e p -e '}' -e '}' -e d)
    HOST=`echo $WebsiteURL | sed -r -e 's#http://([^/]+)/.*#\1#'`
    
    retries=9
    while ! ping -q -c 1 $HOST && ((retries-- > 0)); do
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

Point a web browser at the location given by the ``WebsiteURL`` Output as shown by ``heat describe``::

    wget ${WebsiteURL}

Delete the instance when done
-----------------------------

::

    heat delete wordpress
    heat list

Note: This operation will show no running stack.

Other Templates
===============
Check out the ``Wordpress_2_Instances_with_EBS_EIP.template``.  This uses a few different APIs in OpenStack nova, such as the Volume API, the Floating IP API and the Security Groups API, as well as the general nova launching and monitoring APIs.

Troubleshooting
===============

If you encounter issues running heat, see if the solution to the issue is documented on the Troubleshooting_ wiki page. If not, let us know about the problem in the #heat IRC channel on freenode.

.. _Troubleshooting: https://github.com/heat-api/heat/wiki/Troubleshooting

..
    echo; echo 'Success!'
