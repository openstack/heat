# heat.sh - Devstack extras script to install heat

# Save trace setting
XTRACE=$(set +o | grep xtrace)
set -o xtrace

echo_summary "heat's plugin.sh was called..."
source $DEST/heat/devstack/lib/heat
(set -o posix; set)

if is_service_enabled h-eng h-api h-api-cfn h-api-cw; then
    if [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing heat"
        install_heat
        echo_summary "Installing heatclient"
        install_heatclient
        echo_summary "Installing heat other"
        install_heat_other
        cleanup_heat
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configuring heat"
        configure_heat

        if is_service_enabled key; then
            create_heat_accounts
        fi

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        # Initialize heat
        init_heat

        # Start the heat API and heat taskmgr components
        echo_summary "Starting heat"
        start_heat
        if [ "$HEAT_BUILD_PIP_MIRROR" = "True" ]; then
        echo_summary "Building Heat pip mirror"
        build_heat_pip_mirror
        fi
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
