# heat.sh - Devstack extras script to install heat

# Save trace setting
XTRACE=$(set +o | grep xtrace)
set -o xtrace

echo_summary "heat's plugin.sh was called..."
source $DEST/heat/devstack/lib/heat
(set -o posix; set)

if is_heat_enabled; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing heat"
        # Use stack_install_service here to account for virtualenv
        stack_install_service heat
        echo_summary "Installing heatclient"
        install_heatclient

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        if is_service_enabled tempest; then
            setup_develop $TEMPEST_DIR
        fi

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Cleaning up heat"
        cleanup_heat
        echo_summary "Configuring heat"
        configure_heat
        create_heat_accounts

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        # Initialize heat
        init_heat

        # Start the heat API and heat taskmgr components
        echo_summary "Starting heat"
        start_heat

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        echo_summary "Configuring Tempest for Heat"
        configure_tempest_for_heat
    fi

    if [[ "$1" == "unstack" ]]; then
        stop_heat
    fi

    if [[ "$1" == "clean" ]]; then
        cleanup_heat
    fi
fi

# Restore xtrace
$XTRACE
