import imaplib

def test_imap_connection(config):
    try:
        encryption = config.get('encryption', 'SSL/TLS')
        imap_host = config['imap_host']
        imap_port = config['imap_port']
        username = config['username']
        password = config['password']

        if encryption == 'SSL/TLS':
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        else:
            mail = imaplib.IMAP4(imap_host, imap_port)
            if encryption == 'STARTTLS':
                mail.starttls()

        mail.login(username, password)
        mail.logout()
        return True, "Successfully connected to IMAP server."

    except Exception as e:
        return False, f"Failed to connect: {str(e)}"
