====
HEAT
====

This is an OpenStack style project that provides a REST API to orchestrate
multiple cloud applications implementing well-known standards such as AWS
CloudFormation and TOSCA.

Currently the developers are focusing on AWS CloudFormations but are watching
the development of the TOSCA specification.

Why heat? It makes the clouds rise and keeps them there.

Getting Started
-----------

If you'd like to run from the master branch, you can clone the git repo:

    git clone git@github.com:heat-api/heat.git

Follow the steps:
https://github.com/heat-api/heat/wiki/HeatGettingStarted

References
----------
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/create-stack.html
* http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/aws-template-resource-type-ref.html
* http://www.oasis-open.org/committees/tc_home.php?wg_abbrev=tosca

Related projects
----------------
* http://wiki.openstack.org/Donabe
* http://wiki.openstack.org/DatabaseAsAService (could be used to provide AWS::RDS::DBInstance)
* http://wiki.openstack.org/QueueService (could be used to provide AWS::SQS::Queue)

