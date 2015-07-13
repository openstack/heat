#!/usr/bin/env bash

testr init
testr run --parallel `cat py3-testlist`
