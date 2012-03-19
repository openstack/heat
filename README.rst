
====
HEAT
====

This is the beginings of a AWS Cloudformation API written
in the style of an openstack project.


Why heat? It makes the clouds raise and keeps them there.

Quick Start
-----------

If you'd like to run trunk, you can clone the git repo:

    git clone git@github.com:heat-api/heat.git


Install Heat by running::

    python setup.py build
    sudo python setup.py install

try:
shell1:

    heat-api

shell2:

    sudo heat-engine

shell3:

    heat create my_stack --template-url=https://github.com/heat-api/heat/blob/master/templates/WordPress_Single_Instance.template

References:
http://docs.amazonwebservices.com/AWSCloudFormation/latest/APIReference/API_CreateStack.html
http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/create-stack.html

