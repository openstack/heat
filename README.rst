====
HEAT
====

Heat is a service to orchestrate multiple composite cloud applications using
templates, through both an OpenStack-native ReST API and a
CloudFormation-compatible Query API.

Why heat? It makes the clouds rise and keeps them there.

Getting Started
---------------

If you'd like to run from the master branch, you can clone the git repo:

    git clone git@github.com:openstack/heat.git


* Wiki: http://wiki.openstack.org/Heat
* Developer docs: http://docs.openstack.org/developer/heat


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
