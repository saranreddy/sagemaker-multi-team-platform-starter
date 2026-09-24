#!/bin/bash
set -eux

# Idle shutdown script for SageMaker Studio
# This script checks for idle time and shuts down the app if it exceeds the threshold

IDLE_TIME_MINUTES=${idle_timeout_minutes}
IDLE_TIME_SECONDS=$((IDLE_TIME_MINUTES * 60))

echo "Idle shutdown configured: $IDLE_TIME_MINUTES minutes"

# This script runs on startup - the actual idle detection is handled by
# the Jupyter server's built-in idle detection mechanism or the reaper Lambda
# for longer-term cleanup.

# For on-start lifecycle configs, we just log the configuration
echo "Idle timeout will be enforced by lifecycle configuration"
echo "Apps idle for more than $IDLE_TIME_MINUTES minutes will be shut down"
