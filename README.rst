========================
Team and repository tags
========================

.. image:: http://governance.openstack.org/badges/heat.svg
    :target: http://governance.openstack.org/reference/tags/index.html

.. Change things from this point on

====
Heat
====

Heat is a service to orchestrate multiple composite cloud applications using
templates, through both an OpenStack-native REST API and a
CloudFormation-compatible Query API.

Why heat? It makes the clouds rise and keeps them there.

Getting Started
---------------

If you'd like to run from the master branch, you can clone the git repo:

    git clone https://git.openstack.org/openstack/heat


* Wiki: http://wiki.openstack.org/Heat
* Developer docs: http://docs.openstack.org/developer/heat
* Template samples: https://git.openstack.org/cgit/openstack/heat-templates
* Agents: https://git.openstack.org/cgit/openstack/heat-agents

Python client
-------------
https://git.openstack.org/cgit/openstack/python-heatclient

References
----------
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/create-stack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/aws-template-resource-type-ref.html
* http://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca

We have integration with
------------------------
* https://git.openstack.org/cgit/openstack/python-novaclient (instance)
* https://git.openstack.org/cgit/openstack/python-keystoneclient (auth)
* https://git.openstack.org/cgit/openstack/python-swiftclient (s3)
* https://git.openstack.org/cgit/openstack/python-neutronclient (networking)
* https://git.openstack.org/cgit/openstack/python-ceilometerclient (metering)
* https://git.openstack.org/cgit/openstack/python-aodhclient (alarming service)
* https://git.openstack.org/cgit/openstack/python-cinderclient (storage service)
* https://git.openstack.org/cgit/openstack/python-glanceclient (image service)
* https://git.openstack.org/cgit/openstack/python-troveclient (database as a Service)
* https://git.openstack.org/cgit/openstack/python-saharaclient (hadoop cluster)
* https://git.openstack.org/cgit/openstack/python-barbicanclient (key management service)
* https://git.openstack.org/cgit/openstack/python-designateclient (DNS service)
* https://git.openstack.org/cgit/openstack/python-magnumclient (container service)
* https://git.openstack.org/cgit/openstack/python-manilaclient (shared file system service)
* https://git.openstack.org/cgit/openstack/python-mistralclient (workflow service)
* https://git.openstack.org/cgit/openstack/python-zaqarclient (messaging service)
* https://git.openstack.org/cgit/openstack/python-monascaclient (monitoring service)
* https://git.openstack.org/cgit/openstack/python-senlinclient (clustering service)
