..
      Copyright 2011-2012 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

=================
Heat architecture
=================

Heat is a service to orchestrate multiple composite cloud applications using
the `AWS CloudFormation`_ template format, through both an OpenStack-native
REST API and a CloudFormation-compatible Query API.


Detailed description
~~~~~~~~~~~~~~~~~~~~

What is the purpose of the project and vision for it?

*Heat provides an AWS CloudFormation implementation for OpenStack that
orchestrates an AWS CloudFormation template describing a cloud application by
executing appropriate OpenStack API calls to generate running cloud
applications.*

Describe the relevance of the project to other OpenStack projects and the
OpenStack mission to provide a ubiquitous cloud computing platform:

*The software integrates other core components of OpenStack into a one-file
template system. The templates allow creation of most OpenStack resource types
(such as instances, floating IPs, volumes, security groups and users), as well
as some more advanced functionality such as instance high availability,
instance autoscaling, and nested stacks. By providing very tight integration
with other OpenStack core projects, all OpenStack core projects could receive
a larger user base.*

*Currently no other CloudFormation implementation exists for OpenStack. The
developers believe cloud developers have a strong desire to move workloads
from AWS to OpenStack deployments. Given the missing gap of a well-implemented
and integrated CloudFormation API in OpenStack, we provide a high quality
implementation of this gap improving the ubiquity of OpenStack.*


Heat services
~~~~~~~~~~~~~

The developers are focused on creating an OpenStack style project using
OpenStack design tenets, implemented in Python. We have started with full
integration with keystone. We have a number of components.

As the developers have only started development in March 2012, the
architecture is evolving rapidly.

heat
----

The heat tool is a CLI which communicates with the heat-api to execute AWS
CloudFormation APIs. End developers could also use the heat REST API directly.


heat-api
--------

The heat-api component provides an OpenStack-native REST API that processes
API requests by sending them to the heat-engine over RPC.


heat-api-cfn
------------

The heat-api-cfn component provides an AWS Query API that is compatible with
AWS CloudFormation and processes API requests by sending them to the
heat-engine over RPC.


heat-engine
-----------

The heat-engine's main responsibility is to orchestrate the launching of
templates and provide events back to the API consumer.

The templates integrate well with Puppet_ and Chef_.

.. _Puppet: https://s3.amazonaws.com/cloudformation-examples/IntegratingAWSCloudFormationWithPuppet.pdf
.. _Chef: https://www.full360.com/2011/02/27/integrating-aws-cloudformation-and-chef.html
.. _`AWS CloudFormation`: https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/Welcome.html?r=7078
