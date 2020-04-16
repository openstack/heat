========================
Team and repository tags
========================

.. image:: https://governance.openstack.org/tc/badges/heat.svg
    :target: https://governance.openstack.org/tc/reference/tags/index.html

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

    git clone https://opendev.org/openstack/heat


* Documentation: https://docs.openstack.org/heat/latest
* Template samples: https://opendev.org/openstack/heat-templates
* Agents: https://opendev.org/openstack/heat-agents
* Release Notes: https://docs.openstack.org/releasenotes/heat/

Python client
-------------

* Documentation: https://docs.openstack.org/python-heatclient/latest
* Source: https://opendev.org/openstack/python-heatclient

Report a Story (a bug/blueprint)
--------------------------------

If you'd like to report a Story (we used to call a bug/blueprint), you can
report it under Report a story in
`Heat's StoryBoard <https://storyboard.openstack.org/#!/project/989>`_.
If you must report the story under other sub-project of heat, you can find
them all in `Heat StoryBoard Group <https://storyboard.openstack.org/#!/project_group/82>`_.
if you encounter any issue.

References
----------
* https://docs.amazonwebservices.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html
* https://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/create-stack.html
* https://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/aws-template-resource-type-ref.html
* https://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca

We have integration with
------------------------
* https://opendev.org/openstack/python-novaclient (instance)
* https://opendev.org/openstack/python-keystoneclient (auth)
* https://opendev.org/openstack/python-swiftclient (object storage)
* https://opendev.org/openstack/python-neutronclient (networking)
* https://opendev.org/openstack/python-aodhclient (alarming service)
* https://opendev.org/openstack/python-cinderclient (block storage)
* https://opendev.org/openstack/python-glanceclient (image service)
* https://opendev.org/openstack/python-troveclient (database as a Service)
* https://opendev.org/openstack/python-saharaclient (hadoop cluster)
* https://opendev.org/openstack/python-barbicanclient (key management service)
* https://opendev.org/openstack/python-designateclient (DNS service)
* https://opendev.org/openstack/python-magnumclient (container service)
* https://opendev.org/openstack/python-manilaclient (shared file system service)
* https://opendev.org/openstack/python-mistralclient (workflow service)
* https://opendev.org/openstack/python-zaqarclient (messaging service)
* https://opendev.org/openstack/python-monascaclient (monitoring service)
* https://opendev.org/openstack/python-zunclient (container management service)
* https://opendev.org/openstack/python-blazarclient (reservation service)
* https://opendev.org/openstack/python-octaviaclient.git (Load-balancer service)
* https://opendev.org/openstack/python-senlinclient (Clustering service)
* https://opendev.org/openstack/python-vitrageclient.git (RCA service)
* https://opendev.org/openstack/python-ironicclient (baremetal provisioning service)
