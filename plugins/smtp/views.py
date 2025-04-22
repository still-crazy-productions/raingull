import smtplib
from django.http import JsonResponse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_connection(request, config):
    try:
        # Create a test email message
        msg = MIMEMultipart()
        msg['From'] = config.get('from_address', 'test@example.com')
        msg['To'] = config.get('from_address', 'test@example.com')  # Send to ourselves
        msg['Subject'] = 'Raingull SMTP Test'
        msg.attach(MIMEText('This is a test email from Raingull.', 'plain'))

        # Connect to the SMTP server
        if config.get('use_tls') == 'TLS':
            server = smtplib.SMTP_SSL(config['host'], int(config['port']))
        else:
            server = smtplib.SMTP(config['host'], int(config['port']))
            if config.get('use_tls') == 'STARTTLS':
                server.starttls()

        # Login and send test email
        server.login(config['username'], config['password'])
        server.send_message(msg)
        server.quit()

        return JsonResponse({
            'success': True,
            'message': 'Successfully connected to SMTP server and sent test email.'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to connect to SMTP server: {str(e)}'
        }) 