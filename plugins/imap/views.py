import imaplib
from django.http import JsonResponse

def test_connection(request, data):
    # Map the manifest field names to the expected field names
    field_mapping = {
        'host': 'imap_server',
        'port': 'imap_port',
        'username': 'username',
        'password': 'password',
        'encryption': 'encryption'
    }
    
    # Convert the data to use the expected field names
    converted_data = {}
    for manifest_field, expected_field in field_mapping.items():
        if manifest_field in data:
            converted_data[expected_field] = data[manifest_field]
        elif expected_field in data:
            converted_data[expected_field] = data[expected_field]
    
    required_fields = ['imap_server', 'imap_port', 'username', 'password', 'encryption']
    missing_fields = [f for f in required_fields if not converted_data.get(f)]
    if missing_fields:
        return JsonResponse({
            "success": False,
            "message": f"Missing fields: {', '.join(missing_fields)}"
        })

    server = converted_data['imap_server']
    try:
        port = int(converted_data['imap_port'])
    except ValueError:
        return JsonResponse({
            "success": False,
            "message": "Invalid port number."
        })

    user = converted_data['username']
    password = converted_data['password']
    encryption = converted_data['encryption']

    try:
        if encryption == "SSL/TLS" or encryption == "ssl":
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
            if encryption == "STARTTLS" or encryption == "starttls":
                mail.starttls()

        mail.login(user, password)
        mail.logout()
        return JsonResponse({"success": True, "message": "Connection successful."})

    except imaplib.IMAP4.error as e:
        return JsonResponse({"success": False, "message": f"IMAP error: {e}"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})
