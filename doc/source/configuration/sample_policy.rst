==================
Heat Sample Policy
==================

.. warning::

   JSON formatted policy file is deprecated since Heat 17.0.0 (Xena).
   This `oslopolicy-convert-json-to-yaml`__ tool will migrate your existing
   JSON-formatted policy file to YAML in a backward-compatible way.

.. __: https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-convert-json-to-yaml.html

The following is a sample heat policy file that has been auto-generated
from default policy values in code. If you're using the default policies, then
the maintenance of this file is not necessary, and it should not be copied into
a deployment. Doing so will result in duplicate policy definitions. It is here
to help explain which policy operations protect specific heat APIs, but it
is not suggested to copy and paste into a deployment unless you're planning on
providing a different policy for an operation that is not the default.

If you wish build a policy file, you can also use ``tox -e genpolicy`` to
generate it.

The sample policy file can also be downloaded in `file form <../_static/heat.policy.yaml.sample>`_.

.. literalinclude:: ../_static/heat.policy.yaml.sample
