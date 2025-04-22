import imaplib
from django.http import JsonResponse

def test_connection(request, config):
    try:
        # Connect to the IMAP server
        if config.get('use_ssl') == 'TLS':
            server = imaplib.IMAP4_SSL(config['host'], int(config['port']))
        else:
            server = imaplib.IMAP4(config['host'], int(config['port']))
            if config.get('use_ssl') == 'STARTTLS':
                server.starttls()

        # Login and check capabilities
        server.login(config['username'], config['password'])
        
        # Test folder access
        folder = config.get('folder', 'INBOX')
        server.select(folder)
        
        # Logout
        server.logout()

        return JsonResponse({
            'success': True,
            'message': 'Successfully connected to IMAP server and accessed mailbox.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to connect to IMAP server: {str(e)}'
        }) 