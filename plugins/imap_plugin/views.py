import imaplib
from django.http import JsonResponse

def test_connection(request, data):
    required_fields = ['imap_server', 'imap_port', 'username', 'password', 'encryption']
    missing_fields = [f for f in required_fields if not data.get(f)]
    if missing_fields:
        return JsonResponse({
            "success": False,
            "message": f"Missing fields: {', '.join(missing_fields)}"
        })

    server = data['imap_server']
    port = int(data['imap_port'])
    user = data['username']
    password = data['password']
    encryption = data['encryption']

    try:
        if encryption == "SSL/TLS":
            mail = imaplib.IMAP4_SSL(server, port)
        else:
            mail = imaplib.IMAP4(server, port)
            if encryption == "STARTTLS":
                mail.starttls()

        mail.login(user, password)
        mail.logout()
        return JsonResponse({"success": True, "message": "Connection successful."})

    except imaplib.IMAP4.error as e:
        return JsonResponse({"success": False, "message": f"IMAP error: {e}"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})
