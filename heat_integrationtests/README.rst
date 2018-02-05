======================
Heat integration tests
======================

These tests can be run against any heat-enabled OpenStack cloud, however
defaults match running against a recent DevStack.

To run the tests against DevStack, do the following::

    export DEST=/opt/stack

    # create test resources and write config
    $DEST/heat/heat_integrationtests/prepare_test_env.sh
    $DEST/heat/heat_integrationtests/prepare_test_network.sh

    # run the heat integration tests
    cd $DEST/heat
    stestr --test-path=heat_integrationtests run

If the Heat Tempest Plugin is also installed, the tests from that will be run
as well.

If custom configuration is required, add it in the file
``heat_integrationtests/heat_integrationtests.conf``. A sample configuration is
available in ``heat_integrationtests/heat_integrationtests.conf.sample``
