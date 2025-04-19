import imaplib
import smtplib
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def get_imap_connection(host, port, username, password, use_ssl=True):
    """
    Create and return an IMAP connection.
    
    Args:
        host (str): IMAP server hostname
        port (int): IMAP server port
        username (str): IMAP username
        password (str): IMAP password
        use_ssl (bool): Whether to use SSL/TLS
        
    Returns:
        imaplib.IMAP4 or imaplib.IMAP4_SSL: IMAP connection object
    """
    try:
        if use_ssl:
            connection = imaplib.IMAP4_SSL(host, port)
        else:
            connection = imaplib.IMAP4(host, port)
            
        connection.login(username, password)
        return connection
    except Exception as e:
        logger.error(f"Failed to establish IMAP connection: {str(e)}")
        raise

def get_smtp_connection(host, port, username, password, use_ssl=True):
    """
    Create and return an SMTP connection.
    
    Args:
        host (str): SMTP server hostname
        port (int): SMTP server port
        username (str): SMTP username
        password (str): SMTP password
        use_ssl (bool): Whether to use SSL/TLS
        
    Returns:
        smtplib.SMTP or smtplib.SMTP_SSL: SMTP connection object
    """
    try:
        if use_ssl:
            connection = smtplib.SMTP_SSL(host, port)
        else:
            connection = smtplib.SMTP(host, port)
            connection.starttls()
            
        connection.login(username, password)
        return connection
    except Exception as e:
        logger.error(f"Failed to establish SMTP connection: {str(e)}")
        raise 