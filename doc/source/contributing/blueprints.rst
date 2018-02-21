Blueprints and Specs
====================

The Heat team uses the `heat-specs
<http://git.openstack.org/cgit/openstack/heat-specs>`_ repository for its
specification reviews. Detailed information can be found `here
<https://wiki.openstack.org/wiki/Blueprints#Heat>`_.

Please note that we use a template for spec submissions. Please use the
`template for the latest release
<http://git.openstack.org/cgit/openstack/heat-specs/tree/specs/templates>`_.
It is not required to fill out all sections in the template.

Spec Notes
----------

There are occasions when a spec is approved and the code does not land in
the cycle it was targeted for. For these cases, the workflow to get the spec
into the next release is as below:

* Anyone can propose a patch to heat-specs which moves a spec from the
  previous release backlog into the new release directory.

The specs which are moved in this way can be fast-tracked into the next
release. Please note that it is required to re-propose the spec for the new
release and it'll be evaluated based on the resources available and cycle
priorities.

Heat Spec Lite
--------------

Lite specs are small feature requests tracked as Launchpad bugs, with status
'Wishlist' and tagged with 'spec-lite' tag. These allow for submission and
review of these feature requests before code is submitted.

These can be used for small features that don’t warrant a detailed spec to be
proposed, evaluated, and worked on. The team evaluates these requests as it
evaluates specs.

Once a `spec-lite` bug has been approved/triaged as a
Request for Enhancement(RFE), it’ll be targeted for a release.

The workflow for the life of a spec-lite in Launchpad is as follows:

* File a bug with a small summary of what the requested change is and
  tag it as `spec-lite`.
* The bug is triaged and importance changed to `Wishlist`.
* The bug is evaluated and marked as `Triaged` to announce approval or
  to `Won't fix` to announce rejection or `Invalid` to request a full
  spec.
* The bug is moved to `In Progress` once the code is up and ready to
  review.
* The bug is moved to `Fix Committed` once the patch lands.

In summary:

+--------------+-----------------------------------------------------------------------------+
|State         | Meaning                                                                     |
+==============+=============================================================================+
|New           | This is where spec-lite starts, as filed by the community.                  |
+--------------+-----------------------------------------------------------------------------+
|Triaged       | Drivers - Move to this state to mean, "you can start working on it"         |
+--------------+-----------------------------------------------------------------------------+
|Won't Fix     | Drivers - Move to this state to reject a lite-spec.                         |
+--------------+-----------------------------------------------------------------------------+
|Invalid       | Drivers - Move to this state to request a full spec for this request        |
+--------------+-----------------------------------------------------------------------------+

The drivers team will discuss the following bug reports in IRC meetings:

* `heat RFE's <https://bugs.launchpad.net/heat/+bugs?field.status%3Alist=NEW&field.tag=spec-lite>`_
* `python-heatclient RFE's <https://bugs.launchpad.net/python-heatclient/+bugs?field.status%3Alist=NEW&field.tag=spec-lite>`_


Lite spec Submission Guidelines
-------------------------------

When a bug is submitted, there are two fields that must be filled: ‘summary’
and ‘further information’. The ‘summary’ must be brief enough to fit in one
line.

The ‘further information’ section must be a description of what you would like
to see implemented in heat. The description should provide enough details for
a knowledgeable developer to understand what is the existing problem and
what’s the proposed solution.

Add `spec-lite` tag to the bug.


Lite spec from existing bugs
----------------------------

If there's an already existing bug that describes a small feature suitable for
a spec-lite, add a `spec-lite` tag to the bug. There is no need to create a new
bug. The comments and history of the existing bug are important for it's review.
