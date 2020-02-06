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

These tests require both tempest and heat tempest plugin installed.
If custom configuration is required, it should be configured in the
heat tempest plugin configuration of the tempest config
(see heat tempest plugin and tempest docs for more info).
