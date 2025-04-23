# Lock timeouts for message processing steps (in seconds)
LOCK_TIMEOUTS = {
    'poll': 300,  # Step 1: Polling incoming services
    'process': 60,  # Step 2: Processing incoming messages
    'format': 60,  # Step 3: Formatting outgoing messages
    'queue': 60,  # Step 4: Queueing messages
    'send': 60,  # Step 5: Sending messages
}

# Retry settings
MAX_MESSAGE_RETRIES = 3
MIN_RETRY_DELAY = 5  # minutes
MAX_RETRY_DELAY = 60  # minutes 