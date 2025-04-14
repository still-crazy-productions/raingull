import imaplib
import email
from email.header import decode_header
from django.utils import timezone
from .models import PluginIncomingIMAPMessage

def fetch_and_store_emails(config):
    # Extract config parameters
    imap_server = config['imap_server']
    imap_port = config['imap_port']
    encryption = config['encryption']
    username = config['imap_username']
    password = config['imap_password']
    inbox_folder = config.get('imap_inbox', 'INBOX')
    processed_folder = config.get('imap_processed_folder', 'INBOX/Processed')
    rejected_folder = config.get('imap_rejected_folder', 'INBOX/Rejected')

    # Connect securely based on encryption settings
    try:
        if encryption == 'SSL/TLS':
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        else:
            mail = imaplib.IMAP4(imap_server, imap_port)
            if encryption == 'STARTTLS':
                mail.starttls()

        mail.login(username, password)
    except imaplib.IMAP4.error as e:
        print(f"IMAP login failed: {e}")
        return

    # Select inbox
    mail.select(inbox_folder)

    # Search for all unseen messages
    status, messages = mail.search(None, 'ALL')

    if status != 'OK':
        print(f"Failed to search inbox: {status}")
        mail.logout()
        return

    message_numbers = messages[0].split()

    for num in message_numbers:
        # Fetch entire raw email
        status, data = mail.fetch(num, '(RFC822)')
        if status != 'OK':
            print(f"Failed to fetch email number {num}: {status}")
            continue

        raw_email = data[0][1].decode('utf-8', errors='replace')

        try:
            # Parse raw email
            parsed_email = email.message_from_bytes(data[0][1])

            message_id = parsed_email.get('Message-ID', '').strip()
            subject, encoding = decode_header(parsed_email.get('Subject', ''))[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or 'utf-8', errors='replace')

            from_ = email.utils.parseaddr(parsed_email.get('From', ''))
            from_name, from_email = from_[0], from_[1]

            to_addresses = email.utils.getaddresses(parsed_email.get_all('To', []))
            cc_addresses = email.utils.getaddresses(parsed_email.get_all('Cc', []))

            to_emails = [email for name, email in to_addresses]
            cc_emails = [email for name, email in cc_addresses]

            sent_date = email.utils.parsedate_to_datetime(parsed_email.get('Date'))

            # Extract plain and HTML body separately
            body_plain, body_html = "", ""
            if parsed_email.is_multipart():
                for part in parsed_email.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    if "attachment" not in content_disposition:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'

                        if content_type == "text/plain":
                            body_plain += payload.decode(charset, errors='replace')
                        elif content_type == "text/html":
                            body_html += payload.decode(charset, errors='replace')
            else:
                payload = parsed_email.get_payload(decode=True)
                charset = parsed_email.get_content_charset() or 'utf-8'
                body_plain = payload.decode(charset, errors='replace')

            # Save to database
            PluginIncomingIMAPMessage.objects.create(
                raw_message=raw_email,
                message_id=message_id,
                from_email=from_email,
                from_name=from_name,
                to_addresses=to_emails,
                cc_addresses=cc_emails,
                subject=subject,
                body_plain=body_plain,
                body_html=body_html,
                in_reply_to=parsed_email.get('In-Reply-To'),
                references=parsed_email.get('References', '').split(),
                sent_timestamp=sent_date,
                received_timestamp=timezone.now(),
                status='new',
            )

            # Move processed email to processed folder
            mail.copy(num, processed_folder)
            mail.store(num, '+FLAGS', '\\Deleted')

        except Exception as e:
            print(f"Error processing email {num}: {e}")
            # Move email to rejected folder if something fails
            mail.copy(num, rejected_folder)
            mail.store(num, '+FLAGS', '\\Deleted')

    # Permanently delete emails flagged for deletion
    mail.expunge()
    mail.logout()
