import imaplib

def test_imap_connection(imap_server, imap_port, encryption, username, password):
    try:
        if encryption == "SSL/TLS":
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        else:
            mail = imaplib.IMAP4(imap_server, imap_port)
            if encryption == "STARTTLS":
                mail.starttls()

        mail.login(username, password)
        mail.logout()
        return True, "Connection successful."

    except Exception as e:
        return False, str(e)
