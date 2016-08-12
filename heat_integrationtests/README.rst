======================
Heat integration tests
======================

These tests can be run as a tempest plugin against any heat-enabled OpenStack
cloud, however defaults match running against a recent DevStack.

To run the tests against DevStack, do the following:

    # Define DEST
    
    export DEST=/opt/stack

    # create test resources and write tempest config

    $DEST/heat/heat_integrationtests/prepare_test_env.sh
    $DEST/heat/heat_integrationtests/prepare_test_network.sh

    # run tempest selecting only these tests

    cd $DEST/tempest
    tempest run --regex heat_integrationtests

If custom configuration is required, edit the [heat_plugin] section of

    $DEST/tempest/etc/tempest.conf
