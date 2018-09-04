..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

.. _rally_gates:

=========================
Using Rally on Heat gates
=========================
Heat gate allows to use Rally for performance testing for each particular
patch. This functionality can be used for checking patch on performance
regressions and also for detecting any floating bugs for common scenarios.

How to run Rally for particular patch
-------------------------------------
As was mentioned above Heat allows to execute Rally scenarios as a gate job
for particular patch. It can be done by posting comment with text
``check experimental`` for patch on review. It will run bunch of jobs, one of
which has name ``gate-rally-dsvm-fakevirt-heat``.

List of scenarios, which will be executed, is presented in file
``heat-fakevirt.yaml``. Default version of this file is available here:
https://github.com/openstack/heat/blob/master/rally-scenarios/heat-fakevirt.yaml

Obviously performance analysis make sense, when it can be compared with some
another performance data. So two different approaches can be used for it:

- Comparison of one part of code with some custom changes
  (see :ref:`check_performance_or_detect_regression`)
- Comparison of two different code parts
  (see :ref:`compare_output_API_performance`)

Examples of using Rally
-----------------------

Previously two main approaches of using Rally job for Heat were highlighted.
Corresponding examples will be described in this part of documentation.

However need to note, that there are a lot of other ways how to use Rally job
for Heat performance. For example, this job can be launched periodically
(twice in week) for random patches and these results will be compared between
each other. It allows to see, that Heat has not any performance regressions.

.. _check_performance_or_detect_regression:

Check performance or how to detect regression
+++++++++++++++++++++++++++++++++++++++++++++

The easiest way of using Rally is to execute already existing scenarios.
One of the examples is presented in patch
https://review.openstack.org/#/c/279450/ . In this patch was executed scenario
already existing in Rally ``HeatStacks.create_and_delete_stack``.
During executing this scenario Rally creates and then, when stack is created,
delete Heat stack. All existing scenarios can be found here:
https://github.com/openstack/rally-openstack/blob/master/rally_openstack/scenarios/heat/stacks.py

Mentioned scenario uses Heat template as a parameter for task. The template
path should be mentioned for argument ``template_path``. It can be one of Heat
templates presented in Rally repository
(https://github.com/openstack/rally-openstack/tree/master/samples/tasks/scenarios/heat/templates)
or new one, like it was done for mentioned patch. New added template should be
placed in ``rally-scenarios/extra/`` directory.

Also it's possible to specify other fields for each Rally task, like ``sla``
or ``context``. More information about other configuration setting is
available by link https://rally.readthedocs.io/en/latest/plugins/#rally-plugins
Mentioned patch was proposed for confirmation caching mechanism of Heat
template validation process
(see https://specs.openstack.org/openstack/heat-specs/specs/liberty/constraint-validation-cache.html).
So it contains some changes in OS::Heat::TestResource resource, which allows
to demonstrate mentioned caching feature improvements.

Initially test was run against current devstack installation, where caching
is disabled (e.g. Patch Set 7). The follow results were gotten:

+------------------+----------+----------+----------+--------+------+
|Action            | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+------------------+----------+----------+----------+--------+------+
|heat.create_stack | 38.223   | 48.085   | 42.971   | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+
|heat.delete_stack | 11.755   | 18.155   | 14.085   | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+
|total             | 50.188   | 65.361   | 57.057   | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+

In the next patch set (Patch Set 8) was updated by adding Depends-On reference
to commit message. It let to execute the same test with patch for devstack,
which turns on caching (https://review.openstack.org/#/c/279400/).
The results for this case were:

+------------------+----------+----------+----------+--------+------+
|Action            | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+------------------+----------+----------+----------+--------+------+
|heat.create_stack | 11.863   | 16.074   | 14.174   | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+
|heat.delete_stack | 9.144    | 11.663   | 10.595   | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+
|total             | 21.557   | 27.18    | 24.77    | 100.0% | 10   |
+------------------+----------+----------+----------+--------+------+

Comparison average values for create_stack action in the first and the second
executions shows, that with enabled caching create_stack works faster in 3
times. It is a tangible improvement for create_stack operation.
Need to note, that in described test delay for each constraint validation
request takes 0.3 sec. as specified in ``constraint_prop_secs`` property of
TestResource. It may be more, than real time delay, but it allows to confirm,
that caching works correct.

Also this approach may be used for detecting regressions. In this case workflow
may be presented as follow list of steps:

- add to task list (``heat-fakevirt.yaml``) existing or new tasks.
- wait a result of this execution.
- upload patchset with changes (new feature) and launch the same test again.
- compare performance results.

.. _compare_output_API_performance:

Compare output API performance
++++++++++++++++++++++++++++++

Another example of using Rally job is writing custom Rally scenarios in Heat
repository. There is an example of this is presented on review:
https://review.openstack.org/#/c/270225/

It's similar on the first example, but requires more Rally specific coding.
New tasks in ``heat-fakevirt.yaml`` use undefined in Rally repository
scenarios:

- CustomHeatBenchmark.create_stack_and_show_output_new
- CustomHeatBenchmark.create_stack_and_show_output_old
- CustomHeatBenchmark.create_stack_and_list_output_new
- CustomHeatBenchmark.create_stack_and_list_output_old

All these scenarios are defined in the same patch and placed in
``rally-scenarios/plugins/`` directory.

The aim of these scenarios and tasks is to demonstrate differences between
new and old API calls. Heat client has a two commands for operating stack
outputs:  ``heat output-list`` and ``heat output-show <output-id>``.
Previously there are no special API calls for getting this information from
server and this data was obtained from whole Heat Stack object.
This was changed after implementation new API for outputs:
https://specs.openstack.org/openstack/heat-specs/specs/mitaka/api-calls-for-output.html

As described in the mentioned specification outputs can be obtained via special
requests to Heat API. According to this changes code in Heat client was updated
to use new API, if it's available.

The initial problem for this change was performance issue, which can be
formulated as: execution command ``heat output-show <output-id>`` with old
approach required resolving all outputs in Heat Stack, before getting only
one output specified by user.

The same issue was and with ``heat output-list``, which required to resolve all
outputs only for providing list of output keys without resolved values.

Two scenarios with suffix ``*_new`` use new output API. These scenarios
are not presented in Rally yet, because it's new API.
Another two scenarios with suffix ``*_old`` are based on the old approach of
getting outputs. This code was partially replaced by new API, so it's not
possible to use it on fresh devstack. As result this custom code was written
as two custom scenarios.

All these scenarios were added to task list and executed in the same time.
Results of execution are shown below:

create_stack_and_show_output_old
--------------------------------

+---------------------+----------+----------+----------+--------+------+
|Action               | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+---------------------+----------+----------+----------+--------+------+
|heat.create_stack    | 13.559   | 14.298   | 13.899   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.show_output_old | 5.214    | 5.297    | 5.252    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.delete_stack    | 5.445    | 6.962    | 6.008    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|total                | 24.243   | 26.146   | 25.159   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+

create_stack_and_show_output_new
--------------------------------

+---------------------+----------+----------+----------+--------+------+
|Action               | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+---------------------+----------+----------+----------+--------+------+
|heat.create_stack    | 13.719   | 14.286   | 13.935   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.show_output_new | 0.699    | 0.835    | 0.762    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.delete_stack    | 5.398    | 6.457    | 5.636    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|total                | 19.873   | 21.21    | 20.334   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+

Average value for execution ``output-show`` for old approach obviously more,
then for new API. It happens, because new API resolve only one specified
output.

Same results are for ``output-list``:

create_stack_and_list_output_old
--------------------------------

+---------------------+----------+----------+----------+--------+------+
|Action               | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+---------------------+----------+----------+----------+--------+------+
|heat.create_stack    | 13.861   | 14.573   | 14.141   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.list_output_old | 5.247    | 5.339    | 5.281    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.delete_stack    | 6.727    | 6.845    | 6.776    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|total                | 25.886   | 26.696   | 26.199   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+

create_stack_and_list_output_new
--------------------------------

+---------------------+----------+----------+----------+--------+------+
|Action               | Min (sec)| Max (sec)| Avg (sec)| Success| Count|
+---------------------+----------+----------+----------+--------+------+
|heat.create_stack    | 13.902   | 21.117   | 16.729   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.list_output_new | 0.147    | 0.363    | 0.213    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|heat.delete_stack    | 6.616    | 8.202    | 7.022    | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+
|total                | 20.838   | 27.908   | 23.964   | 100.0% | 5    |
+---------------------+----------+----------+----------+--------+------+

It's also expected, because for getting list of output names is not necessary
resolved values, how it is done in new API.

All mentioned results clearly show performance changes and allow to confirm,
that new approach works correctly.
