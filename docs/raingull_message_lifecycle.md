RainGull Message Lifecycle

This document outlines the lifecycle of a message within RainGull, detailing each step from retrieval through processing, distribution, and eventual purging. It specifies responsibilities, data storage, and the flow of messages through various tables and systems.

📥 Incoming Message Process

Step 1: Message Retrieval (Plugin Responsibility)

Process:

Plugin connects to the external messaging platform (e.g., IMAP).

Retrieves new messages immediately and assigns each a unique RainGull ID (raingull_id, a UUID).

Database Table: Plugin-specific incoming table (e.g., imap_incoming_messages)

Field

Type

Description

raingull_id

UUID

Assigned at retrieval

raw_message

Text

Original, unmodified message data

received_timestamp

DateTime

Timestamp of retrieval

status

String

new, transitions to processed

Step 2: Message Standardization and Snippet Generation (Core Responsibility)

Process:

RainGull Core retrieves raw messages from plugin incoming tables.

Converts messages into a standardized RainGull message format.

Generates a snippet from the standardized message body.

Database Table: Core standardized message table (core_standard_messages)

Field

Type

Description

raingull_id

UUID

Matches UUID assigned by plugin

sender_name

String

Sender's name

sender_address

String

Sender's email or identifier

subject

String

Message subject

body

Text

Full standardized message body

snippet

String

Generated snippet

attachments

JSON

List of attachments (if any)

original_service

String

ID of source plugin/service

received_timestamp

DateTime

Timestamp of message retrieval

distribution_complete

Boolean

True when distribution is complete

📤 Outgoing Message Process

Step 3: Outgoing Message Queue Preparation (Core Responsibility)

Process:

Core identifies members subscribed to specific outgoing services.

Creates outgoing messages for each member/service combination.

Messages placed directly into outgoing queue.

Database Table: Core outgoing queue (core_outgoing_queue)

Field

Type

Description

queue_id

Integer (auto)

Unique queue entry ID

raingull_id

UUID

Original message UUID

member_id

ForeignKey

Member receiving the message

service_id

ForeignKey

Outgoing service ID

formatted_message

Text

Message formatted by outgoing plugin

queued_timestamp

DateTime

Timestamp when message was queued

sent_timestamp

DateTime

Timestamp when sent

send_attempts

Integer

Number of send attempts

status

String

queued, transitions to sent or failed

Step 4: Message Distribution to Platforms (Outgoing Plugin Responsibility)

Process:

Outgoing plugins run scheduled or triggered jobs.

Retrieve messages marked queued from the outgoing queue.

Send messages via configured external platforms (e.g., SMTP).

Update message status upon successful or failed delivery.

🗑️ Data Purging Process

Step 5: Scheduled and Manual Message Purging (Core Responsibility)

When:

Daily scheduled job.

Configurable retention period (default: 30 days).

Admin can manually trigger purge as needed.

How:

Identifies messages older than retention period and marked as fully distributed (distribution_complete=True).

Removes identified messages from:

core_standard_messages

Plugin-specific incoming tables (imap_incoming_messages, etc.)

core_outgoing_queue

Purge Logic Example:

retention_days = 30
purge_before = timezone.now() - timedelta(days=retention_days)

# Purge Core Messages
core_deleted, _ = RainGullMessage.objects.filter(
    received_timestamp__lt=purge_before,
    distribution_complete=True
).delete()

# Purge Plugin Incoming Tables
incoming_deleted, _ = PluginIncomingMessage.objects.filter(
    received_timestamp__lt=purge_before,
    status='processed'
).delete()

# Purge Outgoing Queue Entries
outgoing_deleted, _ = PluginOutgoingMessage.objects.filter(
    sent_timestamp__lt=purge_before,
    status='sent'
).delete()

📌 Lifecycle Summary

Step

Responsibility

Action

Retrieve

Incoming Plugin

Retrieve and store raw messages

Standardize

RainGull Core

Convert messages, generate snippet

Queue

RainGull Core

Queue outgoing messages

Send

Outgoing Plugin

Send messages to external platforms

Purge

RainGull Core

Delete old, fully processed messages

This lifecycle documentation outlines message processing and database handling within RainGull, clearly assigning responsibilities between plugins and core system processes.

