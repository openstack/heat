=============
Building Heat
=============

There are several ways to build the heat project.  When developing, it's probably easiest to use 'python setup.py install' to build and install the python egg. 

Fedora 16 and 17 users:
There is also a Makefile and a heat.spec file to build rpm packages. You have a couple of options with building the rpms as well.  The first is to build your own rpms locally using 'make rpm'.  Using make directly to build rpms will not update the changelog or version of the rpms, that's fine when you're not doing a release.  When doing a release of the project, you would use tito https://github.com/dgoodwin/tito .  If you haven't use tito before, here are some quick steps to get set up and use it for a release:

1. yum install tito

Scenario:
- Test the rpm building but don't modify the git repo
  tito build --test --rpm

- Tag the branch and increment the version for a release and build a release rpm
  tito tag
  tito build --rpm

- Tag the branch and keep the version for a release and build a release rpm
  tito tag --keep-verion
  tito build --rpm

- Tag the branch, keep the version, and don't auto update the spec file changelog
  tito tag --keep-version
  tito build --rpm --no-auto-changelog


For more tips on using tito, check out the man page or the project readme on github.
