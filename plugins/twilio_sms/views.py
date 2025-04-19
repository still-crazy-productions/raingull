from django.http import JsonResponse
from twilio.rest import Client
import logging

logger = logging.getLogger(__name__)

def test_connection(request, data):
    """
    Test the connection to Twilio using the provided credentials
    """
    try:
        # Extract credentials from the data
        account_sid = data.get('account_sid')
        auth_token = data.get('auth_token')
        
        if not account_sid or not auth_token:
            return JsonResponse({
                'success': False,
                'message': 'Account SID and Auth Token are required'
            })
        
        # Initialize Twilio client
        client = Client(account_sid, auth_token)
        
        # Try to fetch account info to verify credentials
        account = client.api.accounts(account_sid).fetch()
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully connected to Twilio account {account.friendly_name}'
        })
    except Exception as e:
        logger.error(f"Error testing Twilio connection: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Failed to connect to Twilio: {str(e)}'
        }) 