======================
Heat integration tests
======================

These tests can be run against any heat-enabled OpenStack cloud, however
defaults match running against a recent DevStack.

To run the tests against DevStack, do the following:

    # source DevStack credentials

    source /opt/stack/devstack/accrc/demo/demo

    # run the heat integration tests with those credentials

    cd /opt/stack/heat

    tox -eintegration

If custom configuration is required, copy the following file:

    heat_integrationtests/heat_integrationtests.conf.sample

to:

    heat_integrationtests/heat_integrationtests.conf

and make any required configuration changes before running:

    tox -eintegration
