MAX_SNIPPET_LENGTH = 200  # default length, adjustable in settings

def platform_to_raingull(raw_message):
    # ... existing translation logic ...
    standardized_message = {
        "raingull_id": raw_message["raingull_id"],
        "sender": raw_message["sender"],
        "subject": raw_message["subject"],
        "body": raw_message["body"],
        "attachments": raw_message.get("attachments", []),
        "original_service": raw_message["service"],
        "received_timestamp": raw_message["timestamp"],
    }
    # Generate snippet clearly
    body = standardized_message["body"]
    standardized_message["snippet"] = (
        body[:MAX_SNIPPET_LENGTH] + "..." if len(body) > MAX_SNIPPET_LENGTH else body
    )

    return standardized_message

def raingull_to_platform(standardized_message, use_snippet=False):
    if use_snippet:
        message_text = standardized_message["snippet"]
    else:
        message_text = standardized_message["body"]

    platform_message = {
        "message_text": message_text,
        # Additional fields clearly here...
    }
    return platform_message
