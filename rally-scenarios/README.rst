This directory contains rally benchmark scenarios to be run by OpenStack CI.

Structure:

* heat.yaml is rally task that will be run in gates

* plugins - directory where you can add rally plugins. So you don't need
  to merge benchmark in scenarios in rally to be able to run them in heat.

* extra - all files from this directory will be copied to gates, so you will
  be able to use absolute path in rally tasks. Files will be in ~/.rally/extra/*

* more about rally: https://wiki.openstack.org/wiki/Rally

* how to add rally-gates: https://wiki.openstack.org/wiki/Rally/RallyGates

* how to write plugins https://rally.readthedocs.io/en/latest/plugins/#rally-plugins
