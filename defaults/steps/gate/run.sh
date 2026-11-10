#!/bin/sh
# The gate step: exit 0 passes (docs/spec/gate.md). SSTACK_HOME_DIR is the sstack install root
# (the clone holding bin/ and defaults/), SSTACK_RUN the run folder (docs/spec/workflow.md).
exec "$SSTACK_HOME_DIR"/bin/sstack-gate --run "$SSTACK_RUN"
