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

    git clone git@github.com:openstack/heat.git


* Wiki: http://wiki.openstack.org/Heat
* Developer docs: http://docs.openstack.org/developer/heat
* Template samples: https://github.com/openstack/heat-templates

Python client
-------------
https://github.com/openstack/python-heatclient

References
----------
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/create-stack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/aws-template-resource-type-ref.html
* http://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca

We have integration with
------------------------
* https://github.com/openstack/python-novaclient (instance)
* https://github.com/openstack/python-keystoneclient (auth)
* https://github.com/openstack/python-swiftclient (s3)
* https://github.com/openstack/python-neutronclient (networking)
* https://github.com/openstack/python-ceilometerclient (metering)
* https://github.com/openstack/python-cinderclient (storage service)
* https://github.com/openstack/python-glanceclient (image service)
* https://github.com/openstack/python-troveclient (database as a Service)
* https://github.com/openstack/python-saharaclient (hadoop cluster)
* https://github.com/openstack/python-barbicanclient (key management service)
* https://github.com/openstack/python-designateclient (DNS service)
* https://github.com/openstack/python-magnumclient (container service)
* https://github.com/openstack/python-manilaclient (shared file system service)
* https://github.com/openstack/python-mistralclient (workflow service)
* https://github.com/openstack/python-zaqarclient (messaging service)
