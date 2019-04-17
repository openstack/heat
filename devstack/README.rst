=========================
Enabling heat in DevStack
=========================

1. Download DevStack::

     git clone https://opendev.org/openstack-dev/devstack
     cd devstack

2. Add this repo as an external repository into your ``local.conf`` file::

     [[local|localrc]]
     enable_plugin heat https://opendev.org/openstack/heat

3. Run ``stack.sh``.
